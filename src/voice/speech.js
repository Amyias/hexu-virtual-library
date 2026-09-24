import { wakeRE } from "./intent.js";
/** Browser recognizer lifecycle, independent of rendering and animation. */
export function createSpeech({ $, notice, wake, processText, getPhase }) {
  // Real Web Speech API: one live recognizer, interim wake-up, final intent, automatic restart.
  const Recognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null,
    wanted = false,
    running = false,
    starting = false,
    restartTimer = null,
    failures = 0,
    retryDelay = 450,
    interimWakes = new Set(),
    lastNetworkError = false;
  function micStatus(text, kind = "off") {
    $("micStatus").textContent = text;
    $("micDot").className =
      "status-dot " +
      (kind === "live" ? "live" : kind === "error" ? "error" : "");
    document.body.classList.toggle("listening", kind === "live");
    $("micButton").classList.toggle("active", wanted);
    $("micButton").textContent = wanted ? "◉ 关闭语音感知" : "◉ 启动语音感知";
  }
  function scheduleRecognition() {
    clearTimeout(restartTimer);
    if (wanted && !document.hidden)
      restartTimer = setTimeout(startRecognition, retryDelay);
  }
  function startRecognition() {
    if (!wanted || running || starting || document.hidden) return;
    try {
      starting = true;
      recognition.start();
      micStatus("正在连接语音服务");
    } catch (e) {
      starting = false;
      if (e.name === "InvalidStateError") {
        scheduleRecognition();
      } else {
        wanted = false;
        micStatus("无法启动，请重新授权", "error");
        notice(e.message);
      }
    }
  }
  if (Recognition) {
    recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => {
      running = true;
      starting = false;
      interimWakes.clear();
      lastNetworkError = false;
      micStatus("监听中：请说“小和”", "live");
    };
    recognition.onresult = (e) => {
      failures = 0;
      retryDelay = 450;
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const text = e.results[i][0].transcript.trim();
        $("transcript").textContent = "听到：" + text;
        /* Optional TTS echo gate; ASR remains running. Headphones recommended. */ if (
          window.speechSynthesis?.speaking
        )
          continue;
        if (!e.results[i].isFinal) {
          if (
            wakeRE.test(text) &&
            !interimWakes.has(i) &&
            getPhase() === "IDLE"
          ) {
            interimWakes.add(i);
            wake();
          }
          continue;
        }
        const already = interimWakes.has(i);
        interimWakes.delete(i);
        processText(text, false, already);
      }
    };
    recognition.onerror = (e) => {
      if (e.error === "aborted") return;
      if (
        ["not-allowed", "service-not-allowed", "audio-capture"].includes(
          e.error,
        )
      ) {
        wanted = false;
        clearTimeout(restartTimer);
        micStatus(
          e.error === "audio-capture"
            ? "未找到可用麦克风"
            : "麦克风或识别服务未获授权",
          "error",
        );
        notice("请检查浏览器站点麦克风权限，使用 localhost / HTTPS 后重试。");
      } else if (e.error === "network") {
        lastNetworkError = true;
        failures++;
        retryDelay = Math.min(12000, 1000 * 2 ** failures);
        micStatus("语音网络中断，等待重连", "error");
        if (failures >= 5) {
          wanted = false;
          micStatus("语音服务不可达，请点击重试", "error");
          notice("浏览器识别服务无法连接。可先使用下方文字找书。");
        }
      }
    };
    recognition.onend = () => {
      running = false;
      starting = false;
      if (wanted) {
        if (!lastNetworkError)
          micStatus(document.hidden ? "页面后台，语音暂停" : "识别重连中");
        scheduleRecognition();
      } else if (!$("micDot").classList.contains("error"))
        micStatus("语音感知已关闭");
    };
  } else {
    micStatus("浏览器不支持语音识别", "error");
    $("micButton").disabled = true;
    $("transcript").textContent =
      "请改用支持 Web Speech API 的 Chrome / Edge，或使用文字找书";
  }
  $("micButton").onclick = () => {
    if (!recognition) return;
    wanted = !wanted;
    failures = 0;
    retryDelay = 450;
    clearTimeout(restartTimer);
    if (wanted) {
      if (!window.isSecureContext && location.protocol !== "file:") {
        wanted = false;
        notice("麦克风需要 HTTPS 或 localhost 环境。");
        return;
      }
      startRecognition();
    } else {
      recognition.abort();
      micStatus("语音感知已关闭");
    }
  };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearTimeout(restartTimer);
      if (wanted) {
        recognition?.abort();
        micStatus("页面后台，语音暂停");
      }
    } else scheduleRecognition();
  });
  window.addEventListener("pagehide", () => {
    wanted = false;
    clearTimeout(restartTimer);
    recognition?.abort();
    window.speechSynthesis?.cancel();
  });

  return {
    getState: () => ({ wanted, running }),
    stop() {
      wanted = false;
      clearTimeout(restartTimer);
      recognition?.abort();
    },
  };
}
