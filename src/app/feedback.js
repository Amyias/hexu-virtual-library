import { createDialogueSounds } from "./dialogue-sounds.js";
import { createPixelDialogue } from "./pixel-dialogue.js";
import { voice } from "../voice/voice.js";

export function createFeedback($) {
  let noticeTimer;
  let speaking = false;
  const sounds = createDialogueSounds();
  const dialogue = createPixelDialogue($("bubble"), sounds);
  const unlock = () => {
    sounds.unlock();
  };
  document.addEventListener("pointerdown", unlock, { capture: true, passive: true });
  document.addEventListener("keydown", unlock, { capture: true });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) dialogue.hide();
  });
  window.addEventListener("pagehide", () => dialogue.hide());

  function notice(text) {
    $("notice").textContent = text;
    $("notice").style.display = "block";
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => ($("notice").style.display = "none"), 6500);
  }
  function bubble(text, hold = 6500, voiced = false, options = {}) {
    dialogue.show(text, hold, { ...options, typingSound: !voiced });
  }
  /** options.silent: show without speaking, for placeholders such as 「正在回应…」 that would
   *  otherwise be read aloud and compete with the real answer. */
  function say(text, hold = 6500, options = {}) {
    if (options.silent) {
      voice.cancel(); // a new question stops the previous answer being read out
      bubble(text, hold, false, options);
      return;
    }
    bubble(text, hold, speaking && voice.available, options);
    if (speaking) voice.speak(text);
  }
  /** A reply that is still being written: the bubble types as text arrives and, with speech on,
   *  each finished sentence is spoken while the model writes the next. */
  function stream(first, options = {}) {
    const voiced = speaking && voice.available;
    dialogue.show(first, 0, { ...options, interactive: true, typingSound: !voiced });
    const spoken = speaking ? voice.stream() : null;
    spoken?.push(first);
    return {
      update(text) {
        dialogue.extend(text);
        spoken?.push(text);
      },
      /** Resolves once the spoken reply has finished (at once when speech is off). */
      finish(text, settled = {}) {
        dialogue.extend(text);
        dialogue.settle(settled);
        return spoken ? spoken.end(text) : Promise.resolve();
      },
    };
  }
  function toggleSpeaking() {
    speaking = !speaking;
    $("sound").style.background = speaking ? "#adc5ad" : "#f9fbf0cf";
    $("sound").title = speaking ? "关闭语音播报" : "开启语音播报";
    $("sound").setAttribute("aria-label", $("sound").title);
    $("sound").setAttribute("aria-pressed", String(speaking));
    if (!speaking) {
      voice.cancel();
      notice("语音播报已关闭，像素气泡回应保持开启。");
      return;
    }
    voice
      .probe()
      .then((local) =>
        notice(
          local
            ? `语音播报已开启：本机台湾女声「${local.voice}」（AI 合成语音），建议使用耳机。`
            : "语音播报已开启：使用系统语音，建议使用耳机。",
        ),
      );
  }
  function paintSoundButton() {
    const enabled = sounds.getState().enabled;
    $("dialogueSound").setAttribute("aria-pressed", String(enabled));
    $("dialogueSound").title = enabled ? "关闭气泡与打字音效" : "开启气泡与打字音效";
    $("dialogueSound").setAttribute("aria-label", $("dialogueSound").title);
    $("dialogueSound").classList.toggle("active", enabled);
  }
  function toggleSounds() {
    const enabled = sounds.setEnabled(!sounds.getState().enabled);
    paintSoundButton();
    if (enabled)
      sounds.unlock().then((ready) => {
        if (ready && sounds.getState().enabled) sounds.pop();
      });
    notice(enabled ? "气泡与打字音效已开启。" : "气泡与打字音效已关闭，文字回应保持开启。");
  }
  paintSoundButton();
  return {
    notice,
    bubble,
    hideBubble: dialogue.hide,
    say,
    stream,
    toggleSpeaking,
    toggleSounds,
    getState: () => ({
      ...dialogue.getState(),
      sound: sounds.getState(),
      speaking,
      voice: voice.getState(),
    }),
  };
}
