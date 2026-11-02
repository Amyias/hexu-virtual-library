import { books, anchors, heights } from "../data/catalog.js";
import { understand } from "../voice/understand.js";
import { wakeRE } from "../voice/intent.js";
import { lookupBooks } from "../reader/library.js";
import {
  decide,
  requestOf,
  asksAboutPage,
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
import { IDLE, NAVIGATING, PRESENTING, READING } from "./phases.js";

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
    // Asked together with fetching a book: done once the book is in the reader's hands.
    if (args?.after === "arrival" && ["reading_music", "open_chapter"].includes(name)) {
      afterArrival.push({ name, args: { ...args, after: undefined } });
      return;
    }
    if (name === "set_sky" && ["day", "night", "auto"].includes(args?.mode))
      actions.setSky?.(args.mode);
    else if (name === "reading_music" && machine.is(READING))
      args?.action === "pause" ? readingMusic?.pause() : readingMusic?.play();
    else if (name === "open_chapter" && machine.is(READING) && Number.isInteger(args?.chapter))
      return novelReader.goTo(args.chapter - 1);
    else if (name === "open_bookmark" && machine.is(READING) && Number.isInteger(args?.chapter))
      return novelReader.goTo(args.chapter - 1, args.offset);
    else if (name === "set_font_size" && machine.is(READING)) novelReader.fontSize?.(args?.size);
    else if (name === "locate_book" && machine.is(IDLE)) {
      const book = books.find((entry) => entry.localBookId && entry.bookId === args?.bookId);
      if (book) actions.locate?.(book);
    } else if (name === "download_book" && args?.candidate?.title) offerDownload(args.candidate);
    return true;
  }

  /* Steps asked for with a fetch (「取《三体》翻到第三章」) wait while the book is on its way, and
     run once it is open in the reader's hands. They get SETTLE_MS there (the text may still be
     loading); if they cannot run then, or the fetch ends without the book arriving, the reader
     is told rather than left waiting. */
  const SETTLE_MS = 10000;
  let afterArrival = [];
  function runAfterArrival() {
    if (!afterArrival.length) return;
    const steps = afterArrival;
    afterArrival = [];
    let until = null;
    const attempt = () => {
      if (machine.is(NAVIGATING, PRESENTING)) return setTimeout(attempt, 500); // still on its way
      if (!machine.is(READING)) return notice("书没有取到，刚才翻章或音乐的要求没有执行。");
      until ??= Date.now() + SETTLE_MS;
      const left = steps.filter((step) => !perform(step.name, step.args));
      steps.splice(0, steps.length, ...left);
      if (!steps.length) return;
      if (Date.now() < until) setTimeout(attempt, 500);
      else notice("书到手后没能接着完成刚才的要求，请再说一次。");
    };
    attempt();
  }

  /* The reader went back a page and stayed (novel.js onLinger): offer once, quietly, to
     explain. Not spoken, and off when the reader turned it off in the settings. */
  function offerHelp() {
    let off = false;
    try {
      off = localStorage.getItem("hexu-reading-help") === "off";
    } catch {}
    if (off || !machine.is(READING) || chat.getState().busy) return;
    attention.wake(30000);
    say("这一段要我帮你解释一下吗？说「解释一下」就好。", 0, { interactive: true, silent: true });
  }

  /* Downloading is never done on the model's word alone: 小和 asks, and only a 「要」 within
     DOWNLOAD_WAIT_MS starts it. Anything else is handled as a new request. */
  const DOWNLOAD_WAIT_MS = 30000;
  let pendingDownload = null; // { candidate, until }
  const YES = /^(?:要|好|好的|可以|行|下载|下载吧|要的|是的|确定|嗯|对)(?:吧|呀|啊|的)?$/;
  const NO = /^(?:不|不要|不用|算了|取消|不下载|不用了)(?:吧|了|啦)?$/;
  function offerDownload(candidate) {
    pendingDownload = { candidate, until: Date.now() + DOWNLOAD_WAIT_MS };
    attention.wake(DOWNLOAD_WAIT_MS);
    notice(`说「要」开始下载《${candidate.title}》，说「不用」取消（30 秒内有效）。`);
  }
  function answerDownload(text) {
    const offer = pendingDownload;
    pendingDownload = null;
    const answer = requestOf(text);
    if (YES.test(answer)) {
      const speech = `好的，开始下载《${offer.candidate.title}》，下载好就放上书架。`;
      respond(speech);
      say(speech);
      getLibrary()?.download?.(offer.candidate);
      return true;
    }
    if (NO.test(answer)) {
      respond("好的，不下载了。");
      say("好的，不下载了。");
      return true;
    }
    return false;
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
    // 「这段什么意思」 while reading: the page in front of the reader goes with the question.
    const page =
      machine.is(READING) && asksAboutPage(request) ? novelReader.pageText?.().slice(0, 800) : "";
    const result = await chat.ask(request, machine.phase, journey.selected?.bookId, {
      page,
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
      if (book && asked === intentGeneration && machine.is(IDLE)) {
        present(book, FOUND);
        runAfterArrival();
      } else afterArrival = [];
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
      pendingDownload &&
      Date.now() < pendingDownload.until &&
      (direct || attention.active() || wakeRE.test(text)) &&
      answerDownload(text)
    )
      return null;
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
    offerHelp,
    getChatState: chat.getState,
  };
}
