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
  [
    "return",
    /^(?:请|帮我|把这本书|把书|将书)*(?:放回(?:书架|去)?|归还(?:书籍|图书)?|还书|收回|拿走)(?:吧|一下)?$/,
  ],
  ["next", /^(?:请|帮我|翻到)*(?:下一页|往后翻|向后翻)(?:吧|一下)?$/],
  ["previous", /^(?:请|帮我|翻到)*(?:上一页|往前翻|向前翻)(?:吧|一下)?$/],
  [
    "fullText",
    /^(?:请|帮我|我要|我想)*(?:读正文|看正文|正文|读小说|继续阅读|阅读正文|打开正文)(?:吧|一下)?$/,
  ],
  ["close", /^(?:请|帮我|把书)*(?:合上|关上|闭合|盖上)(?:书|书本|封面)?(?:吧|一下)?$/],
  ["open", /^(?:请|帮我|把书)*(?:翻开|打开|摊开|掀开)(?:书|书本|封面)?(?:吧|一下)?$/],
  ["chip", /^(?:请|帮我)*(?:看看|看|查看|检查)?(?:芯片|标签|身份证)(?:吧|一下)?$/],
];

/** The request with the wake word, greetings and punctuation taken out. */
export function requestOf(text) {
  return text
    .replace(wakeStripRE, "")
    .replace(GREETINGS, "")
    .replace(/[\s，。！？、,.!?]/g, "");
}

/** Preserve normal punctuation/spaces for the model; requestOf is only a shelf matcher. */
export function conversationText(text) {
  return text
    .replace(wakeRE, "")
    .replace(/^[\s，。！？、,.!?：:]+/u, "")
    .trim();
}
export function isBookRequest(text) {
  if (/bug|代码|错误|原因|解决|图片|网页/i.test(text) && !/书|小说|《/.test(text)) return false;
  if (
    /什么|为何|为什么|如何|怎么|解释|介绍|意义|原理/.test(text) &&
    !/帮我找|我要找|我想找|找一本|找本|搜索|检索|下载|借/.test(text)
  )
    return false;
  return /(?:帮我|给我|我要|我想|想)?(?:找|搜索|检索|借|下载|读|阅读|取)(?:一下|一本|本|这本|那本|书|《)|(?:帮我找|找本|找书|找一本|我要找|我想找)|哪(?:本|部)书|那本$|这本书$|书在哪里|书在哪|^《[^》]+》$|^HX-\d+$|^S[1-5]-[AB]-L[1-4]-\d+$|书$/.test(
    text,
  );
}

export function readingCommand(request) {
  if (/为什么|如何|怎么|是什么|解释|介绍|分析|意义|区别|吗|能不能/.test(request)) return null;
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
  const wake = addressed && !wasInterimWake;
  const question =
    /什么|为何|为什么|如何|怎么|解释|介绍|分析|评价|讲讲|讲啥|意义|原理|区别|主题|吗$|谁|聊聊|说说/.test(
      request,
    ) || /[？?]\s*$/.test(text);
  const bookRequest = isBookRequest(request);
  if (phase === READING) {
    const command = readingCommand(request);
    if (command) return { type: "reading", command };
    if (bookRequest) return { type: "reading", command: addressed || direct ? "hint" : null };
    return { type: "chat", wake, request: conversationText(text) };
  }
  if (phase !== IDLE) return { type: "busy", tell: addressed || direct };
  // Offline courtesy still works, but configured models answer naturally instead of canned text.
  const reply = !understand && PET_REPLIES.find(([pattern]) => pattern.test(request));
  if (reply) return { type: "reply", wake, speech: reply[1] };
  const book = !question || bookRequest ? lookup(request) : null;
  if (book) return { type: "present", wake, book, speech: addressed ? FOUND : LOCATING };
  if (bookRequest || /^HX-\d+$/i.test(request)) {
    if (understand) return { type: "model", wake, request: conversationText(text) };
    if (fullText) return { type: "full-text", wake, query: text };
    return { type: "no-match", wake };
  }
  return { type: "chat", wake, request: conversationText(text) };
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
