import { books, anchors, heights } from "../data/catalog.js";
import { understand } from "../voice/understand.js";
import { findBook } from "../voice/intent.js";
import { decide, protocolResponse, NO_MATCH, FOUND, READING_HINT, BUSY_HINT } from "./dialogue.js";
import { createChatSession } from "../voice/chat.js";
import { IDLE } from "./phases.js";

/* 小和 itself: carries out what dialogue.decide() concluded. Every text input — recognised speech,
   the conversation panel, libraryDebug.processText — comes through processText(). */
export function createAssistant({
  gsap,
  $,
  machine,
  attention,
  feedback,
  journey,
  view,
  pulse,
  home,
  getLibrary,
  novelReader,
  isUnderstandReady,
  conversation,
}) {
  const { notice, say } = feedback;
  let wakeTween;
  const chat = createChatSession();
  let intentGeneration = 0;
  const lookup = (text) => getLibrary()?.find(text) || findBook(text);

  /** Publish the find / wake protocol for integrations. */
  function respond(text, book = null, wakeOnly = false) {
    const response = protocolResponse(text, book, wakeOnly, {
      anchors,
      heights,
      home: home.toArray(),
    });
    window.dispatchEvent(new CustomEvent("xiaohe-response", { detail: response }));
    return response;
  }

  function wake() {
    attention.wake();
    wakeTween?.kill();
    pulse.value = 1;
    wakeTween = gsap.to(pulse, { value: 0, duration: 2.8, ease: "power2.out" });
    say("有什么需求吗？", 25000);
    $("voiceTitle").textContent = "我在，请告诉我书名或感兴趣的主题";
  }

  function present(book, speech) {
    cancelPending();
    attention.clear();
    const response = respond(speech, book);
    say(speech);
    journey.fetchBook(book, response.target);
    return response;
  }

  function noMatch() {
    attention.wake();
    respond(NO_MATCH);
    say(NO_MATCH);
  }

  function searchFullText(query) {
    attention.wake();
    const speech = "好的，正在为您检索可下载的正文。";
    respond(speech);
    say(speech);
    getLibrary().search(query, true);
  }

  /* The rules place most requests instantly and for free. What they cannot read — "霍金写的那
     本", "讲宇宙起源最著名的那本书" — goes to the configured model instead, and if that cannot
     answer either the reply is exactly what it always was. */
  async function findViaModel(request) {
    $("voiceTitle").textContent = "小和正在理解你的意思…";
    const generation = ++intentGeneration;
    const result = await understand(request, machine.phase);
    if (generation !== intentGeneration || !machine.is(IDLE)) return; // the reader moved on while we were waiting
    const book =
      result.action === "find" && result.bookId
        ? books.find((entry) => entry.localBookId && entry.bookId === result.bookId)
        : null;
    if (book) {
      present(book, result.say || FOUND);
      return;
    }
    if (["return", "open", "close", "chip"].includes(result.action)) {
      notice("现在还没有在阅读的书。");
      return;
    }
    if (result.error) {
      notice(result.error);
      say("找书理解服务暂时不可用，请在正文书库按书名检索。");
      return;
    }
    if (getLibrary()) {
      searchFullText(request);
      return;
    }
    noMatch();
  }

  function cancelPending() {
    intentGeneration++;
    chat.cancel();
    conversation?.busy(false);
    feedback.hideBubble();
    window.speechSynthesis?.cancel();
  }
  function clearConversation() {
    cancelPending();
    chat.clear();
  }
  async function converse(request) {
    if (chat.getState().busy) {
      notice("小和正在回答，请等待或点击气泡中的停止等待。");
      return;
    }
    intentGeneration++;
    attention.wake(120000);
    conversation.begin(request);
    say("正在回应…", 0, { interactive: true, onCancel: cancelPending });
    const result = await chat.ask(request, machine.phase, journey.selected?.bookId);
    if (result.cancelled) return;
    attention.wake(40000);
    if (result.error) {
      conversation.error(result.error);
      respond(result.error);
      say(result.error, 0, { interactive: true });
      $("voiceTitle").textContent = "对话服务尚未就绪，可打开模型设置检查";
      return;
    }
    conversation.answer(result.reply, result.model, result.truncated, result.sources);
    respond(result.reply);
    say(result.reply, 0, { interactive: true, sources: result.sources });
    $("voiceTitle").textContent = "小和已回答，可以继续追问";
  }

  function openFullText() {
    const selected = journey.selected;
    if (selected?.localBookId) novelReader.show();
  }

  const READING_ACTIONS = {
    return: () => journey.returnBook(),
    next: () => {
      novelReader.show();
      novelReader.next();
    },
    previous: () => {
      novelReader.show();
      novelReader.previous();
    },
    fullText: openFullText,
    close: () => (view.inspecting ? view.closeChip() : view.animateTurn(0)),
    open: () => view.animateTurn(1),
    chip: () => view.openChip(journey.selected),
    hint: () => notice(READING_HINT),
  };

  function processText(text, direct = false, wasInterimWake = false) {
    const decision = decide(text, {
      phase: machine.phase,
      direct,
      wasInterimWake,
      awake: attention.active(),
      lookup,
      fullText: Boolean(getLibrary()),
      understand: isUnderstandReady(),
    });
    if (
      ["reading", "present", "model", "full-text"].includes(decision.type) ||
      (decision.type === "wake-only" && chat.getState().busy)
    )
      cancelPending();
    if (decision.wake && !chat.getState().busy) wake();
    switch (decision.type) {
      case "wake-only":
        return respond("有什么需求吗？", null, true);
      case "reply":
        attention.wake();
        respond(decision.speech);
        say(decision.speech);
        return null;
      case "reading":
        READING_ACTIONS[decision.command]?.();
        return null;
      case "busy":
        if (decision.tell) notice(BUSY_HINT);
        return null;
      case "full-text":
        searchFullText(decision.query);
        return null;
      case "chat":
        converse(decision.request);
        return null;
      case "model":
        findViaModel(decision.request);
        return null;
      case "no-match":
        noMatch();
        return null;
      case "present":
        return present(decision.book, decision.speech);
      default:
        return null;
    }
  }

  return {
    processText,
    wake,
    present,
    openFullText,
    lookup,
    cancelPending,
    clearConversation,
    getChatState: chat.getState,
  };
}
