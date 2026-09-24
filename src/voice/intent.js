import { books } from "../data/catalog.js";
export const normalize = (s) =>
  s.toLowerCase().replace(/[\s，。！？、,.!?《》“”"：:]/g, "");
export const wakeRE = /小和|小何|肖和|小荷|小河|晓和|xiao\s*he/i;
export function findBook(text) {
  const q = normalize(text);
  return (
    books.find((b) => q.includes(normalize(b.title))) ||
    books.find((b) => b.keys.some((k) => q.includes(normalize(k))))
  );
}
