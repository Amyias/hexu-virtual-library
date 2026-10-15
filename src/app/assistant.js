import { books, anchors, heights } from "../data/catalog.js";
import { understand } from "../voice/understand.js";
import { findBook } from "../voice/intent.js";
import { decide, protocolResponse, NO_MATCH, FOUND, READING_HINT, BUSY_HINT } from "./dialogue.js";
import { IDLE } from "./phases.js";

/* 小和 itself: carries out what dialogue.decide() concluded. Every text input — recognised speech,
   the search box, the suggestion chips, libraryDebug.processText — comes through processText(). */
export function createAssistant({ gsap, $, machine, attention, feedback, journey, view, pulse, home, getLibrary, novelReader, isUnderstandReady }) {
  const { notice, bubble, say } = feedback;
  let wakeTween;
  const lookup = (text) => getLibrary()?.find(text) || findBook(text);

  /** Publish the find / wake protocol and show it in the developer panel. */
  function respond(text, book = null, wakeOnly = false) {
    const response = protocolResponse(text, book, wakeOnly, { anchors, heights, home: home.toArray() });
    $("protocol").textContent = JSON.stringify(response, null, 2);
    window.dispatchEvent(new CustomEvent("xiaohe-response", { detail: response }));
    return response;
  }

  function wake() {
    attention.wake();
    wakeTween?.kill();
    pulse.value = 1;
    wakeTween = gsap.to(pulse, { value: 0, duration: 2.8, ease: "power2.out" });
    bubble("有什么需求吗？", 25000);
    $("voiceTitle").textContent = "我在，请告诉我书名或感兴趣的主题";
  }

  function present(book, speech) {
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
    const result = await understand(request, machine.phase);
    if (!machine.is(IDLE)) return; // the reader moved on while we were waiting
    const book = result.action === "find" && result.bookId ? books.find((entry) => entry.bookId === result.bookId) : null;
    if (book) {
      present(book, result.say || FOUND);
      return;
    }
    if (["return", "open", "close", "chip"].includes(result.action)) {
      notice("现在还没有在阅读的书。");
      return;
    }
    if (getLibrary()) {
      searchFullText(request);
      return;
    }
    if (result.error) notice(result.error);
    noMatch();
  }

  function openFullText() {
    const selected = journey.selected;
    if (selected?.localBookId) novelReader.show();
    else if (selected) {
      notice("这册演示馆藏目前只有简介，正在在线检索正文");
      getLibrary().search(selected.title, false);
    }
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
    if (decision.wake) wake();
    switch (decision.type) {
      case "wake-only":
        return respond("有什么需求吗？", null, true);
      case "reading":
        READING_ACTIONS[decision.command]?.();
        return null;
      case "busy":
        if (decision.tell) notice(BUSY_HINT);
        return null;
      case "full-text":
        searchFullText(decision.query);
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

  return { processText, wake, present, openFullText, lookup };
}
