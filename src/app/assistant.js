import { books, anchors, heights } from "../data/catalog.js";
import { understand } from "../voice/understand.js";
import { wakeRE } from "../voice/intent.js";
import { lookupBooks } from "../reader/library.js";
import {
  decide,
  protocolResponse,
  pickChoice,
  choiceSpeech,
  NO_MATCH,
  FOUND,
  READING_HINT,
  BUSY_HINT,
} from "./dialogue.js";
import { createChatSession } from "../voice/chat.js";
import { voice } from "../voice/voice.js";

// A conversation is summarised into long-term memory once it has been quiet this long, when it
// is cleared, or when the page goes away. Only the turns since the previous summary are sent.
const SUMMARY_IDLE_MS = 3 * 60 * 1000;
const postJson = (url, body) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
import { IDLE, READING } from "./phases.js";

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
  readingMusic,
  actions = {},
}) {
  const { notice, say } = feedback;
  let wakeTween;
  const chat = createChatSession();
  let intentGeneration = 0;
  /* One book, or several equally good ones for the reader to choose from. */
  const lookup = (text) => lookupBooks(text, getLibrary()?.findAll?.(text) ?? []);
  let choice = null; // { books, until } while 小和 waits for 「第一本」 or a title
  function offerChoice(offered) {
    // Title order, so 《星海Ⅰ》 is offered before 《星海Ⅱ》 whatever shelf each stands on.
    const books = [...offered].sort((a, b) => a.title.localeCompare(b.title, "zh"));
    attention.wake(30000);
    choice = { books, until: Date.now() + 30000 };
    const speech = choiceSpeech(books);
    respond(speech);
    say(speech, 0, { interactive: true });
  }

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

  let summaryTimer = null,
    summarized = 0;
  function summarize({ leaving = false } = {}) {
    clearTimeout(summaryTimer);
    const { total, turns } = chat.getState();
    const fresh = Math.min(total - summarized, turns);
    if (fresh < 1) return;
    summarized = total;
    const body = JSON.stringify({ history: chat.recent(fresh) });
    if (leaving && navigator.sendBeacon)
      navigator.sendBeacon("/memory/summarize", new Blob([body], { type: "application/json" }));
    else
      fetch("/memory/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      }).catch(() => {});
  }
  window.addEventListener("pagehide", () => summarize({ leaving: true }));

  /** Library actions requested in conversation, each checked again before it runs. */
  function perform(name, args) {
    if (name === "set_sky" && ["day", "night", "auto"].includes(args?.mode))
      actions.setSky?.(args.mode);
    else if (name === "reading_music" && machine.is(READING))
      args?.action === "pause" ? readingMusic?.pause() : readingMusic?.play();
    else if (name === "open_chapter" && machine.is(READING) && Number.isInteger(args?.chapter))
      novelReader.goTo(args.chapter - 1);
  }

  async function remember(fact) {
    attention.wake();
    let speech = "这件事我没能记下来，请稍后再试。";
    try {
      const response = await postJson("/memory/fact", { text: fact });
      if (response.ok) speech = `好，我记住了：${fact}。`;
      else if (response.status === 409)
        speech = "我的记忆现在是关闭的，可以在本机设置的「小和记得的事」里打开。";
    } catch {}
    respond(speech);
    say(speech);
  }

  function present(book, speech) {
    cancelPending();
    attention.clear();
    if (book.localBookId) postJson("/memory/reading", { bookId: book.localBookId }).catch(() => {});
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
    voice.cancel();
  }
  function clearConversation() {
    summarize();
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
    say("正在回应…", 0, { interactive: true, onCancel: cancelPending, silent: true });
    // The first words replace the waiting bubble; later ones extend it and are spoken as each
    // sentence completes, so the reader hears 小和 start answering within a second or so.
    let live = null,
      fetchRequest = null;
    const result = await chat.ask(request, machine.phase, journey.selected?.bookId, {
      onText(text) {
        if (live) live.update(text);
        else live = feedback.stream(text, { onCancel: cancelPending });
      },
      // The model asked for a library action; the server has validated it already. Fetching a
      // book waits for the reply to be said, so 小和 does not fly off mid-sentence.
      onAction({ name, args }) {
        if (name === "fetch_book") fetchRequest = args;
        else perform(name, args);
      },
    });
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
    const spoken = live
      ? live.finish(result.reply, { sources: result.sources })
      : (say(result.reply, 0, { interactive: true, sources: result.sources }), Promise.resolve());
    if (fetchRequest) {
      const book = books.find((entry) => entry.localBookId && entry.bookId === fetchRequest.bookId);
      const asked = intentGeneration;
      await Promise.race([spoken, new Promise((resolve) => setTimeout(resolve, 8000))]);
      if (book && asked === intentGeneration && machine.is(IDLE)) present(book, FOUND);
    }
    clearTimeout(summaryTimer);
    summaryTimer = setTimeout(summarize, SUMMARY_IDLE_MS);
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
    if (
      choice &&
      Date.now() < choice.until &&
      (direct || attention.active() || wakeRE.test(text))
    ) {
      const picked = pickChoice(text, choice.books);
      choice = null;
      if (picked) return present(picked, FOUND);
    }
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
      case "choose":
        offerChoice(decision.books);
        return null;
      case "remember":
        remember(decision.fact);
        return null;
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
