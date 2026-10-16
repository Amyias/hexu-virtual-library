import { createDialogueSounds } from "./dialogue-sounds.js";
import { createPixelDialogue } from "./pixel-dialogue.js";

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
  function say(text, hold = 6500, options = {}) {
    bubble(text, hold, speaking && Boolean(window.speechSynthesis), options);
    if (!speaking || !window.speechSynthesis) return;
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 1;
    const voice = speechSynthesis.getVoices().find((v) => v.lang.startsWith("zh"));
    if (voice) utterance.voice = voice;
    speechSynthesis.speak(utterance);
  }
  function toggleSpeaking() {
    speaking = !speaking;
    $("sound").style.background = speaking ? "#adc5ad" : "#f9fbf0cf";
    $("sound").title = speaking ? "关闭语音播报" : "开启语音播报";
    $("sound").setAttribute("aria-label", $("sound").title);
    $("sound").setAttribute("aria-pressed", String(speaking));
    if (!speaking) window.speechSynthesis?.cancel();
    notice(speaking ? "语音播报已开启，建议使用耳机。" : "语音播报已关闭，像素气泡回应保持开启。");
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
    toggleSpeaking,
    toggleSounds,
    getState: () => ({ ...dialogue.getState(), sound: sounds.getState(), speaking }),
  };
}
