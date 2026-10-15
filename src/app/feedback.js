/* What the reader sees and hears back: the corner notice, the speech bubble above the orb, and —
   when switched on with ♪ — the same words spoken aloud. */
export function createFeedback($) {
  let noticeTimer, bubbleTimer;
  let speaking = false;

  function notice(text) {
    $("notice").textContent = text;
    $("notice").style.display = "block";
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => ($("notice").style.display = "none"), 6500);
  }

  function bubble(text, hold = 6500) {
    $("bubble").textContent = text;
    $("bubble").classList.add("show");
    clearTimeout(bubbleTimer);
    if (hold) bubbleTimer = setTimeout(hideBubble, hold);
  }

  function hideBubble() {
    $("bubble").classList.remove("show");
  }

  function say(text) {
    bubble(text);
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
    if (!speaking) window.speechSynthesis?.cancel();
    notice(speaking ? "语音播报已开启，建议使用耳机。" : "语音播报已关闭，气泡回应保持开启。");
  }

  return { notice, bubble, hideBubble, say, toggleSpeaking };
}
