import { findBook, wakeRE } from "./intent.js";
/* Browser recognizer lifecycle, independent of rendering and animation. */
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
  /* Every hypothesis the recogniser offers, best first. Engines that expose only
     alternative 0 degrade to a single-element list. */
  function alternatives(result) {
    const list = [];
    for (let i = 0; i < (result?.length ?? 1); i++) {
      const text = result[i]?.transcript?.trim();
      if (text) list.push(text);
    }
    return list;
  }
  /* Bounded record of what was heard versus what was used. Without it a recognition
     error and a matching miss look identical in the interface — both just do nothing. */
  const recent = [];
  function record(heard, used, candidates, matched) {
    recent.push({ heard, used, candidates, matched });
    if (recent.length > 20) recent.shift();
    $("voiceLog").textContent = recent
      .slice(-5)
      .reverse()
      .map((r) =>
        r.matched
          ? `听到：${r.heard}${r.used !== r.heard ? ` → 采用候选：${r.used}` : ""} ✓`
          : `听到：${r.heard} ✗ ${r.candidates > 1 ? `${r.candidates} 条候选均未匹配` : "未匹配馆藏"}`,
      )
      .join("\n");
  }
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
    /* Ask for several hypotheses: they are free, and one of them often carries the
       correct title when the top-scoring one is a homophone slip. */
    recognition.maxAlternatives = 5;
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
        const heard = alternatives(e.results[i]);
        const text = heard[0] ?? "";
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
        /* Fall back to a lower-ranked hypothesis only when the top one matches no
           catalogue entry. A lower one may not contain the wake word, and depending
           on the 25s window for that would make every rescue fragile. */
        const chosen = findBook(text)
          ? text
          : heard.find((candidate) => findBook(candidate)) ?? text;
        const matched = Boolean(findBook(chosen));
        record(text, chosen, heard.length, matched);
        const already = interimWakes.has(i);
        interimWakes.delete(i);
        processText(chosen, false, already);
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
    getState: () => ({ wanted, running, recent }),
    stop() {
      wanted = false;
      clearTimeout(restartTimer);
      recognition?.abort();
    },
  };
}
