/* Server-side speech recognition.

The browser's own Web Speech API is hard-wired to the browser vendor's cloud service, and on
networks where that service is unreachable it starts, reports itself healthy, and then never
returns a single result. This transport avoids it: the page records a segment, posts it to the
deployment's local model, and dispatches the transcript through exactly the same
`processText` entry point the Web Speech path uses.

Only activated when the page is served by tools/asr-server.py — a plain static deployment
fails the probe and keeps using the Web Speech API unchanged. */

const PROBE_PATH = "/asr/ready";
const ASR_PATH = "/asr";
const TARGET_RATE = 16000;
const FRAME = 1024; // 64 ms at 16 kHz — fine enough to place a 700 ms silence reliably
const SPEECH_RMS = 0.012;
const SILENCE_FRAMES = 11; // ~0.7 s of quiet ends a segment
const PREROLL_FRAMES = 4; // ~0.25 s kept from before the onset so the first word is not clipped
const MAX_SEGMENT_FRAMES = Math.round((15 * TARGET_RATE) / FRAME);
const MIN_SEGMENT_FRAMES = 5;

/** Resolve to the backend's readiness payload, or null when this deployment has no backend. */
export async function probeServerAsr() {
  try {
    const response = await fetch(PROBE_PATH, { cache: "no-store" });
    if (!response.ok) return null;
    const info = await response.json();
    return info && info.ready ? info : null;
  } catch {
    /* Static deployment, or the probe was blocked: not an error, just no backend. */
    return null;
  }
}

export function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset, value) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return new Blob([view], { type: "audio/wav" });
}

/** Linear resample; only used when the browser refuses to open the context at 16 kHz. */
export function resample(samples, from, to) {
  if (from === to) return samples;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const position = i * ratio;
    const left = Math.floor(position);
    const mix = position - left;
    out[i] = samples[left] * (1 - mix) + (samples[left + 1] ?? samples[left]) * mix;
  }
  return out;
}

function rms(frame) {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return Math.sqrt(sum / frame.length);
}

/** Cut a stream of FRAME-sample frames into speech segments by loudness: a segment opens on a
 *  frame at or above SPEECH_RMS (keeping a little audio from before it), and closes after
 *  SILENCE_FRAMES quiet frames or at MAX_SEGMENT_FRAMES. push(frame) returns the finished
 *  segment's frames, or null; segments shorter than MIN_SEGMENT_FRAMES are dropped. Pure, so the
 *  voice evaluation (tools/voice-eval.mjs) replays recordings through exactly this rule. */
export function createSegmenter() {
  let speaking = false;
  let silence = 0;
  let preroll = [];
  let segment = [];

  function reset() {
    speaking = false;
    silence = 0;
    preroll = [];
    segment = [];
  }

  function finish() {
    const frames = segment;
    reset();
    return frames.length < MIN_SEGMENT_FRAMES ? null : frames;
  }

  return {
    push(frame) {
      const level = rms(frame);
      if (!speaking) {
        if (level >= SPEECH_RMS) {
          speaking = true;
          silence = 0;
          segment = [...preroll, frame];
          preroll = [];
        } else {
          preroll.push(frame);
          if (preroll.length > PREROLL_FRAMES) preroll.shift();
        }
        return null;
      }
      segment.push(frame);
      if (level < SPEECH_RMS) {
        silence++;
        if (silence >= SILENCE_FRAMES) return finish();
      } else silence = 0;
      return segment.length >= MAX_SEGMENT_FRAMES ? finish() : null;
    },
    reset,
  };
}

export const SEGMENT = { FRAME, TARGET_RATE, SPEECH_RMS, SILENCE_FRAMES };

export function createServerAsr({ post, onText, onStatus, onError }) {
  let stream = null;
  let context = null;
  let node = null;
  let source = null;
  let wanted = false;
  let busy = false; // a segment is being transcribed; ignore audio until it returns
  const segmenter = createSegmenter();
  const reset = () => segmenter.reset();

  async function flush(frames) {
    busy = true;
    onStatus("正在识别", "live");
    let wav;
    try {
      const rate = context.sampleRate;
      const joined = new Float32Array(frames.length * FRAME);
      frames.forEach((frame, i) => joined.set(frame, i * FRAME));
      wav = encodeWav(resample(joined, rate, TARGET_RATE), TARGET_RATE);
    } catch (error) {
      busy = false;
      onError("录音编码失败：" + error.message);
      return;
    }
    try {
      const response = await fetch(ASR_PATH, { method: "POST", body: wav });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        onError(payload.error || "识别服务返回 " + response.status);
      } else if (payload.text) {
        onText(payload.text);
      } else {
        onStatus("监听中：请说“小和”", "live");
      }
    } catch (error) {
      onError("无法连接识别服务：" + error.message);
    } finally {
      busy = false;
      if (wanted) onStatus("监听中：请说“小和”", "live");
    }
  }

  function onFrame(event) {
    if (!wanted || busy) return;
    const frames = segmenter.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    if (frames) flush(frames);
  }

  return {
    async start() {
      wanted = true;
      busy = false;
      reset();
      onStatus("正在连接语音服务");
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
      } catch (error) {
        wanted = false;
        onError(
          error && error.name === "NotFoundError"
            ? "未找到可用麦克风"
            : "麦克风未获授权，请检查站点权限",
        );
        return false;
      }
      context = new AudioContext({ sampleRate: TARGET_RATE });
      if (context.state === "suspended") await context.resume();
      source = context.createMediaStreamSource(stream);
      node = context.createScriptProcessor(FRAME, 1, 1);
      node.onaudioprocess = onFrame;
      source.connect(node);
      node.connect(context.destination); // required for the node to run; it outputs nothing
      onStatus("监听中：请说“小和”", "live");
      return true;
    },
    stop() {
      wanted = false;
      busy = false;
      reset();
      if (node) {
        node.onaudioprocess = null;
        node.disconnect();
        node = null;
      }
      if (source) {
        source.disconnect();
        source = null;
      }
      if (context) {
        context.close();
        context = null;
      }
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
        stream = null;
      }
    },
    get running() {
      return Boolean(node);
    },
    get paused() {
      return busy;
    },
  };
}
