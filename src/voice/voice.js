/* 小和's spoken replies. The local Taiwan-Mandarin voice (PrimeTTS 欣然, POST /tts) when the
   service offers it; otherwise, or if it fails mid-reply, the browser's speechSynthesis with a
   Taiwan voice preferred. One module, so the recogniser's echo gate and every cancel cover both. */
const LOCAL_TIMEOUT = 8000;
// Sentence-sized pieces: the first one is heard after a fraction of a second, and the next is
// synthesised while the current one plays.
const SENTENCE = /[^。！？!?；;\n]+[。！？!?；;\n]*|[。！？!?；;\n]+/g;
const PREFERRED_SYSTEM = [/HsiaoChen/i, /HsiaoYu/i, /Yating/i, /Hanhan/i];

export function splitSentences(text, max = 120) {
  const pieces = [];
  for (const sentence of String(text).match(SENTENCE) ?? []) {
    let rest = sentence.trim();
    // An over-long sentence is cut at its commas, then hard at the limit.
    while (rest.length > max) {
      const cut = Math.max(rest.lastIndexOf("，", max), rest.lastIndexOf(",", max));
      const at = cut > max / 3 ? cut + 1 : max;
      pieces.push(rest.slice(0, at).trim());
      rest = rest.slice(at).trim();
    }
    if (rest && /[\p{L}\p{N}]/u.test(rest)) pieces.push(rest);
  }
  return pieces;
}

/** What part of a growing reply, from `from` on, is ready to be spoken: up to its last sentence
 *  end, or a comma once a sentence runs long, so a reply without full stops still gets going. */
export function completedPart(text, from = 0, long = 60) {
  const rest = text.slice(from);
  const end = Math.max(...[..."。！？!?；;\n"].map((mark) => rest.lastIndexOf(mark)));
  if (end >= 0) return rest.slice(0, end + 1);
  if (rest.length < long) return "";
  const comma = Math.max(rest.lastIndexOf("，"), rest.lastIndexOf(","), rest.lastIndexOf("、"));
  return comma > 0 ? rest.slice(0, comma + 1) : "";
}

/** Text as it should sound: Markdown marks and citation numbers are for the eye only. */
export function speakable(text) {
  return String(text)
    .replace(/\[\d+\]/g, "")
    .replace(/[*#`>_~|]/g, "");
}

export function pickSystemVoice(voices) {
  for (const pattern of PREFERRED_SYSTEM) {
    const voice = voices.find((v) => pattern.test(v.name) && v.lang?.startsWith("zh"));
    if (voice) return voice;
  }
  return (
    voices.find((v) => /^zh[-_]TW/i.test(v.lang)) ?? voices.find((v) => v.lang?.startsWith("zh"))
  );
}

export function createVoice({
  fetch: request = (...args) => globalThis.fetch(...args),
  synthesis = globalThis.speechSynthesis,
  Utterance = globalThis.SpeechSynthesisUtterance,
  createAudio = (url) => new Audio(url),
  urls = globalThis.URL,
} = {}) {
  let local = null; // probe promise -> voice info or null
  let localInfo = null;
  let generation = 0;
  let busy = false; // inside a local reply, including the gap while the next sentence is made
  let audio = null;
  let stopPlayback = null; // settles the clip that is playing when a reply is cancelled
  let releaseWait = null; // ends a stream's wait for its next sentence when it is cancelled
  let controller = null;
  let engine = "none"; // what the last reply actually used

  function probe() {
    local ??= request("/tts/ready", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null)
      .then((info) => (localInfo = info));
    return local;
  }

  function speakSystem(text) {
    if (!synthesis || !Utterance) return false;
    const utterance = new Utterance(text);
    const voice = pickSystemVoice(synthesis.getVoices?.() ?? []);
    utterance.lang = voice?.lang ?? "zh-CN";
    if (voice) utterance.voice = voice;
    utterance.rate = 1;
    synthesis.speak(utterance);
    engine = "system";
    return true;
  }

  async function fetchClip(text, signal) {
    const timer = setTimeout(() => controller?.abort(), LOCAL_TIMEOUT);
    try {
      const response = await request("/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal,
      });
      if (!response.ok) throw new Error("tts " + response.status);
      return await response.blob();
    } finally {
      clearTimeout(timer);
    }
  }

  function play(blob, mine) {
    return new Promise((resolve, reject) => {
      if (mine !== generation) return resolve();
      const url = urls.createObjectURL(blob);
      const element = (audio = createAudio(url));
      const done = (error) => {
        urls.revokeObjectURL(url);
        if (audio === element) audio = null;
        if (stopPlayback === done) stopPlayback = null;
        error ? reject(error) : resolve();
      };
      stopPlayback = done;
      element.onended = () => done();
      element.onerror = () => done(new Error("audio playback failed"));
      element.play().catch(done);
    });
  }

  function cancel() {
    generation++;
    busy = false;
    controller?.abort();
    controller = null;
    if (audio) {
      audio.pause();
      audio = null;
    }
    stopPlayback?.(); // a paused clip never fires "ended"; settle it so the reply can finish
    releaseWait?.();
    releaseWait = null;
    synthesis?.cancel();
  }

  /** A reply that may still be arriving. push(text) with the whole reply so far: every sentence
   *  that is complete is queued and spoken in turn, the next synthesised while one plays. end()
   *  queues the rest. Starting a stream silences whatever was being said. */
  function stream() {
    cancel();
    const mine = generation;
    const queue = [];
    let consumed = 0;
    let ended = false;
    let wake = null;
    let fallback = false; // the local voice failed: say everything from here with the system voice
    const signalMore = () => {
      wake?.();
      wake = null;
    };
    function enqueue(text) {
      const pieces = splitSentences(speakable(text));
      if (!pieces.length) return;
      if (fallback) speakSystem(pieces.join(""));
      else queue.push(...pieces);
      signalMore();
    }
    async function next() {
      while (!queue.length) {
        if (ended || mine !== generation) return null;
        await new Promise((resolve) => (wake = releaseWait = resolve));
      }
      return mine === generation ? queue.shift() : null;
    }
    const done = (async () => {
      busy = true;
      try {
        const local = await probe();
        if (mine !== generation) return;
        if (!local) {
          // System speech queues utterances itself: hand over each batch as it completes.
          fallback = true;
          if (queue.length) speakSystem(queue.splice(0).join(""));
          return;
        }
        controller = new AbortController();
        const { signal } = controller;
        engine = "local";
        let current = await next();
        let clip = current && fetchClip(current, signal);
        while (current) {
          let blob;
          try {
            blob = await clip;
            if (mine !== generation) return;
            // Synthesise the following sentence while this one plays.
            const upcoming = queue.length ? queue.shift() : null;
            const upcomingClip = upcoming && fetchClip(upcoming, signal);
            upcomingClip?.catch(() => {}); // handled when awaited
            await play(blob, mine);
            if (mine !== generation) return;
            current = upcoming ?? (await next());
            clip = upcoming ? upcomingClip : current && fetchClip(current, signal);
          } catch {
            // The local voice failed mid-reply: say the rest with the system voice instead.
            if (mine !== generation) return;
            fallback = true;
            speakSystem([current, ...queue.splice(0)].join(""));
            return;
          }
        }
      } finally {
        if (mine === generation) busy = false;
      }
    })();
    return {
      push(text) {
        if (mine !== generation) return;
        const ready = completedPart(String(text), consumed);
        if (!ready) return;
        consumed += ready.length;
        enqueue(ready);
      },
      end(text = "") {
        if (mine !== generation) return done;
        enqueue(String(text).slice(consumed));
        consumed = String(text).length;
        ended = true;
        signalMore();
        return done;
      },
      done,
    };
  }

  function speak(text) {
    return stream().end(text);
  }

  return {
    probe,
    speak,
    stream,
    cancel,
    get available() {
      return Boolean(localInfo) || Boolean(synthesis && Utterance);
    },
    isSpeaking: () => busy || Boolean(audio) || Boolean(synthesis?.speaking),
    getState: () => ({ local: localInfo, engine, speaking: busy || Boolean(audio) }),
  };
}

export const voice = createVoice();
