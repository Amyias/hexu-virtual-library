import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createHash } from "node:crypto";
import { createTypewriter, splitGlyphs } from "../src/app/pixel-dialogue.js";
import { createDialogueSounds } from "../src/app/dialogue-sounds.js";
import { decide } from "../src/app/dialogue.js";

function clock() {
  let now = 0,
    id = 0;
  const jobs = new Map();
  return {
    jobs,
    schedule(fn, delay) {
      const key = ++id;
      jobs.set(key, { fn, at: now + delay });
      return key;
    },
    cancel(key) {
      jobs.delete(key);
    },
    tick(ms) {
      const until = now + ms;
      while (jobs.size) {
        const [key, job] = [...jobs].sort((a, b) => a[1].at - b[1].at)[0];
        if (job.at > until) break;
        now = job.at;
        jobs.delete(key);
        job.fn();
      }
      now = until;
    },
  };
}

test("typewriter reveals complete Unicode glyphs and cancels stale replies", () => {
  const timer = clock();
  let visible = "",
    done = 0;
  const sounds = [];
  const writer = createTypewriter({
    ...timer,
    onText: (value) => {
      visible = value;
    },
    onGlyph: (glyph) => sounds.push(glyph),
    onDone: () => done++,
  });
  const phrase = "你👨‍👩‍👧‍👦e\u0301好";
  assert.equal(splitGlyphs(phrase).length, 4);
  writer.start(phrase);
  assert.equal(visible, "");
  const stale = [...timer.jobs.values()][0].fn;
  timer.tick(45);
  assert.equal(visible, "你");
  timer.tick(65);
  assert.equal(visible, "你👨‍👩‍👧‍👦");
  writer.start("新回复");
  stale();
  assert.equal(visible, "");
  timer.tick(1000);
  assert.equal(visible, "新回复");
  assert.equal(done, 1);
  assert.equal(writer.getState().typing, false);
  writer.start("不应继续打印");
  timer.tick(45);
  writer.stop();
  const stopped = visible,
    count = sounds.length;
  timer.tick(1000);
  assert.equal(visible, stopped);
  assert.equal(sounds.length, count);
  assert.equal(timer.jobs.size, 0);
});

test("punctuation pauses, explicit instant mode finishes at once, and streams stay separate", () => {
  const timer = clock();
  let visible = "",
    ticks = 0,
    done = 0;
  const writer = createTypewriter({
    ...timer,
    onText: (value) => {
      visible = value;
    },
    onGlyph: () => ticks++,
    onDone: () => done++,
  });
  writer.start("你，好");
  timer.tick(110);
  assert.equal(visible, "你，");
  timer.tick(169);
  assert.equal(visible, "你，");
  timer.tick(1);
  assert.equal(visible, "你，好");
  assert.equal(done, 1);
  writer.start("完整回复", { instant: true });
  assert.equal(visible, "完整回复");
  assert.equal(timer.jobs.size, 0);
  assert.equal(ticks, 3);
  assert.equal(done, 2);
});

class AudioMock {
  static created = 0;
  constructor() {
    AudioMock.created++;
    this.state = "suspended";
    this.currentTime = 0;
    this.destination = {};
    this.nodes = [];
  }
  async resume() {
    this.state = "running";
  }
  parameter() {
    return {
      value: 0,
      setValueAtTime() {},
      exponentialRampToValueAtTime() {},
      cancelScheduledValues() {},
    };
  }
  node(extra = {}) {
    const node = {
      connect() {},
      disconnect() {
        this.disconnected = true;
      },
      ...extra,
    };
    this.nodes.push(node);
    return node;
  }
  createGain() {
    return this.node({ gain: this.parameter() });
  }
  createBiquadFilter() {
    return this.node({ frequency: this.parameter() });
  }
  createOscillator() {
    return this.node({
      frequency: this.parameter(),
      start() {
        this.started = true;
      },
      stop(when) {
        if (when === undefined) this.onended?.();
      },
    });
  }
}

test("dialogue sounds wait for unlock, mute immediately, throttle and release nodes", async () => {
  AudioMock.created = 0;
  const values = new Map();
  const host = { AudioContext: AudioMock };
  let context;
  host.AudioContext = class extends AudioMock {
    constructor() {
      super();
      context = this;
    }
  };
  const audio = createDialogueSounds({
    host,
    storage: { getItem: (key) => values.get(key), setItem: (k, v) => values.set(k, v) },
  });
  audio.pop();
  audio.type("你", 1);
  assert.equal(AudioMock.created, 0, "no unsolicited AudioContext at boot");
  assert.equal(await audio.unlock(), true);
  audio.pop();
  audio.type("你", 1);
  audio.type("好", 2);
  audio.type("，", 3);
  audio.type(" ", 4);
  assert.equal(audio.getState().pops, 1);
  assert.equal(audio.getState().ticks, 1);
  context.currentTime = 0.065;
  audio.type("好", 2);
  assert.equal(audio.getState().ticks, 2);
  audio.setEnabled(false);
  assert.equal(audio.getState().activeVoices, 0);
  assert.equal(values.get("hexu-dialogue-sound"), "off");
  audio.pop();
  audio.type("字", 3);
  assert.equal(audio.getState().pops, 1);
  assert.equal(audio.getState().ticks, 2);
  audio.setEnabled(true);
  assert.equal(await audio.unlock(), true);
  assert.equal(AudioMock.created, 1, "reuse one audio context");
  audio.type("新", 1);
  audio.stop();
  assert.equal(audio.getState().activeVoices, 0);
});

test("saved mute and unavailable audio do not break text replies", async () => {
  const muted = createDialogueSounds({
    host: { AudioContext: AudioMock },
    storage: { getItem: () => "off" },
  });
  assert.equal(await muted.unlock(), false);
  assert.equal(muted.getState().enabled, false);
  const host = {};
  Object.defineProperty(host, "localStorage", {
    get() {
      throw Error("blocked storage");
    },
  });
  const unsupported = createDialogueSounds({ host });
  assert.equal(await unsupported.unlock(), false);
  unsupported.pop();
  unsupported.type("字", 1);
  unsupported.stop();
});

test("pet conversation stays local and never searches or moves books", () => {
  const options = {
    phase: "IDLE",
    lookup: () => {
      throw Error("chat must not search books");
    },
  };
  for (const text of ["小和你是谁", "小和谢谢", "小和你能做什么", "小和再见"])
    assert.equal(decide(text, options).type, "reply");
  assert.equal(decide("小和你好", options).type, "wake-only");
});

test("offline Chinese pixel font matches its provenance and ships all licence notices", () => {
  const directory = new URL("../public/fonts/fusion-pixel/", import.meta.url);
  const source = JSON.parse(fs.readFileSync(new URL("SOURCE.json", directory)));
  const font = fs.readFileSync(new URL(source.font, directory));
  assert.equal(font.subarray(0, 4).toString(), "wOF2");
  assert.equal(createHash("sha256").update(font).digest("hex"), source.sha256);
  for (const name of [
    "OFL.txt",
    "LICENSES/ark-pixel/OFL.txt",
    "LICENSES/cubic-11/OFL.txt",
    "LICENSES/galmuri/LICENSE.txt",
  ])
    assert.ok(fs.readFileSync(new URL(name, directory), "utf8").includes("SIL OPEN FONT LICENSE"));
  const packager = fs.readFileSync(new URL("../tools/package-local.mjs", import.meta.url), "utf8");
  assert.ok(packager.includes('path.join("public", "fonts")'));
});
