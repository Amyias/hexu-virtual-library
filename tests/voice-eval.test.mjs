import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { books as slots } from "../src/data/catalog.js";
import { SEGMENT } from "../src/voice/server-asr.js";
import { segmentsOf } from "../tools/voice-eval/audio.mjs";
import {
  evaluationShelf,
  replay,
  matches,
  plain,
  editDistance,
  percentile,
  scoreClip,
  summarize,
} from "../tools/voice-eval/score.mjs";

const { prompts } = JSON.parse(fs.readFileSync("tests/voice-eval/prompts.json", "utf8"));
const bound = JSON.parse(fs.readFileSync("tests/voice-eval/books.json", "utf8"));
const shelf = evaluationShelf(slots, bound);
const byId = (id) => prompts.find((prompt) => prompt.id === id);

const RATE = SEGMENT.TARGET_RATE;
const quiet = (seconds) => new Float32Array(Math.round(seconds * RATE));
const tone = (seconds) => quiet(seconds).map((_, i) => Math.sin(i / 7) * 0.2);
const join = (...parts) => {
  const out = new Float32Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
};

test("recordings are cut by the program's own segmentation rule", () => {
  const two = segmentsOf(join(quiet(0.8), tone(0.6), quiet(1.2), tone(0.8), quiet(1)));
  assert.equal(two.length, 2, "a one-second pause separates two utterances");
  const frameMs = (SEGMENT.FRAME / RATE) * 1000;
  for (const segment of two)
    assert.ok(
      Math.abs(segment.tailMs - SEGMENT.SILENCE_FRAMES * frameMs) <= frameMs,
      segment.tailMs,
    );
  assert.equal(segmentsOf(join(quiet(0.5), tone(0.6), quiet(0.3), tone(0.6), quiet(1))).length, 1);
  // Today a click is sent as speech too: the closing silence alone outlasts the minimum length.
  // The VAD step (docs/INTELLIGENCE_PLAN.md 5.1) is expected to change this.
  assert.equal(segmentsOf(join(quiet(0.5), tone(0.1), quiet(1))).length, 1);
  assert.equal(
    segmentsOf(join(quiet(0.5), tone(1))).length,
    1,
    "speech running to the end still counts",
  );
});

test("the prompt list is complete and every expectation names a shelved book", () => {
  const ids = prompts.map((prompt) => prompt.id);
  assert.equal(new Set(ids).size, ids.length, "ids are unique");
  assert.ok(prompts.length >= 60);
  const titles = new Set(bound.map((book) => book.title));
  for (const prompt of prompts) {
    assert.match(prompt.id, /^[a-z]+-\d+$/, "the recorder only accepts this shape");
    assert.ok(prompt.say.length >= 1 && prompt.say.every((part) => part.trim()), prompt.id);
    assert.equal(typeof prompt.expect.wake, "boolean", prompt.id);
    for (const title of [prompt.expect.book, ...(prompt.expect.books || [])].filter(Boolean))
      assert.ok(titles.has(title), `${prompt.id}: ${title}`);
  }
  for (const book of bound)
    assert.ok(
      slots.some((slot) => slot.bookId === book.bookId),
      book.bookId,
    );
  assert.ok(
    prompts.some((prompt) => !prompt.expect.wake),
    "negatives measure false wakes",
  );
});

test("replay routes heard text exactly as the program does", () => {
  const found = replay(byId("title-01"), ["小和，帮我找三体。"], shelf);
  assert.deepEqual(
    [found.wake, found.outcome.type, found.outcome.book.title],
    [true, "present", "三体"],
  );
  const twoStep = replay(byId("step-01"), ["小和。", "帮我找三体。"], shelf);
  assert.ok(matches(byId("step-01").expect, twoStep.outcome), "「小和」 opens the waiting window");
  const unaddressed = replay(byId("neg-06"), ["帮我找三体"], shelf);
  assert.deepEqual([unaddressed.wake, unaddressed.outcome.type], [false, "ignore"]);
  const choice = replay(byId("part-01"), ["小和，帮我找星海"], shelf);
  assert.ok(matches(byId("part-01").expect, choice.outcome));
  const reading = replay(byId("read-01"), ["小和，下一页"], shelf);
  assert.ok(matches(byId("read-01").expect, reading.outcome));
  assert.ok(
    !matches(byId("title-01").expect, replay(byId("title-01"), ["小何帮我找三国"], shelf).outcome),
  );
  // Continuous listening: the spotter heard the name the transcript spelt 「笑河」 or lost.
  const spotted = replay(
    byId("read-03"),
    [{ text: "笑河读正文", woke: true, request: "读正文" }],
    shelf,
  );
  assert.ok(spotted.wake && matches(byId("read-03").expect, spotted.outcome), "while reading");
  const nameOnly = replay(byId("wake-02"), [{ text: "可以", woke: true, request: "" }], shelf);
  assert.ok(matches(byId("wake-02").expect, nameOnly.outcome), "a misheard name is not a request");
});

test("character errors compare text the way the recogniser writes it", () => {
  assert.equal(plain("小和，帮我找 HX 零二二七三。"), "小和帮我找hx02273");
  assert.equal(editDistance("三体", "三题"), 1);
  assert.equal(editDistance("", "abc"), 3);
  assert.equal(percentile([5, 1, 3, 2, 4], 50), 3);
  assert.equal(percentile([1, 2, 3, 4, 100], 95), 100);
  assert.equal(percentile([], 50), null);
});

test("the summary counts wakes, false wakes, accuracy, errors and latency", () => {
  const clip = (texts, seconds = 3) => ({
    seconds,
    segments: texts.map((text) => ({ text, tailMs: 700, recogMs: 100 })),
  });
  const used = ["title-01", "wake-01", "neg-01", "neg-13"].map(byId);
  const rows = [
    scoreClip(used[0], clip(["小和，帮我找三题"]), shelf), // wrong title heard
    scoreClip(used[1], clip(["小和"]), shelf),
    scoreClip(used[2], clip(["我和小明一起去图书馆"], 1800), shelf),
    scoreClip(used[3], clip(["小河边上有一座桥"], 1800), shelf), // an alias of the wake word
  ];
  const summary = summarize(rows, used);
  assert.equal(summary.wakeRecall, 1);
  assert.equal(summary.falseWakes, 1);
  assert.equal(summary.falseWakesPerHour, 1, "one false wake in an hour of negatives");
  assert.equal(summary.intentAccuracy, 0.5);
  assert.equal(summary.findAccuracy, 0);
  assert.ok(summary.characterErrorRate > 0 && summary.characterErrorRate < 0.1);
  assert.deepEqual(summary.latencyMs, { p50: 800, p95: 800 });
  assert.equal(summary.segmentationMismatches, 0);
  assert.deepEqual(summary.categories["不该唤醒"], { clips: 2, correct: 1, accuracy: 0.5 });
});
