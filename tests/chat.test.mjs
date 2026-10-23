import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { createChatSession } from "../src/voice/chat.js";
import { decide, conversationText } from "../src/app/dialogue.js";
import { sourceEntries } from "../src/app/web-sources.js";
const ok = (body, status = 200) => new Response(JSON.stringify(body), { status });
/** The reply as /chat/stream sends it: delta lines, then one done line. */
const streamed = (reply, extra = {}) =>
  new Response(
    [
      ...Array.from(reply.matchAll(/[^。！？]+[。！？]?/g), ([text]) => ({ type: "delta", text })),
      { type: "done", reply, ...extra },
    ]
      .map((event) => JSON.stringify(event) + "\n")
      .join(""),
    { status: 200, headers: { "Content-Type": "application/x-ndjson; charset=utf-8" } },
  );
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
      return streamed("自然语言回答", { model: "test-model", configuration: config });
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
    "小和，搜索今天的新闻",
    "小和，联网搜索人工智能最新消息",
    "读取网页 https://example.com/article",
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
test("mentioning an installed title in discussion or writing cannot trigger shelf lookup", () => {
  const installed = { title: "三体", localBookId: "real-book", bookId: "HX-02273" };
  const ctx = {
    phase: "IDLE",
    direct: true,
    fullText: true,
    understand: true,
    lookup: () => installed,
  };
  for (const text of [
    "小和，请总结《三体》",
    "帮我写一篇三体读后感",
    "介绍一下三体",
    "推荐一本科幻小说",
    "三体和其他小说比较一下",
  ])
    assert.equal(decide(text, ctx).type, "chat", text);
  assert.equal(decide("小和，帮我找《三体》", ctx).type, "present");
  assert.equal(decide("帮我搜索《新闻写作》", ctx).type, "present");
  assert.equal(decide("三体", ctx).type, "present");
  assert.equal(decide("小和，请总结这本书", { ...ctx, phase: "READING" }).type, "chat");
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
    url === "/chat/stream"
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
test("web questions bypass shelf lookup and sources reject executable URLs", () => {
  const ctx = {
    phase: "IDLE",
    direct: true,
    understand: true,
    lookup: () => {
      throw Error("unexpected shelf lookup");
    },
  };
  for (const text of ["联网搜索三体", "搜索今天的新闻", "读取网页 https://example.com"])
    assert.equal(decide(text, ctx).type, "chat");
  const entries = sourceEntries([
    { title: "<script>not HTML</script>", url: "https://example.com/article", id: 1 },
    { url: "javascript:alert(1)" },
    { url: "data:text/html,bad" },
    { url: "https://name:password@example.com" },
    { url: "not a URL" },
    null,
  ]);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].title, "<script>not HTML</script>");
  assert.equal(entries[0].url, "https://example.com/article");
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

test("talking about finding books is conversation; only a named book opens the reading library", async () => {
  const { namesABook, NAME_A_BOOK } = await import("../src/app/dialogue.js");
  const general = [
    "你能帮我找书吗？",
    "小和，怎么找书",
    "帮我找几本科幻小说",
    "我想找本小说",
    "帮我找书",
    "书在哪里",
    "帮我找一本好看的书",
    "你可以帮我下载书吗",
    "找书有什么技巧",
  ];
  const named = [
    "帮我找三体",
    "你能帮我找三体吗",
    "帮我找《不存在的书》",
    "霍金写的那本",
    "HX-03408",
  ];
  const withModel = {
    direct: true,
    phase: "IDLE",
    fullText: true,
    understand: true,
    lookup: () => null,
  };
  const offline = { ...withModel, understand: false };
  for (const text of general) {
    assert.equal(namesABook(text.replace(/^小和，/, "").replace(/[？?]/g, "")), false, text);
    assert.equal(decide(text, withModel).type, "chat", text);
    const hint = decide(text, offline);
    assert.deepEqual([hint.type, hint.speech], ["reply", NAME_A_BOOK], text);
  }
  for (const text of named) {
    assert.equal(decide(text, withModel).type, "model", text);
    assert.equal(decide(text, offline).type, "full-text", text);
  }
});
