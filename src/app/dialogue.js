/* What an utterance asks for, decided without doing any of it.

   Recognised speech, the search box all arrive as text. decide() reads
   one against the current phase and returns a plain description — wake up, read this command,
   walk to this book, ask the model — and assistant.js carries it out. Keeping the decision free
   of the scene, the DOM and the network is what lets the routing rules be tested on their own. */
import { wakeRE, wakeStripRE } from "../voice/intent.js";
import { IDLE, READING } from "./phases.js";

/** How long 「小和」 keeps listening for a request without the wake word. */
export const AWAKE_MS = 25000;
export const NO_MATCH = "暂未匹配到已入库书籍。请打开正文书库，搜索下载或导入 TXT / EPUB。";
export const FOUND = "好的，为您找到相关书籍，请随我来。";
export const LOCATING = "好的，正在为您定位…";
export const READING_HINT = "正在陪你阅读，可以说下一页、上一页、读正文、看芯片或放回书架。";
export const BUSY_HINT = "小和正在取书，请稍候。";

const PET_REPLIES = [
  [/^(?:你是谁|你叫什么|介绍一下自己)$/, "我是小和，你的图书馆小伙伴。想读什么书，告诉我吧！"],
  [/^(?:谢谢|谢谢你|多谢|辛苦了)$/, "不客气！能陪你读书，我很开心。"],
  [/^(?:你会什么|你能做什么|有什么功能)$/, "我会找书、带你取书，也能陪你翻页阅读。说出书名就好！"],
  [/^(?:再见|拜拜|晚安)$/, "下次见！我会在书架旁等你。"],
];
const GREETINGS = /你好|您好|在吗|你在吗|嗨|嘿|哈喽|hello/gi;

/* Reading commands are few and regular, so they are answered at once; going to the model for them
   would add a second of latency for nothing. Order matters where phrases overlap. 「合上」 closes
   the cover (or the chip close-up) — it used to return the book, which is not what it says. */
const READING_COMMANDS = [
  ["return", /放回|归还|还书|收回|拿走/],
  ["next", /下一页|往后翻|向后翻/],
  ["previous", /上一页|往前翻|向前翻/],
  ["fullText", /正文|读小说|继续阅读/],
  ["close", /合上|关上|闭合|盖上/],
  ["open", /翻开|打开|摊开|掀开/],
  ["chip", /芯片|标签|身份证/],
];

/** The request with the wake word, greetings and punctuation taken out. */
export function requestOf(text) {
  return text
    .replace(wakeStripRE, "")
    .replace(GREETINGS, "")
    .replace(/[\s，。！？、,.!?]/g, "");
}

export function readingCommand(request) {
  return READING_COMMANDS.find(([, pattern]) => pattern.test(request))?.[0] ?? null;
}

/** Decide what one utterance asks for.
 *
 *  direct: typed or clicked, so no wake word is needed. wasInterimWake: the wake word was already
 *  answered from an interim result, so it must not be answered twice. awake: inside the window
 *  after 「小和」. lookup(request): the book a request names, if any. fullText / understand: whether
 *  the reading library and the semantic model are available.
 *
 *  `wake` on the result means: answer the wake word before doing the rest. */
export function decide(
  text,
  {
    phase,
    direct = false,
    wasInterimWake = false,
    awake = false,
    lookup,
    fullText = false,
    understand = false,
  },
) {
  const addressed = wakeRE.test(text);
  if (!direct && !addressed && !awake) return { type: "ignore" };
  const request = requestOf(text);
  if (!request) return { type: "wake-only", wake: !wasInterimWake };
  if (phase === READING) {
    const command = readingCommand(request);
    if (command) return { type: "reading", command };
    return { type: "reading", command: addressed || direct ? "hint" : null };
  }
  if (phase !== IDLE) return { type: "busy", tell: addressed || direct };

  const wake = addressed && !wasInterimWake;
  const reply = PET_REPLIES.find(([pattern]) => pattern.test(request));
  if (reply) return { type: "reply", wake, speech: reply[1] };
  const book = lookup(request);
  if (!book) {
    if (understand) return { type: "model", wake, request };
    if (fullText) return { type: "full-text", wake, query: text };
    return { type: "no-match", wake };
  }
  return { type: "present", wake, book, speech: addressed ? FOUND : LOCATING };
}

/** The window after 「小和」 in which a request needs no wake word. */
export function createAttention(now = Date.now) {
  let until = 0;
  return {
    wake(ms = AWAKE_MS) {
      until = now() + ms;
    },
    clear() {
      until = 0;
    },
    active: () => now() < until,
    /** True exactly once, when an open window runs out. */
    lapsed() {
      if (!until || now() <= until) return false;
      until = 0;
      return true;
    },
  };
}

/** The find / wake protocol published as the `xiaohe-response` event. In IDLE the target is a
 *  placeholder with no movement behind it; a consumer must check `action` first. */
export function protocolResponse(text, book, wakeOnly, { anchors, heights, home }) {
  return {
    speech: text,
    is_wake_only: wakeOnly,
    action: book ? "NAVIGATE_TO_BOOK" : "IDLE",
    target: book
      ? {
          shelf_id: "Shelf_" + book.shelf,
          shelf_side: book.side,
          layer: book.layer,
          world_position: [anchors[book.shelf - 1], heights[book.layer - 1], 0],
        }
      : { shelf_id: "Shelf_1", shelf_side: "A", layer: 1, world_position: [...home] },
    book_data: book
      ? { title: book.title, author: book.author, category: book.category, synopsis: book.synopsis }
      : { title: "", author: "", category: "", synopsis: "" },
  };
}
