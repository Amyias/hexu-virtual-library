import { books } from "../data/catalog.js";
export const normalize = (s) => s.toLowerCase().replace(/[\s，。！？、,.!?《》“”"：:]/g, "");
/* 唤醒词别名。供 test() 使用，不能带 g 标志——带 g 的正则会被 lastIndex 状态污染。 */
export const wakeRE = /小和|小何|肖和|小荷|小河|晓和|小禾|小鹤|xiao\s*he/i;
/* 供 replace() 使用：一句话里唤醒词可能出现多次，不带 g 只会删掉第一处。 */
export const wakeStripRE = new RegExp(wakeRE.source, "gi");

/* 近似匹配的长度下限。单字查询太短，放宽后几乎会撞上任何书，因此不做近似。 */
const MIN_FUZZY = 2;
/* 允许的最大编辑距离。中文识别错误绝大多数是单字同音替换，距离为 1。 */
const MAX_EDITS = 1;
/* 只有 3 字及以上的书名/别名才做近似匹配。编辑距离分不出同音与不同音：
   「题」「体」同音而「国」「体」不同音，距离却都是 1。放开二字书名会让
   「身体」「团体」「三国」「沙发」这类常用词全部误命中（实测 12 个常见
   二字词命中 8 个）。二字书名的错字改由识别器的候选列表救回——同音词通常
   就在候选里，这比放宽距离更准。 */
const MIN_NEAR_CANDIDATE = 3;

/* 是否有编辑距离不超过 limit 的可能。逐行计算并在整行最小值超限时提前退出，
   避免为每条无关候选都算完整矩阵。 */
function withinEdits(a, b, limit) {
  if (Math.abs(a.length - b.length) > limit) return false;
  let previous = Array.from({ length: a.length + 1 }, (_, j) => j);
  for (let i = 1; i <= b.length; i++) {
    const row = [i];
    let best = i;
    for (let j = 1; j <= a.length; j++) {
      const substitute = previous[j - 1] + (a[j - 1] === b[i - 1] ? 0 : 1);
      row[j] = Math.min(previous[j] + 1, row[j - 1] + 1, substitute);
      if (row[j] < best) best = row[j];
    }
    if (best > limit) return false;
    previous = row;
  }
  return previous[a.length] <= limit;
}

/* 匹配级别。3 查询含完整书名或别名；2 查询是书名或别名的一段；1 只差一个字。
   2 与 1 都设了长度门槛，否则「书」「一」这类单字会大面积误命中。 */
const EXACT = 3,
  FRAGMENT = 2,
  NEAR = 1;

function tierOf(query, candidate) {
  if (!candidate) return 0;
  if (query.includes(candidate)) return EXACT;
  if (query.length >= MIN_FUZZY && candidate.includes(query)) return FRAGMENT;
  if (
    query.length >= MIN_FUZZY &&
    candidate.length >= MIN_NEAR_CANDIDATE &&
    withinEdits(query, candidate, MAX_EDITS)
  )
    return NEAR;
  return 0;
}

/* 书名的念法：《星海Ⅱ·归途》念出来是「星海归途」，罗马数字与间隔号都不出声。与书名相同、
   或去掉后不足三字时不另建，免得「Ⅱ」这类书名只剩一两个字而撞上别的书。 */
const UNSPOKEN = /[ⅰ-ⅿ·・:：\-—_()（）[\]【】]/g;
export function spokenTitle(title) {
  const written = normalize(title || "");
  const spoken = written.replace(UNSPOKEN, "");
  return spoken !== written && spoken.length >= 3 ? spoken : "";
}

/* 编号与位置码的念法：数字念成中文或英文都换回阿拉伯数字，只留字母和数字。
   「HX 零三四零八」「S two A L4 P二八四」→「hx03408」「s2al4p284」。 */
const SPOKEN_DIGITS = {
  零: 0,
  〇: 0,
  幺: 1,
  一: 1,
  二: 2,
  两: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  zero: 0,
  one: 1,
  two: 2,
  three: 3,
  four: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  nine: 9,
};
export function codeForm(text) {
  return String(text || "")
    .toLowerCase()
    .replace(
      /zero|one|two|three|four|five|six|seven|eight|nine|[零〇幺一二两三四五六七八九]/g,
      (word) => String(SPOKEN_DIGITS[word]),
    )
    .replace(/[^a-z0-9]/g, "");
}

/* 返回命中的书、级别与命中的那个词。级别相同时先到者胜，即目录顺序。 */
export function matchBook(text, collection = books) {
  return matchBooks(text, collection)[0] ?? null;
}

/* 所有并列最高分的书（同一本只算一次），按目录顺序。两本以上时调用方应先请读者选择，
   而不是悄悄取第一本：同名的两个版本、只说了「三体」而书架上有《三体Ⅱ》《三体Ⅲ》都会这样。 */
export function matchBooks(text, collection = books) {
  // Titles and aliases change when real books are bound after startup. Never index empty slots.
  const INDEX = collection
    .filter((book) => book.localBookId)
    .flatMap((book) => {
      const spoken = spokenTitle(book.title);
      return [
        { book, text: normalize(book.title), isTitle: true },
        ...(spoken ? [{ book, text: spoken, isTitle: true }] : []),
        ...[...book.keys, ...(book.localAliases || [])].map((key) => ({
          book,
          text: normalize(key),
          isTitle: false,
        })),
        // Numbers and position codes as they come out of speech: 「S2 A L4 P284」 has no hyphens.
        ...book.keys.map((key) => ({ book, text: codeForm(key), isTitle: false, code: true })),
      ];
    });
  const query = normalize(text);
  const code = codeForm(text);
  let best = [];
  let bestRank = 0;
  for (const { book, text: candidate, isTitle, code: isCode } of INDEX) {
    // A code matches whole or not at all: one digit off is the shelf next door, not a near miss.
    const tier = isCode
      ? candidate && code.includes(candidate)
        ? EXACT
        : 0
      : tierOf(query, candidate);
    if (!tier) continue;
    const rank = tier * 2 + (isTitle ? 1 : 0);
    const match = { book, tier, via: (isTitle ? "书名：" : "别名：") + candidate };
    if (rank > bestRank) {
      bestRank = rank;
      best = [match];
    } else if (rank === bestRank && !best.some((item) => item.book === book)) best.push(match);
  }
  return best;
}

export function findBook(text, collection = books) {
  return matchBook(text, collection)?.book;
}

export function findBooks(text, collection = books) {
  return matchBooks(text, collection).map((match) => match.book);
}
