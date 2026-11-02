import test from "node:test";
import assert from "node:assert/strict";
import { bookQuery } from "../src/reader/library.js";

test("spoken book requests strip commands while preserving titles and English spacing", () => {
  assert.equal(bookQuery("小和，我要找《狂人日记》"), "狂人日记");
  assert.equal(bookQuery("小荷，帮我下载红楼梦的正文"), "红楼梦");
  assert.equal(bookQuery("请找尚书"), "尚书");
  assert.equal(bookQuery("帮我找 Pride and Prejudice"), "Pride and Prejudice");
});

test("titles are also matched as they are said, and codes as speech writes them", async () => {
  const { spokenTitle, codeForm, findBooks } = await import("../src/voice/intent.js");
  assert.equal(spokenTitle("星海Ⅱ·归途"), "星海归途");
  assert.equal(spokenTitle("三体"), "", "nothing unsaid, no second entry");
  assert.equal(spokenTitle("Ⅱ·下"), "", "too short once the numeral goes");
  assert.equal(codeForm("S two A L4 P二八四"), "s2al4p284");
  assert.equal(codeForm("HX 零三四零八"), "hx03408");
  const shelf = [
    { title: "星海Ⅱ·归途", keys: ["HX-00001", "HX00001", "S2-A-L4-P284"], localBookId: "a" },
    { title: "狂人日记", keys: ["HX-00002", "HX00002", "S2-A-L4-P283"], localBookId: "b" },
  ];
  assert.deepEqual(
    findBooks("星海归途", shelf).map((book) => book.localBookId),
    ["a"],
  );
  assert.deepEqual(
    findBooks("S2 A L4 P二八三", shelf).map((book) => book.localBookId),
    ["b"],
  );
  assert.deepEqual(
    findBooks("S2 A L4 P二八五", shelf),
    [],
    "one digit off is another slot, not a near miss",
  );
});
