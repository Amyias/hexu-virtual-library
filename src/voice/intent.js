import { books } from "../data/catalog.js";
export const normalize = (s) =>
  s.toLowerCase().replace(/[\s，。！？、,.!?《》“”"：:]/g, "");
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

/* 馆藏摊平成候选表。归一化是纯函数，一次算好，免得每次查询重复上千次正则替换。
   每条记下所属书与是否书名——书名与别名同级时书名优先。 */
const INDEX = books.flatMap((book) => [
  { book, text: normalize(book.title), isTitle: true },
  ...book.keys.map((key) => ({ book, text: normalize(key), isTitle: false })),
]);

/* 返回命中的书、级别与命中的那个词。级别相同时先到者胜，即目录顺序。 */
export function matchBook(text) {
  const query = normalize(text);
  let best = null;
  let bestRank = 0;
  for (const { book, text: candidate, isTitle } of INDEX) {
    const tier = tierOf(query, candidate);
    if (!tier) continue;
    const rank = tier * 2 + (isTitle ? 1 : 0);
    if (rank > bestRank) {
      bestRank = rank;
      best = { book, tier, via: (isTitle ? "书名：" : "别名：") + candidate };
    }
  }
  return best;
}

export function findBook(text) {
  return matchBook(text)?.book;
}
