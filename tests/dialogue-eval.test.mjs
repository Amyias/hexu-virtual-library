import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { books as slots } from "../src/data/catalog.js";
import { decide, pickChoice } from "../src/app/dialogue.js";
import { lookupBooks } from "../src/reader/library.js";
import { evaluationShelf, matches } from "../tools/voice-eval/score.mjs";

const scenes = JSON.parse(fs.readFileSync("tests/dialogue-eval.json", "utf8"));
const shelf = evaluationShelf(
  slots,
  JSON.parse(fs.readFileSync("tests/voice-eval/books.json", "utf8")),
);
const titled = (title) => shelf.find((book) => book.title === title);

/** Run the cases that are not known gaps; return the gaps that still fail, for the log. */
function replay(cases, run, check) {
  const open = [];
  for (const scene of cases) {
    const result = run(scene);
    if (scene.gap) {
      if (!check(scene, result)) open.push(scene.gap);
      continue;
    }
    assert.ok(check(scene, result), `${scene.text} → ${JSON.stringify(result)}`);
  }
  return open;
}

test("typed requests route as the scenes expect", (t) => {
  const open = replay(
    scenes.routing,
    (scene) =>
      decide(scene.text, {
        phase: scene.phase || "IDLE",
        direct: true,
        lookup: (text) => lookupBooks(text, [], shelf),
        fullText: true,
        understand: true,
      }),
    (scene, decision) =>
      matches(scene.expect, decision) &&
      (!scene.expect.fact || decision.fact === scene.expect.fact),
  );
  if (open.length) t.diagnostic("已知缺口：" + open.join("；"));
});

test("answers to 「which one?」 pick the book the scenes expect", (t) => {
  const open = replay(
    scenes.choices,
    (scene) => pickChoice(scene.text, scene.offered.map(titled))?.title ?? null,
    (scene, picked) => picked === scene.pick,
  );
  if (open.length) t.diagnostic("已知缺口：" + open.join("；"));
});

test("every scene names books that are on the evaluation shelf", () => {
  for (const scene of scenes.routing)
    for (const title of [scene.expect.book, ...(scene.expect.books || [])].filter(Boolean))
      assert.ok(titled(title), title);
  for (const scene of scenes.choices)
    for (const title of scene.offered) assert.ok(titled(title), title);
});
