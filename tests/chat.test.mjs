import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { createChatSession } from "../src/voice/chat.js";
import { decide, conversationText } from "../src/app/dialogue.js";
const ok = (body, status = 200) => new Response(JSON.stringify(body), { status });
function service() {
  const calls = [];
  let config = "one",
    mode = "ok";
  return {
    calls,
    setConfig: (value) => (config = value),
    setMode: (value) => (mode = value),
    request: async (url, options) => {
      if (url.endsWith("ready")) return ok({ ready: true, configuration: config });
      const body = JSON.parse(options.body);
      calls.push(body);
      if (mode === "error") return ok({ error: "模型服务返回 401" }, 502);
      return ok({ reply: "自然语言回答", model: "test-model", configuration: config });
    },
  };
}
test("general questions preserve wording and do not search/move books, including during reading", () => {
  const ctx = { direct: true, phase: "IDLE", fullText: true, understand: true, lookup: () => null };
  for (const text of [
    "小和，什么是机器学习？",
    "下一页是什么意思",
    "芯片的原理",
    "帮我找一下代码错误",
    "三体的主题是什么？",
    "三体讲什么",
    "什么是书",
    "如何放回书架",
  ])
    for (const phase of ["IDLE", "READING"])
      assert.equal(decide(text, { ...ctx, phase }).type, "chat", text);
  assert.equal(
    conversationText("小和，Hello world! 你好，请解释 C++。"),
    "Hello world! 你好，请解释 C++。",
  );
  assert.equal(decide("小和你是谁", ctx).type, "chat");
  assert.equal(decide("小和你好", ctx).type, "wake-only");
  assert.equal(decide("帮我找《不存在的书》", ctx).type, "model");
  assert.equal(decide("下一页", { ...ctx, phase: "READING" }).command, "next");
  assert.equal(decide("放回书架", { ...ctx, phase: "READING" }).command, "return");
});
test("conversation sends successful pairs, bounds context and resets when provider/model changes", async () => {
  const backend = service();
  const session = createChatSession(backend);
  await session.ask("第一问", "IDLE");
  await session.ask("继续讲", "READING", "HX-02273");
  assert.deepEqual(backend.calls[1].history, [
    { role: "user", content: "第一问" },
    { role: "assistant", content: "自然语言回答" },
  ]);
  assert.equal(backend.calls[1].bookId, "HX-02273");
  backend.setMode("error");
  assert.match((await session.ask("失败", "IDLE")).error, /401/);
  assert.equal(session.getState().turns, 2);
  backend.setMode("ok");
  for (let i = 0; i < 9; i++) await session.ask(`问题${i}`, "IDLE");
  assert.equal(session.getState().turns, 6);
  assert.equal(backend.calls.at(-1).history.length, 12);
  backend.setConfig("other-provider");
  await session.ask("换模型", "IDLE");
  assert.deepEqual(backend.calls.at(-1).history, []);
  session.clear();
  assert.equal(session.getState().turns, 0);
});
test("stopping a pending conversation rejects late replies and never contaminates the next turn", async () => {
  let complete;
  const backend = service();
  const normal = backend.request;
  backend.request = async (url, options) =>
    url === "/chat"
      ? new Promise((resolve) => {
          complete = resolve;
        })
      : normal(url, options);
  const session = createChatSession(backend);
  const old = session.ask("旧问题", "IDLE");
  while (!complete) await new Promise((resolve) => setTimeout(resolve, 1));
  assert.equal((await session.ask("重复", "IDLE")).busy, true);
  session.cancel();
  complete(ok({ reply: "迟到的回答", configuration: "one" }));
  assert.equal((await old).cancelled, true);
  assert.equal(session.getState().turns, 0);
  assert.equal(session.getState().busy, false);
});
test("missing configuration and timeout produce explicit connection messages", async () => {
  const missing = createChatSession({
    request: async () => ok({ ready: false, reason: "尚未配置模型密钥" }, 503),
  });
  assert.match((await missing.ask("你好", "IDLE")).error, /未配置/);
  const slow = createChatSession({
    timeout: 5,
    request: (_url, options) =>
      new Promise((_resolve, reject) =>
        options.signal.addEventListener("abort", () =>
          reject(Object.assign(new Error(), { name: "AbortError" })),
        ),
      ),
  });
  assert.match((await slow.ask("你好", "IDLE")).error, /超时/);
});
const python = [process.env.PYTHON, path.resolve(".cache/venv/Scripts/python.exe"), "python"].find(
  (cmd) => cmd && spawnSync(cmd, ["--version"], { windowsHide: true }).status === 0,
);
test(
  "provider transport validates context, standard protocol, errors and credentials with mocked HTTP",
  { skip: !python },
  () => {
    const result = spawnSync(
      python,
      ["-m", "unittest", "discover", "-s", "tests", "-p", "test_llm_chat.py"],
      { encoding: "utf8", windowsHide: true },
    );
    assert.equal(result.status, 0, result.stderr);
  },
);
