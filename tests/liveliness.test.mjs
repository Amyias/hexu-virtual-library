import test from "node:test";
import assert from "node:assert/strict";
import { composeGreeting, createGreeting, GREETING_PREFERENCE } from "../src/app/greeting.js";
import { idleMotion, REST } from "../src/scene/pet-idle.js";

const at = (hour) => new Date(2026, 9, 24, hour, 0);
const reading = {
  enabled: true,
  reading: [{ title: "三体", chapter: 11, chapter_title: "红岸之四" }],
};

test("the greeting follows the clock, an absence and the book last read", () => {
  assert.equal(composeGreeting({ now: at(9) }), "早上好！有想找的书就叫我。");
  assert.equal(composeGreeting({ now: at(2) }), "夜深了！看书别太晚哦，有想找的书就叫我。");
  assert.equal(
    composeGreeting({ now: at(20), memory: reading }),
    "晚上好！上次读到《三体》第 12 章「红岸之四」，要接着读吗？",
  );
  assert.equal(
    composeGreeting({ now: at(15), lastVisit: new Date(2026, 9, 10), memory: reading }),
    "下午好！好久不见呀。上次读到《三体》第 12 章「红岸之四」，要接着读吗？",
  );
  const started = { reading: [{ title: "红楼梦", chapter: 0, chapter_title: "" }] };
  assert.equal(
    composeGreeting({ now: at(12), memory: started }),
    "中午好！上次翻开的《红楼梦》，还想继续读吗？",
  );
  assert.equal(
    composeGreeting({ now: at(12), memory: { ...reading, enabled: false } }),
    "中午好！有想找的书就叫我。",
    "memory switched off is not used even if entries remain",
  );
});

function memoryStorage(values = {}) {
  return { getItem: (k) => values[k] ?? null, setItem: (k, v) => (values[k] = v), values };
}

test("it greets once, waits until nothing else is on screen, and can be switched off", async () => {
  const said = [];
  let free = false;
  const requests = [];
  const greeting = createGreeting({
    say: (text) => said.push(text),
    ready: () => free,
    storage: memoryStorage(),
    request: async (url) => {
      requests.push(url);
      return { ok: true, json: async () => reading };
    },
    clock: () => at(20),
    delay: 0,
  });
  const pending = greeting.greet();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.deepEqual(said, [], "nothing while the reader is busy");
  free = true;
  assert.match(await pending, /红岸之四/);
  assert.deepEqual(requests, ["/memory/state?peek=1"], "peeks without creating a memory file");
  assert.equal(await greeting.greet(), null, "only once per start");
  assert.equal(said.length, 1);

  const off = createGreeting({
    say: (text) => said.push(text),
    ready: () => true,
    storage: memoryStorage({ [GREETING_PREFERENCE]: "off" }),
    request: async () => assert.fail("no request when switched off"),
    delay: 0,
  });
  assert.equal(await off.greet(), null);
  assert.equal(said.length, 1);
});

test("left alone 小和 hops and looks around by day, and gets sleepy at night", () => {
  assert.deepEqual(idleMotion(0), { mood: "idle", hop: 0, look: 0, eyes: 1, yawn: 0, breath: 1 });
  assert.equal(idleMotion(REST - 1).hop, 0, "nothing before it has been quiet a while");
  assert.equal(idleMotion(REST + 0.35).mood, "resting");
  assert.ok(idleMotion(REST + 0.35).hop > 0.08, "a hop at the start of each cycle");
  assert.equal(idleMotion(REST + 5).hop, 0);
  assert.ok(Math.abs(idleMotion(REST + 34).look) > 0.3, "it looks round the hall now and then");
  const night = idleMotion(0, true);
  assert.equal(night.mood, "sleepy");
  assert.ok(night.eyes < 0.5 && night.breath < 1, "drooping eyes and slower breathing");
  assert.ok(idleMotion(REST + 1.2, true).yawn > 0.9, "a yawn");
  assert.equal(idleMotion(REST + 0.35, true).hop, 0, "no hopping when sleepy");
  for (let t = 0; t < 200; t += 0.5) {
    const motion = idleMotion(t, t > 100);
    assert.ok(Math.abs(motion.hop) <= 0.09 && Math.abs(motion.look) <= 0.6 && motion.eyes >= 0);
  }
});
