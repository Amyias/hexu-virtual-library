import test from "node:test";
import assert from "node:assert/strict";
import {
  createPhaseMachine,
  TRANSITIONS,
  IDLE,
  NAVIGATING,
  PRESENTING,
  READING,
  RETURNING,
} from "../src/app/phases.js";
import {
  decide,
  createAttention,
  protocolResponse,
  requestOf,
  readingCommand,
  FOUND,
  LOCATING,
} from "../src/app/dialogue.js";
import { findBook as findInstalledBook } from "../src/voice/intent.js";

test("the reading loop is one cycle and refuses every out-of-order step", () => {
  const seen = [];
  const machine = createPhaseMachine((next, previous, event) =>
    seen.push(`${previous}-${event}->${next}`),
  );
  // Nothing but a walk can start from IDLE: a second request, a 「放回」, a stray animation end.
  for (const event of ["arrive", "present", "return", "shelve", "nonsense"])
    assert.equal(machine.send(event), false, event);
  assert.equal(machine.phase, IDLE);
  for (const [event, phase] of [
    ["navigate", NAVIGATING],
    ["arrive", PRESENTING],
    ["present", READING],
    ["return", RETURNING],
    ["shelve", IDLE],
  ]) {
    assert.equal(machine.send(event), true, event);
    assert.equal(machine.phase, phase);
  }
  assert.equal(seen.length, 5);
  // Mid-walk, another find is refused rather than starting a second walk.
  machine.send("navigate");
  assert.equal(machine.send("navigate"), false);
  assert.equal(machine.is(NAVIGATING, PRESENTING), true);
  // Every phase has exactly one way out, and the table cannot be edited at runtime.
  for (const exits of Object.values(TRANSITIONS)) assert.equal(Object.keys(exits).length, 1);
  assert.throws(() => (TRANSITIONS[IDLE].return = READING));
  assert.equal(machine.can("toString"), false, "inherited keys are not events");
});

import { readingBooks } from "./fixtures/books.mjs";
const findBook = (text) => findInstalledBook(text, readingBooks);
const lookup = (request) => findBook(request);
const ctx = (extra = {}) => ({ phase: IDLE, lookup, ...extra });

test("an utterance is only heard when it is addressed, typed, or inside the wake window", () => {
  assert.equal(decide("帮我找三体", ctx()).type, "ignore");
  assert.equal(decide("帮我找三体", ctx({ awake: true })).type, "present");
  assert.equal(decide("帮我找三体", ctx({ direct: true })).type, "present");
  // The wake word alone wakes, but not twice for one utterance already answered from an interim.
  assert.deepEqual(decide("小和", ctx()), { type: "wake-only", wake: true });
  assert.deepEqual(decide("小和你好", ctx({ wasInterimWake: true })), {
    type: "wake-only",
    wake: false,
  });
  // Wake word, greeting and punctuation go; the title marks stay for the matcher to normalise.
  assert.equal(requestOf("小和，你好！帮我找 《三体》。"), "帮我找《三体》");
});

test("a found book is fetched, with the reply depending on how it was asked", () => {
  const addressed = decide("小和，帮我找三体", ctx());
  assert.equal(addressed.type, "present");
  assert.equal(addressed.book.title, "三体");
  assert.equal(addressed.speech, FOUND);
  assert.equal(addressed.wake, true);
  const typed = decide("HX-11360", ctx({ direct: true }));
  assert.equal(typed.book.bookId, "HX-11360");
  assert.equal(typed.speech, LOCATING);
  assert.equal(typed.wake, false);
});

test("what the rules cannot place goes to the model, then the reading library, then a polite no", () => {
  const unknown = "霍金写的那本";
  assert.deepEqual(decide(unknown, ctx({ direct: true, understand: true, fullText: true })), {
    type: "model",
    wake: false,
    request: unknown,
  });
  assert.equal(decide(unknown, ctx({ direct: true, fullText: true })).type, "full-text");
  assert.equal(decide(unknown, ctx({ direct: true })).type, "no-match");
  assert.equal(decide("三体", ctx({ direct: true, fullText: true })).type, "present");
  // Empty IDs are not selectable, even when the physical slot exists.
  assert.equal(decide("HX-00001", ctx({ direct: true, lookup: () => undefined })).type, "no-match");
  // A book the reading library already holds is fetched, not searched for again.
  const local = { title: "三体", localBookId: "x" };
  assert.equal(
    decide("三体", ctx({ direct: true, fullText: true, lookup: () => local })).type,
    "present",
  );
});

test("while reading, commands act on the book in hand and nothing starts another walk", () => {
  const reading = (text, extra) => decide(text, ctx({ phase: READING, ...extra }));
  for (const [text, command] of [
    ["小和，放回书架", "return"],
    ["小和下一页", "next"],
    ["小和往前翻", "previous"],
    ["小和继续阅读", "fullText"],
    ["小和合上", "close"],
    ["小和翻开", "open"],
    ["小和看看芯片", "chip"],
  ])
    assert.deepEqual(reading(text), { type: "reading", command }, text);
  assert.deepEqual(reading("小和帮我找三体"), { type: "reading", command: "hint" });
  assert.deepEqual(
    reading("帮我找三体", { awake: true }),
    { type: "reading", command: null },
    "unaddressed chatter is not answered",
  );
  assert.equal(
    readingCommand("合上"),
    "close",
    "「合上」 closes the cover; it does not return the book",
  );
  for (const phase of [NAVIGATING, PRESENTING, RETURNING]) {
    assert.deepEqual(decide("小和帮我找三体", ctx({ phase })), { type: "busy", tell: true });
    assert.deepEqual(decide("帮我找三体", ctx({ phase, awake: true })), {
      type: "busy",
      tell: false,
    });
  }
});

test("the wake window opens, reports its lapse exactly once, and can be cleared", () => {
  let now = 1000;
  const attention = createAttention(() => now);
  assert.equal(attention.active(), false);
  assert.equal(attention.lapsed(), false);
  attention.wake();
  now += 24999;
  assert.equal(attention.active(), true);
  now += 2;
  assert.equal(attention.active(), false);
  assert.equal(attention.lapsed(), true);
  assert.equal(attention.lapsed(), false);
  attention.wake(10);
  attention.clear();
  now += 20;
  assert.equal(attention.lapsed(), false, "a cleared window does not lapse");
});

test("the published protocol keeps its shape", () => {
  const options = { anchors: [-6, -3, 0, 3, 6], heights: [0.3, 0.7, 1.2, 1.7], home: [0, 1.2, 5] };
  const book = findBook("三体");
  const found = protocolResponse("好的", book, false, options);
  assert.deepEqual(Object.keys(found), ["speech", "is_wake_only", "action", "target", "book_data"]);
  assert.equal(found.action, "NAVIGATE_TO_BOOK");
  assert.deepEqual(found.target, {
    shelf_id: "Shelf_5",
    shelf_side: "A",
    layer: 3,
    world_position: [6, 1.2, 0],
  });
  assert.equal(found.book_data.title, "三体");
  const idle = protocolResponse("有什么需求吗？", null, true, options);
  assert.equal(idle.action, "IDLE");
  assert.equal(idle.is_wake_only, true);
  assert.deepEqual(idle.target.world_position, [0, 1.2, 5]);
  assert.deepEqual(idle.book_data, { title: "", author: "", category: "", synopsis: "" });
});
