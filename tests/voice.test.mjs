import test from "node:test";
import assert from "node:assert/strict";
import {
  completedPart,
  createVoice,
  pickSystemVoice,
  speakable,
  splitSentences,
} from "../src/voice/voice.js";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function harness({ ready = true, failOn = null } = {}) {
  const requested = [];
  const played = [];
  const spoken = [];
  const audios = [];
  const synthesis = {
    speaking: false,
    getVoices: () => [
      { name: "Microsoft Huihui", lang: "zh-CN" },
      { name: "Microsoft Yating", lang: "zh-TW" },
    ],
    speak: (utterance) => spoken.push(utterance),
    cancel: () => {},
  };
  const voice = createVoice({
    fetch: async (url, options = {}) => {
      if (url === "/tts/ready")
        return { ok: ready, json: async () => ({ ready, voice: "欣然", model: "PrimeTTS v2.1" }) };
      const { text } = JSON.parse(options.body);
      requested.push(text);
      if (failOn && text.includes(failOn)) return { ok: false, status: 500 };
      return { ok: true, blob: async () => ({ text }) };
    },
    synthesis,
    Utterance: class {
      constructor(text) {
        this.text = text;
      }
    },
    createAudio: (url) => {
      const audio = {
        url,
        paused: false,
        play: async () => {
          played.push(url);
          setTimeout(() => !audio.paused && audio.onended?.(), 5);
        },
        pause: () => (audio.paused = true),
      };
      audios.push(audio);
      return audio;
    },
    urls: { createObjectURL: (blob) => "blob:" + blob.text, revokeObjectURL: () => {} },
  });
  return { voice, requested, played, spoken, audios };
}

test("replies are cut into sentence pieces, long ones at a comma", () => {
  assert.deepEqual(splitSentences("你好，我是小和。有什么需要吗？"), [
    "你好，我是小和。",
    "有什么需要吗？",
  ]);
  assert.deepEqual(splitSentences("。。！"), [], "punctuation alone is not spoken");
  const long = "第一段很长很长，" + "字".repeat(60) + "，" + "尾".repeat(30) + "。";
  const pieces = splitSentences(long, 50);
  assert.ok(pieces.every((piece) => piece.length <= 50));
  assert.equal(pieces.join(""), long);
});

test("the system fallback prefers a Taiwan voice over the first Chinese one", () => {
  const voices = [
    { name: "Microsoft Huihui", lang: "zh-CN" },
    { name: "Microsoft Hanhan", lang: "zh-TW" },
    { name: "Microsoft Yating", lang: "zh-TW" },
  ];
  assert.equal(pickSystemVoice(voices).name, "Microsoft Yating");
  assert.equal(pickSystemVoice([voices[0]]).name, "Microsoft Huihui");
  assert.equal(pickSystemVoice([{ name: "X", lang: "zh-TW" }, voices[0]]).name, "X");
  assert.equal(pickSystemVoice([{ name: "Zira", lang: "en-US" }]), undefined);
});

test("the local voice speaks sentence by sentence and closes the echo gate meanwhile", async () => {
  const { voice, requested, played, spoken } = harness();
  const done = voice.speak("你好，我是小和。有什么需要吗？");
  await tick();
  assert.equal(voice.isSpeaking(), true);
  await done;
  assert.deepEqual(requested, ["你好，我是小和。", "有什么需要吗？"]);
  assert.deepEqual(played, ["blob:你好，我是小和。", "blob:有什么需要吗？"]);
  assert.equal(spoken.length, 0, "no system voice while the local one works");
  assert.equal(voice.isSpeaking(), false);
  assert.equal(voice.getState().engine, "local");
  assert.equal(voice.getState().local.voice, "欣然");
});

test("without the local model the system voice reads the whole reply", async () => {
  const { voice, requested, spoken } = harness({ ready: false });
  await voice.speak("天亮了。阳光照进馆内。");
  assert.deepEqual(requested, []);
  assert.equal(spoken.length, 1);
  assert.equal(spoken[0].text, "天亮了。阳光照进馆内。");
  assert.equal(spoken[0].voice.name, "Microsoft Yating");
  assert.equal(spoken[0].lang, "zh-TW");
});

test("a local failure mid-reply hands the rest to the system voice", async () => {
  const { voice, played, spoken } = harness({ failOn: "第二句" });
  await voice.speak("第一句。第二句。第三句。");
  assert.deepEqual(played, ["blob:第一句。"]);
  assert.equal(spoken.length, 1);
  assert.equal(spoken[0].text, "第二句。第三句。");
});

test("a new reply or a cancel silences the one still playing", async () => {
  const { voice, requested, audios, spoken } = harness();
  const first = voice.speak("第一段。很长的第二段。");
  await tick();
  const second = voice.speak("新的回答。");
  await Promise.all([first, second]);
  assert.ok(audios[0].paused, "the first reply stopped");
  assert.ok(!requested.includes("很长的第二段。") || audios.length === 2);
  assert.equal(audios.at(-1).url, "blob:新的回答。");
  const third = voice.speak("会被取消。");
  await tick();
  voice.cancel();
  await third;
  assert.equal(voice.isSpeaking(), false);
  assert.equal(spoken.length, 0);
});

test("a growing reply is spoken sentence by sentence as each one completes", async () => {
  assert.equal(completedPart("你好呀，我是"), "", "an unfinished sentence waits");
  assert.equal(completedPart("你好呀。我是小和"), "你好呀。");
  assert.equal(completedPart("你好呀。我是小和。", 4), "我是小和。");
  const long = "这是一段很长很长的回答".repeat(6) + "，后面还在写";
  assert.ok(completedPart(long).endsWith("，"), "a long sentence starts at its last comma");
  assert.equal(speakable("**重点**是[1]《三体》"), "重点是《三体》");

  const { voice, requested, played } = harness();
  const reply = voice.stream();
  reply.push("你好呀，");
  await tick();
  assert.deepEqual(requested, [], "nothing is synthesised before a sentence ends");
  reply.push("你好呀，我是小和。今天");
  await tick();
  assert.deepEqual(requested, ["你好呀，我是小和。"], "the first sentence starts at once");
  assert.equal(voice.isSpeaking(), true);
  reply.push("你好呀，我是小和。今天想读点什么？");
  await reply.end("你好呀，我是小和。今天想读点什么？要我推荐吗");
  assert.deepEqual(played, ["blob:你好呀，我是小和。", "blob:今天想读点什么？", "blob:要我推荐吗"]);
  assert.equal(voice.isSpeaking(), false);
});

test("without the local voice a streamed reply goes to system speech batch by batch", async () => {
  const { voice, spoken } = harness({ ready: false });
  const reply = voice.stream();
  reply.push("第一句。");
  await tick();
  reply.push("第一句。第二句。");
  await reply.end("第一句。第二句。");
  assert.deepEqual(
    spoken.map((utterance) => utterance.text),
    ["第一句。", "第二句。"],
  );
});
