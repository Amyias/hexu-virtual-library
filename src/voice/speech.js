import { findBook, wakeRE } from "./intent.js";
import { createServerAsr, probeServerAsr } from "./server-asr.js";
/* Browser recognizer lifecycle, independent of rendering and animation. */
export function createSpeech({ $, notice, wake, processText, getPhase, lookupBook = findBook }) {
  // Real Web Speech API: one live recognizer, interim wake-up, final intent, automatic restart.
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null,
    wanted = false,
    running = false,
    starting = false,
    restartTimer = null,
    failures = 0,
    retryDelay = 450,
    interimWakes = new Set(),
    lastNetworkError = false,
    resultSeen = false,
    silentTimer = null,
    serverAsr = null,
    autoKick = null;
  /* A recogniser can report "listening" and then never deliver a single result, because the
     fault is upstream of this module: no audio is reaching the browser, or the browser vendor's
     speech service is not answering. Both look identical to a healthy session, so say so rather
     than leaving the user guessing why nothing happens. */
  function watchForSilence() {
    clearTimeout(silentTimer);
    silentTimer = setTimeout(() => {
      if (!wanted || resultSeen) return;
      micStatus("监听中，但收不到识别结果", "error");
      notice(
        "麦克风已授权、识别器也在运行，但浏览器一次结果都没回传。通常是这两种原因：系统麦克风被静音或输入设备选错；或浏览器厂商的识别服务连不上。可先打开右下角「和 · 对话」使用文字输入。",
      );
    }, 20000);
  }
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
      "status-dot " + (kind === "live" ? "live" : kind === "error" ? "error" : "");
    document.body.classList.toggle("listening", kind === "live");
    $("micButton").classList.toggle("active", wanted);
    $("micButton").textContent = wanted ? "◉ 关闭语音感知" : "◉ 启动语音感知";
  }
  function scheduleRecognition() {
    clearTimeout(restartTimer);
    if (wanted && !document.hidden) restartTimer = setTimeout(startRecognition, retryDelay);
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
      watchForSilence();
      /* Deliberately does not clear lastNetworkError: the automatic restart that follows a
         network failure would otherwise reset the status to a healthy "listening" and hide the
         fault completely. It clears when a result actually arrives. */
      micStatus(
        lastNetworkError ? "监听中，但识别服务未响应" : "监听中：请说“小和”",
        lastNetworkError ? "error" : "live",
      );
    };
    recognition.onresult = (e) => {
      failures = 0;
      retryDelay = 450;
      // A delivered result is proof the service is reachable again.
      lastNetworkError = false;
      resultSeen = true;
      clearTimeout(silentTimer);
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const heard = alternatives(e.results[i]);
        const text = heard[0] ?? "";
        $("transcript").textContent = "听到：" + text;
        /* Optional TTS echo gate; ASR remains running. Headphones recommended. */ if (
          window.speechSynthesis?.speaking
        )
          continue;
        if (!e.results[i].isFinal) {
          if (wakeRE.test(text) && !interimWakes.has(i) && getPhase() === "IDLE") {
            interimWakes.add(i);
            wake();
          }
          continue;
        }
        /* Fall back to a lower-ranked hypothesis only when the top one matches no
           catalogue entry. A lower one may not contain the wake word, and depending
           on the 25s window for that would make every rescue fragile. */
        const chosen = lookupBook(text)
          ? text
          : (heard.find((candidate) => lookupBook(candidate)) ?? text);
        const matched = Boolean(lookupBook(chosen));
        record(text, chosen, heard.length, matched);
        const already = interimWakes.has(i);
        interimWakes.delete(i);
        processText(chosen, false, already);
      }
    };
    recognition.onerror = (e) => {
      if (e.error === "aborted") return;
      if (["not-allowed", "service-not-allowed", "audio-capture"].includes(e.error)) {
        wanted = false;
        clearTimeout(restartTimer);
        clearTimeout(silentTimer);
        micStatus(
          e.error === "audio-capture" ? "未找到可用麦克风" : "麦克风或识别服务未获授权",
          "error",
        );
        notice("请检查浏览器站点麦克风权限，使用 localhost / HTTPS 后重试。");
      } else if (e.error === "network") {
        lastNetworkError = true;
        failures++;
        retryDelay = Math.min(12000, 1000 * 2 ** failures);
        micStatus("语音网络中断，等待重连", "error");
        // Report it the first time. Waiting for the fifth failure meant the automatic restarts
        // hid a service that was never reachable behind a healthy-looking status.
        if (failures === 1)
          notice(
            "浏览器识别服务没有响应。语音识别需要把音频发给浏览器厂商的服务，请检查网络后重试，也可以先打开右下角「和 · 对话」使用文字输入。",
          );
        if (failures >= 5) {
          wanted = false;
          micStatus("语音服务不可达，请点击重试", "error");
          notice("浏览器识别服务无法连接。可先打开右下角「和 · 对话」使用文字输入。");
        }
      }
    };
    recognition.onend = () => {
      running = false;
      starting = false;
      if (wanted) {
        if (!lastNetworkError) micStatus(document.hidden ? "页面后台，语音暂停" : "识别重连中");
        scheduleRecognition();
      } else if (!$("micDot").classList.contains("error")) micStatus("语音感知已关闭");
    };
  } else {
    micStatus("浏览器不支持语音识别", "error");
    $("micButton").disabled = true;
    $("transcript").textContent =
      "请改用支持 Web Speech API 的 Chrome / Edge，或打开「和 · 对话」使用文字输入";
  }
  /* Segment recognition returns no interim results, so the wake word arrives at the end of the
     utterance instead of mid-sentence. Nothing downstream can tell which transport produced the
     text, because it dispatches through the same processText. */
  function startServerAsr() {
    micStatus("正在连接语音服务");
    serverAsr.start().then((started) => {
      if (!started) {
        wanted = false;
        micStatus("语音感知已关闭", "off");
      }
    });
  }
  /* A deployment may serve a local recogniser (tools/asr-server.py). Probing must not block the
     wiring above: the Web Speech path is bound synchronously either way, so a plain static
     deployment keeps behaving exactly as it did. */
  probeServerAsr().then((info) => {
    if (info) {
      serverAsr = createServerAsr({
        onText(text) {
          $("transcript").textContent = "听到：" + text;
          record(text, text, 1, Boolean(lookupBook(text)));
          processText(text, false, false);
        },
        onStatus: micStatus,
        onError(message) {
          notice(message);
        },
      });
      // Equally, a browser without Web Speech can still be used here, so undo that branch's lock.
      $("micButton").disabled = false;
      $("transcript").textContent = "服务端识别已就绪";
    }
    // Decided here rather than at load time so the automatic start picks whichever transport
    // actually turned out to be available.
    if (voiceWasEnabled()) armAutoStart();
  });

  /* Voice cannot be started by a document the user has never touched: granting the microphone
     permission itself needs a gesture, and no page can bypass that. So that gesture is spent
     once. The choice is remembered, and every later visit starts listening by itself — measured
     in a browser, once the permission is granted both getUserMedia and an AudioContext work on
     a freshly loaded document with no interaction at all, so afterwards this really is
     click-free. */
  const VOICE_PREFERENCE = "hexu.voice.enabled";
  function voiceWasEnabled() {
    try {
      return localStorage.getItem(VOICE_PREFERENCE) === "1";
    } catch {
      return false; // no storage available (private mode, or the test host)
    }
  }
  function rememberVoice(on) {
    try {
      if (on) localStorage.setItem(VOICE_PREFERENCE, "1");
      else localStorage.removeItem(VOICE_PREFERENCE);
    } catch {
      /* Failing to remember only costs a click on the next visit. */
    }
  }
  function live() {
    return serverAsr ? serverAsr.running : running;
  }
  function startSession() {
    if (!recognition && !serverAsr) return false;
    if (!window.isSecureContext && location.protocol !== "file:") {
      notice("麦克风需要 HTTPS 或 localhost 环境。");
      return false;
    }
    wanted = true;
    failures = 0;
    retryDelay = 450;
    clearTimeout(restartTimer);
    // A fresh session: forget the previous run's errors so the silence watchdog can report
    // again if this attempt also never produces a result.
    lastNetworkError = false;
    resultSeen = false;
    clearTimeout(silentTimer);
    if (serverAsr) startServerAsr();
    else startRecognition();
    return true;
  }
  function stopSession() {
    wanted = false;
    disarmAutoStart();
    if (serverAsr) serverAsr.stop();
    else recognition?.abort();
    clearTimeout(silentTimer);
    micStatus("语音感知已关闭");
  }
  function disarmAutoStart() {
    if (!autoKick) return;
    document.removeEventListener("pointerdown", autoKick);
    document.removeEventListener("keydown", autoKick);
    autoKick = null;
  }
  /* Listen without being asked, because the user already asked once. The attempt below succeeds
     whenever the permission is already granted; if the browser still wants a gesture, the first
     interaction anywhere supplies it. */
  function armAutoStart() {
    micStatus("语音待命：正在恢复收听");
    autoKick = () => {
      disarmAutoStart();
      if (!wanted || !live()) startSession();
    };
    document.addEventListener("pointerdown", autoKick);
    document.addEventListener("keydown", autoKick);
    startSession();
  }

  $("micButton").onclick = () => {
    if (!recognition && !serverAsr) return;
    if (wanted) stopSession();
    else if (startSession()) rememberVoice(true);
  };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearTimeout(restartTimer);
      if (wanted) {
        // Both transports stop listening in a background tab, so speech the page was never
        // asked to hear cannot be transcribed.
        if (serverAsr) serverAsr.stop();
        else recognition?.abort();
        micStatus("页面后台，语音暂停", "off");
      }
    } else if (wanted && serverAsr) startServerAsr();
    else scheduleRecognition();
  });
  window.addEventListener("pagehide", () => {
    wanted = false;
    disarmAutoStart();
    clearTimeout(restartTimer);
    clearTimeout(silentTimer);
    serverAsr?.stop();
    recognition?.abort();
    window.speechSynthesis?.cancel();
  });

  return {
    getState: () => ({ wanted, running, recent }),
    stop() {
      wanted = false;
      disarmAutoStart();
      clearTimeout(restartTimer);
      clearTimeout(silentTimer);
      serverAsr?.stop();
      recognition?.abort();
    },
  };
}
