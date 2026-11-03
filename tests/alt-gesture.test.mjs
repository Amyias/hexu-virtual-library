import test from "node:test";
import assert from "node:assert/strict";
import { createAltGesture, HOLD_MIN, TAP_MAX, TAP_WINDOW } from "../src/voice/alt-gesture.js";

/* A gesture driven by a fake clock: run(ms) advances time and fires due timers. */
function harness() {
  let clock = 0;
  const timers = new Map();
  let nextId = 1;
  const log = [];
  const gesture = createAltGesture({
    onTap: () => log.push("tap"),
    onHoldStart: () => log.push("hold"),
    onHoldEnd: ({ cancelled }) => log.push(cancelled ? "cancel" : "send"),
    now: () => clock,
    setTimer(fn, ms) {
      const id = nextId++;
      timers.set(id, { fn, at: clock + ms });
      return id;
    },
    clearTimer: (id) => timers.delete(id),
  });
  function run(ms) {
    clock += ms;
    for (const [id, timer] of [...timers]) {
      if (timer.at <= clock) {
        timers.delete(id);
        timer.fn();
      }
    }
  }
  const alt = { code: "AltLeft" };
  return {
    gesture,
    log,
    run,
    down: (event = alt) => gesture.keydown(event),
    up: (event = alt) => gesture.keyup(event),
  };
}

test("a short press of left Alt wakes, but only once a second press can no longer follow", () => {
  const h = harness();
  assert.equal(h.down(), true, "the shortcut claims its own key");
  h.run(80);
  h.up();
  h.run(TAP_WINDOW - 1);
  assert.deepEqual(h.log, []);
  h.run(1);
  assert.deepEqual(h.log, ["tap"]);
});

test("a tap then a held press records until the key is let go, without waking first", () => {
  const h = harness();
  h.down();
  h.run(80);
  h.up();
  h.run(150);
  h.down();
  assert.deepEqual(h.log, ["hold"]);
  assert.equal(h.gesture.holding, true);
  for (let i = 0; i < 10; i++) {
    h.run(200);
    h.down({ code: "AltLeft", repeat: true }); // auto-repeat while held changes nothing
  }
  h.up();
  h.run(TAP_WINDOW * 2);
  assert.deepEqual(h.log, ["hold", "send"]);
});

test("a quick double tap is a recording too short to send", () => {
  const h = harness();
  h.down();
  h.run(60);
  h.up();
  h.run(100);
  h.down();
  h.run(HOLD_MIN - 1);
  h.up();
  assert.deepEqual(h.log, ["hold", "cancel"]);
});

test("Alt used with another key or the mouse is someone else's shortcut", () => {
  const h = harness();
  h.down();
  h.down({ code: "Tab" }); // Alt+Tab
  h.up();
  h.run(TAP_WINDOW * 2);
  h.down();
  h.gesture.pointerdown(); // Alt+click
  h.up();
  h.run(TAP_WINDOW * 2);
  assert.deepEqual(h.log, []);
});

test("holding Alt down too long on its own is not a tap", () => {
  const h = harness();
  h.down();
  h.run(TAP_MAX + 1);
  h.up();
  h.run(TAP_WINDOW * 2);
  assert.deepEqual(h.log, []);
});

test("another key, the mouse or losing focus while recording throws the recording away", () => {
  for (const interrupt of [
    (h) => h.down({ code: "KeyF" }),
    (h) => h.gesture.pointerdown(),
    (h) => h.gesture.blur(),
  ]) {
    const h = harness();
    h.down();
    h.up();
    h.run(50);
    h.down();
    h.run(1000);
    interrupt(h);
    assert.equal(h.gesture.holding, false);
    h.up();
    h.run(TAP_WINDOW * 2);
    assert.deepEqual(h.log, ["hold", "cancel"]);
  }
});

test("right Alt (AltGr on many layouts) and other keys are left alone", () => {
  const h = harness();
  assert.equal(h.down({ code: "AltRight" }), false);
  assert.equal(h.up({ code: "AltRight" }), false);
  h.run(TAP_WINDOW * 2);
  assert.deepEqual(h.log, []);
});

test("a key pressed between the tap and the second press keeps the tap from firing", () => {
  const h = harness();
  h.down();
  h.up();
  h.run(50);
  h.down({ code: "KeyA" });
  h.run(TAP_WINDOW * 2);
  assert.deepEqual(h.log, []);
});
