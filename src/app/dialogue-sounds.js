// Original 8-bit UI sounds, synthesised locally. No audio files or network requests.
export function createDialogueSounds({ host = globalThis.window, storage } = {}) {
  let enabled = true;
  try {
    storage ??= host?.localStorage;
    enabled = storage?.getItem("hexu-dialogue-sound") !== "off";
  } catch {}
  let context = null,
    master = null,
    lastType = -Infinity,
    pops = 0,
    ticks = 0;
  const voices = new Set();

  async function unlock() {
    if (!enabled) return false;
    const Audio = host?.AudioContext || host?.webkitAudioContext;
    if (!Audio) return false;
    try {
      if (!context) {
        context = new Audio();
        master = context.createGain();
        master.gain.value = 0.18;
        master.connect(context.destination);
      }
      if (context.state === "suspended") await context.resume();
      return context.state === "running";
    } catch {
      return false;
    }
  }
  function tone({ type, start, end, duration, peak }) {
    if (!enabled || context?.state !== "running") return false;
    const now = context.currentTime;
    const oscillator = context.createOscillator(),
      gain = context.createGain();
    const filter = context.createBiquadFilter();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(start, now);
    oscillator.frequency.exponentialRampToValueAtTime(end, now + duration);
    filter.type = "lowpass";
    filter.frequency.value = 2400;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(peak, now + 0.004);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
    oscillator.connect(filter);
    filter.connect(gain);
    gain.connect(master);
    const voice = { oscillator, filter, gain };
    voices.add(voice);
    oscillator.onended = () => {
      oscillator.disconnect();
      filter.disconnect();
      gain.disconnect();
      voices.delete(voice);
    };
    oscillator.start(now);
    oscillator.stop(now + duration + 0.005);
    return true;
  }
  function stop() {
    for (const { oscillator, gain } of voices) {
      gain.gain.cancelScheduledValues(context.currentTime);
      gain.gain.setValueAtTime(0, context.currentTime);
      try {
        oscillator.stop();
      } catch {}
    }
    lastType = -Infinity;
  }
  function pop() {
    if (tone({ type: "sine", start: 780, end: 390, duration: 0.12, peak: 0.32 })) pops++;
  }
  function type(glyph, index) {
    if (/^[\s\p{P}\p{S}]+$/u.test(glyph)) return;
    if (!enabled || context?.state !== "running" || context.currentTime - lastType < 0.045) return;
    const pitch = 490 + ((index * 7) % 5) * 42;
    if (tone({ type: "square", start: pitch, end: pitch * 0.88, duration: 0.026, peak: 0.13 })) {
      ticks++;
      lastType = context.currentTime;
    }
  }
  function setEnabled(value) {
    enabled = Boolean(value);
    if (!enabled) stop();
    try {
      storage?.setItem("hexu-dialogue-sound", enabled ? "on" : "off");
    } catch {}
    return enabled;
  }
  return {
    unlock,
    pop,
    type,
    stop,
    setEnabled,
    getState: () => ({
      enabled,
      state: context?.state || "locked",
      pops,
      ticks,
      activeVoices: voices.size,
    }),
  };
}
