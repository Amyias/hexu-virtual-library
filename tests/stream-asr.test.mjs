import test from "node:test";
import assert from "node:assert/strict";
import { createStreamClient, heardRequest, toPcm16 } from "../src/voice/server-asr.js";
import { createSpeech } from "../src/voice/speech.js";
import { voice } from "../src/voice/voice.js";

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("an utterance the spotter woke on is acted on as the name plus what followed it", () => {
  assert.equal(heardRequest("笑河读正文", { woke: true, request: "读正文" }), "小和，读正文");
  assert.equal(heardRequest("可以", { woke: true, request: "" }), "小和，", "the name alone");
  assert.equal(heardRequest("今天吃什么", { woke: false }), "今天吃什么");
  assert.equal(
    heardRequest("小和，帮我找三体", { woke: true }),
    "小和，帮我找三体",
    "no request: as heard",
  );
});

test("audio is sent as 16-bit PCM, clamped", () => {
  assert.deepEqual(
    [...toPcm16(new Float32Array([0, 1, -1, 2, -2, 0.5]))],
    [0, 32767, -32768, 32767, -32768, 16383],
  );
});

test("the stream client sends a quarter second at a time, one request at a time", async () => {
  const posts = [];
  let release;
  const client = createStreamClient({
    rate: 16000,
    session: "test-session",
    post: (url, body) => {
      posts.push({ url, samples: body.byteLength / 2 });
      return new Promise((resolve) => (release = () => resolve({ events: [{ type: "wake" }] })));
    },
    onEvents: (payload) => events.push(payload),
    onFail: () => assert.fail("no failure expected"),
  });
  const events = [];
  client.push(new Float32Array(3000));
  assert.equal(posts.length, 0, "less than a quarter second waits for more");
  client.push(new Float32Array(1000));
  assert.deepEqual(posts, [{ url: "/asr/stream?session=test-session", samples: 4000 }]);
  // While a sentence is being recognised, audio queues instead of being dropped or sent twice.
  client.push(new Float32Array(16000 * 5));
  assert.equal(posts.length, 1);
  release();
  await settle();
  assert.equal(events.length, 1);
  assert.equal(posts[1].samples, 16000 * 3, "a backlog goes in pieces no bigger than 3 s");
  release();
  await settle();
  assert.equal(posts[2].samples, 16000 * 2);
  client.close();
  client.push(new Float32Array(8000));
  release();
  await settle();
  assert.equal(posts.length, 3, "nothing is sent after closing");
});

test("a 48 kHz microphone is resampled before sending", () => {
  const sent = [];
  const client = createStreamClient({
    rate: 48000,
    session: "s48",
    post: (url, body) => {
      sent.push(body.byteLength / 2);
      return new Promise(() => {});
    },
    onEvents() {},
    onFail() {},
  });
  client.push(new Float32Array(11999));
  assert.equal(sent.length, 0);
  client.push(new Float32Array(1));
  assert.deepEqual(sent, [4000]);
});

test("three failed requests in a row stop the stream once; a success resets the count", async () => {
  let failing = true;
  let fails = 0;
  let posts = 0;
  const client = createStreamClient({
    rate: 16000,
    session: "sfail",
    post: async () => {
      posts++;
      if (failing) throw new Error("offline");
      return { events: [] };
    },
    onEvents() {},
    onFail: () => fails++,
  });
  client.push(new Float32Array(4000));
  await settle();
  client.push(new Float32Array(4000));
  await settle();
  failing = false;
  client.push(new Float32Array(4000));
  await settle();
  failing = true;
  for (let i = 0; i < 4; i++) {
    client.push(new Float32Array(4000));
    await settle();
  }
  assert.equal(fails, 1);
  assert.equal(posts, 6, "the fourth failure is never attempted");
});

test("continuous listening wakes mid-sentence, interrupts 小和 by name and ignores its echo", async () => {
  const elements = {};
  const $ = (name) =>
    (elements[name] ??= {
      textContent: "",
      className: "",
      classList: { toggle() {}, contains: () => false },
    });
  const original = {
    window: globalThis.window,
    document: globalThis.document,
    navigator: globalThis.navigator,
    fetch: globalThis.fetch,
    AudioContext: globalThis.AudioContext,
    AudioWorkletNode: globalThis.AudioWorkletNode,
    localStorage: globalThis.localStorage,
    isSpeaking: voice.isSpeaking,
  };
  let node;
  let reply = { events: [] };
  globalThis.window = { isSecureContext: true, addEventListener() {} };
  globalThis.document = {
    hidden: false,
    body: { classList: { toggle() {} } },
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) } },
  });
  globalThis.AudioContext = class {
    sampleRate = 16000;
    state = "running";
    audioWorklet = { addModule: async () => {} };
    createMediaStreamSource() {
      return { connect() {}, disconnect() {} };
    }
    close() {}
  };
  globalThis.AudioWorkletNode = class {
    constructor() {
      node = this;
      this.port = {};
    }
    disconnect() {}
  };
  globalThis.fetch = async (url) => {
    if (url === "/asr/ready")
      return { ok: true, json: async () => ({ ready: true, streaming: true }) };
    const answer = reply;
    reply = { events: [] };
    return { ok: true, json: async () => answer };
  };
  let speaking = false;
  voice.isSpeaking = () => speaking;
  const wakes = [];
  const heard = [];
  let interrupted = 0;
  let speech;
  try {
    speech = createSpeech({
      $,
      notice() {},
      wake: () => wakes.push("wake"),
      processText: (...args) => heard.push(args),
      getPhase: () => "IDLE",
      interrupt: () => interrupted++,
    });
    await settle();
    $("micButton").onclick();
    for (let i = 0; i < 5 && !node?.port.onmessage; i++) await settle();
    const send = async (answer) => {
      reply = answer;
      node.port.onmessage({ data: new Float32Array(4000) });
      for (let i = 0; i < 4; i++) await settle();
    };

    await send({ events: [{ type: "wake", at: 1.2 }] });
    assert.deepEqual(wakes, ["wake"], "the name wakes 小和 before the sentence ends");
    await send({
      events: [{ type: "text", text: "笑河，帮我找三体", woke: true, request: "帮我找三体" }],
    });
    assert.deepEqual(heard.at(-1), ["小和，帮我找三体", false, true], "not answered twice");

    speaking = true;
    await send({ events: [{ type: "text", text: "这是完整回答", woke: false }] });
    assert.equal(heard.length, 1, "小和's own voice is not taken for the reader");
    await send({ events: [{ type: "wake", at: 9 }] });
    assert.equal(interrupted, 1, "saying its name over its voice interrupts it");
    speaking = false;
    await send({ events: [{ type: "text", text: "小和，下一页", woke: true }] });
    assert.deepEqual(heard.at(-1), ["小和，下一页", false, true]);
  } finally {
    speech?.stop();
    voice.isSpeaking = original.isSpeaking;
    for (const key of [
      "window",
      "document",
      "fetch",
      "AudioContext",
      "AudioWorkletNode",
      "localStorage",
    ])
      globalThis[key] = original[key];
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: original.navigator,
    });
  }
});
