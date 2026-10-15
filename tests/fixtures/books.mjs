import { books } from "../../src/data/catalog.js";
const fixtures = [
  ["三体", 9880, ["科幻"]],
  ["计算机基础", 214, ["编程"]],
  ["人工智能：一种现代的方法", 792, ["人工智能", "AI"]],
  ["时间简史", 2202, []],
  ["人类简史", 2780, []],
];
export const readingBooks = fixtures.map(([title, index, aliases]) => ({
  ...books[index],
  title,
  author: "测试作者",
  synopsis: "仅供自动化测试的本地书籍。",
  localBookId: `test-${index}`,
  keys: [...books[index].keys, ...aliases],
}));
readingBooks.push({ ...books.at(-1), title: "尾部槽位测试", localBookId: "test-last" });
