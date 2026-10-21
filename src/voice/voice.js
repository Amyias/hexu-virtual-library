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
    synthesis?.cancel();
  }

  async function speak(text) {
    cancel();
    const mine = generation;
    const pieces = splitSentences(text);
    if (!pieces.length) return;
    if (!(await probe()) || mine !== generation) {
      if (mine === generation) speakSystem(text);
      return;
    }
    controller = new AbortController();
    const { signal } = controller;
    engine = "local";
    busy = true;
    try {
      await speakLocal(pieces, mine, signal);
    } finally {
      if (mine === generation) busy = false;
    }
  }

  async function speakLocal(pieces, mine, signal) {
    let next = fetchClip(pieces[0], signal);
    for (let i = 0; i < pieces.length; i++) {
      let blob;
      try {
        blob = await next;
      } catch {
        // The local voice failed mid-reply: say the rest with the system voice instead.
        if (mine === generation) speakSystem(pieces.slice(i).join(""));
        return;
      }
      if (mine !== generation) return;
      next = i + 1 < pieces.length ? fetchClip(pieces[i + 1], signal) : null;
      next?.catch(() => {}); // handled when awaited; avoid an unhandled rejection meanwhile
      try {
        await play(blob, mine);
      } catch {
        if (mine === generation) speakSystem(pieces.slice(i).join(""));
        return;
      }
      if (mine !== generation) return;
    }
  }

  return {
    probe,
    speak,
    cancel,
    get available() {
      return Boolean(localInfo) || Boolean(synthesis && Utterance);
    },
    isSpeaking: () => busy || Boolean(audio) || Boolean(synthesis?.speaking),
    getState: () => ({ local: localInfo, engine, speaking: busy || Boolean(audio) }),
  };
}

export const voice = createVoice();
