/* What an utterance asks for, decided without doing any of it.

   Recognised speech and conversation input arrive as text. decide() reads
   one against the current phase and returns a plain description — wake up, read this command,
   walk to this book, ask the model — and assistant.js carries it out. Keeping the decision free
   of the scene, the DOM and the network is what lets the routing rules be tested on their own. */
import { normalize, spokenTitle, wakeRE, wakeStripRE } from "../voice/intent.js";
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
// Discussing a book, recommending reading or creating text is not a request to fetch a book.
const QUESTION_OR_DISCUSSION =
  /什么|为何|为什么|如何|怎么|解释|介绍|分析|评价|讲讲|讲啥|意义|原理|区别|主题|吗$|谁|聊聊|说说|总结|概括|解读|讨论|谈谈|推荐|建议|比较|对比|翻译|润色|创作|帮我写|写一|写个|写篇|写首|写段|读后感/;
const EXPLICIT_FIND = /帮我找|我要找|我想找|找一本|找本|找书|搜索|检索|下载|借/;

export function isBookRequest(text) {
  if (/bug|代码|错误|原因|解决|图片|网页/i.test(text) && !/书|小说|《/.test(text)) return false;
  if (QUESTION_OR_DISCUSSION.test(text) && !EXPLICIT_FIND.test(text)) return false;
  return /(?:帮我|给我|我要|我想|想)?(?:找|搜索|检索|借|下载|读|阅读|取)(?:一下|一本|本|这本|那本|书|《)|(?:帮我找|找本|找书|找一本|我要找|我想找)|哪(?:本|部)书|那本$|这本书$|书在哪里|书在哪|^《[^》]+》$|^HX-\d+$|^S[1-5]-[AB]-L[1-4]-\d+$|书$/.test(
    text,
  );
}

/* Whether a find request names one particular book. "帮我找《三体》", "我想读红楼梦" and even
   "霍金写的那本" do; "你能帮我找书吗", "怎么找书", "帮我找几本科幻小说" and "推荐一本好书" only
   mention finding books. Those are conversation for the model, not a reason to open the reading
   library and search for the sentence itself. Only the ends are trimmed, so a title is never cut
   from the middle. */
const NOT_ONE_BOOK =
  /怎么|怎样|如何|为什么|为何|什么|哪些|哪几|几本|几部|一些|推荐|建议|随便|任意|好看|有趣|有意思|方法|技巧/;
const LEADING =
  /^(?:你能|你可以|能不能|可不可以|能否|可以|帮我|帮忙|给我|替我|我要|我想要|我想|我需要|请|麻烦|找一下|找一找|找到|寻找|找|搜索|检索|下载|借阅|借|阅读|读|看|一下|一本|一部|本|部)+/;
const TRAILING =
  /(?:的正文|的全文|正文|全文|在哪里|在哪儿|在哪|这本书|这本|一下|吗|呢|吧|啊|呀|哦)+$/;
const GENRE_ONLY =
  /^(?:科幻|悬疑|推理|历史|言情|武侠|奇幻|玄幻|恐怖|经典|外国|中国|儿童|英文|中文|哲学|文学|计算机|编程|人工智能|商业|经济|管理|艺术|设计|建筑|科普|心理|传记|诗歌|散文|好|新)*(?:的)?(?:小说|书籍|图书|书|作品|名著|读物|资料)?$/;

export const NAME_A_BOOK = "请告诉我书名或编号，例如「帮我找《狂人日记》」或「HX-03408」。";

export function namesABook(request) {
  if (/《[^》]+》/.test(request)) return true;
  if (/^HX-\d+$|^S[1-5]-[AB]-L[1-4]-/i.test(request)) return true;
  if (NOT_ONE_BOOK.test(request)) return false;
  const rest = request.replace(LEADING, "").replace(TRAILING, "");
  return rest.length >= 2 && !GENRE_ONLY.test(rest);
}

/* 「记住我喜欢科幻」: the one way a fact enters 小和's long-term memory. The reader says it in
   so many words; the model never decides on its own what to remember. */
const REMEMBER =
  /^(?:请|麻烦)?(?:你)?(?:帮我)?(?:记住|记一下|记下来|记着|要记得|别忘了)(?:这件事|一下)?[：:，,、\s]*(.+)$/u;

export function rememberedFact(text) {
  const match = conversationText(text).match(REMEMBER);
  if (!match) return null;
  const fact = match[1].replace(/[。！!？?～~\s]+$/u, "").trim();
  return fact.length >= 2 ? fact.slice(0, 120) : null;
}

export const MAX_CHOICES = 4;
const ORDINAL = { 一: 0, 1: 0, 二: 1, 两: 1, 2: 1, 三: 2, 3: 2, 四: 3, 4: 3 };

/** Which of the offered books the reader means: 「第一本」「第二个」「最后那本」, a title or an
 *  author. null when the answer does not pick one, so it is handled as a new request. */
export function pickChoice(text, choices) {
  // Normalised like the titles it is compared with: lower case turns 「Ⅱ」 into 「ⅱ」 and
  // 「Austen」 into 「austen」, so an answer typed exactly as the title would otherwise miss it.
  const request = normalize(requestOf(text)).replace(/^(?:我要|要|选|就|是)+/, "");
  if (!request) return null;
  if (/^(?:最后|末尾|最后面)(?:一|那)?(?:本|个|部)?/.test(request)) return choices.at(-1) ?? null;
  const ordinal = request.match(/^第?([一两二三四1-4])(?:本|个|部|种|项)?(?:吧|吗|啊)?$/);
  if (ordinal) return choices[ORDINAL[ordinal[1]]] ?? null;
  // 「启航那本」「归途的」: the pointing words around a part of the title are not part of it.
  const named =
    request.replace(/(?:的)?(?:那|这)?(?:一)?(?:本|部|个)?(?:吧|呢|啊)?$/, "") || request;
  const byTitle = choices.filter((book) =>
    [normalize(book.title), spokenTitle(book.title)].some(
      (title) => title && (named.includes(title) || title.includes(named)),
    ),
  );
  if (byTitle.length === 1) return byTitle[0];
  const byAuthor = choices.filter(
    (book) => book.author && request.includes(normalize(book.author)),
  );
  return byAuthor.length === 1 ? byAuthor[0] : null;
}

const CHINESE_ORDINAL = ["一", "二", "三", "四"];
export function choiceSpeech(choices) {
  const list = choices
    .map(
      (book, i) =>
        `第${CHINESE_ORDINAL[i]}本《${book.title}》` +
        (book.author && book.author !== "未知作者" ? `（${book.author}）` : ""),
    )
    .join("，");
  return `我找到了 ${choices.length} 本：${list}。你要哪一本？说「第一本」或书名就好。`;
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
  // Remembering works in any phase: it only stores a line, and moves nothing.
  const fact = rememberedFact(text);
  if (fact) return { type: "remember", wake, fact };
  const question = QUESTION_OR_DISCUSSION.test(request) || /[？?]\s*$/.test(text);
  const webRequest =
    /联网|上网|网页|https?:\/\//i.test(text) ||
    (!/《[^》]+》/.test(text) &&
      /(?:搜索|查一下|搜一下|查询).*(?:新闻|天气|消息|汇率|股价|最新|实时)/.test(text));
  const bookRequest = !webRequest && isBookRequest(request);
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
  const found = !webRequest && (!question || bookRequest) ? lookup(request) : null;
  // Several books fit equally well: ask which one rather than quietly take the first.
  if (Array.isArray(found) && found.length > 1)
    return { type: "choose", wake, books: found.slice(0, MAX_CHOICES) };
  const book = Array.isArray(found) ? found[0] : found;
  if (book) return { type: "present", wake, book, speech: addressed ? FOUND : LOCATING };
  if (bookRequest || /^HX-\d+$/i.test(request)) {
    // Talking about finding books is conversation; only a named book is searched for.
    if (!namesABook(request))
      return understand
        ? { type: "chat", wake, request: conversationText(text) }
        : { type: "reply", wake, speech: NAME_A_BOOK };
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
