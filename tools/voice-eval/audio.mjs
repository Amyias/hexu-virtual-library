/* 语音验收的音频处理：读 WAV，并按程序真实的断句规则切段。 */
import { createSegmenter, resample, SEGMENT } from "../../src/voice/server-asr.js";

const FRAME_MS = (SEGMENT.FRAME / SEGMENT.TARGET_RATE) * 1000;

/** 16-bit PCM WAV → Float32 samples at 16 kHz. */
export function readWav(buffer) {
  if (buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WAVE")
    throw new Error("不是 WAV 文件");
  let offset = 12;
  let format = null;
  while (offset + 8 <= buffer.length) {
    const id = buffer.toString("ascii", offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    const body = offset + 8;
    if (id === "fmt ")
      format = {
        channels: buffer.readUInt16LE(body + 2),
        rate: buffer.readUInt32LE(body + 4),
        bits: buffer.readUInt16LE(body + 14),
      };
    if (id === "data") {
      if (!format || format.bits !== 16) throw new Error("只支持 16 位 PCM");
      const count = Math.floor(size / 2 / format.channels);
      const samples = new Float32Array(count);
      for (let i = 0; i < count; i++)
        samples[i] = buffer.readInt16LE(body + i * 2 * format.channels) / 32768;
      return resample(samples, format.rate, SEGMENT.TARGET_RATE);
    }
    offset = body + size + (size % 2);
  }
  throw new Error("WAV 缺少数据块");
}

/** Cut one recording as the program would. Each segment: its samples and how long the program
 *  waited after the last loud frame before sending it (the silence that ends a segment). */
export function segmentsOf(samples) {
  const segmenter = createSegmenter();
  const segments = [];
  const frames = Math.ceil(samples.length / SEGMENT.FRAME) + SEGMENT.SILENCE_FRAMES;
  let lastLoud = -1;
  for (let i = 0; i < frames; i++) {
    // Past the end, quiet frames close a segment the recording stopped in the middle of.
    const frame = new Float32Array(SEGMENT.FRAME);
    frame.set(samples.subarray(i * SEGMENT.FRAME, (i + 1) * SEGMENT.FRAME));
    let sum = 0;
    for (const value of frame) sum += value * value;
    if (Math.sqrt(sum / frame.length) >= SEGMENT.SPEECH_RMS) lastLoud = i;
    const done = segmenter.push(frame);
    if (done) {
      const joined = new Float32Array(done.length * SEGMENT.FRAME);
      done.forEach((part, index) => joined.set(part, index * SEGMENT.FRAME));
      segments.push({ samples: joined, tailMs: Math.round((i - lastLoud) * FRAME_MS) });
    }
  }
  return segments;
}
