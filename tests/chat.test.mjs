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
  const compacts = [];
  let config = "one",
    mode = "ok",
    folding = "ok";
  return {
    calls,
    compacts,
    setConfig: (value) => (config = value),
    setMode: (value) => (mode = value),
    setFolding: (value) => (folding = value),
    request: async (url, options) => {
      if (url.endsWith("ready")) return ok({ ready: true, configuration: config });
      if (url.endsWith("compact")) {
        const body = JSON.parse(options.body);
        compacts.push(body);
        if (folding === "error") return ok({ error: "模型服务返回 401" }, 502);
        return ok({ digest: `摘要${compacts.length}` });
      }
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
  // Past six turns the oldest are folded into a digest and three stay word for word.
  assert.equal(session.getState().turns, 3);
  assert.equal(backend.calls.at(-1).history.length, 12, "never more than the server accepts");
  backend.setConfig("other-provider");
  await session.ask("换模型", "IDLE");
  assert.deepEqual(backend.calls.at(-1).history, []);
  assert.ok(!("digest" in backend.calls.at(-1)), "a new provider starts without the old digest");
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

test("only an explicit 「记住……」 stores a memory, in any phase, and moves nothing", async () => {
  const { rememberedFact } = await import("../src/app/dialogue.js");
  const ctx = { direct: true, phase: "IDLE", understand: true, lookup: () => null };
  for (const [text, fact] of [
    ["小和，记住我喜欢科幻小说。", "我喜欢科幻小说"],
    ["请帮我记一下：我周末才有空读书", "我周末才有空读书"],
    ["别忘了我对推理小说不感兴趣", "我对推理小说不感兴趣"],
  ]) {
    assert.equal(rememberedFact(text), fact, text);
    for (const phase of ["IDLE", "READING", "NAVIGATING"])
      assert.deepEqual(
        [decide(text, { ...ctx, phase }).type, decide(text, { ...ctx, phase }).fact],
        ["remember", fact],
      );
  }
  for (const text of ["记住", "你还记得我喜欢什么吗？", "我记得这本书", "帮我找三体"])
    assert.notEqual(decide(text, ctx).type, "remember", text);
});

test("the session counts every finished turn so a summary takes only the new ones", async () => {
  const backend = service();
  const session = createChatSession(backend);
  await session.ask("第一问", "IDLE");
  await session.ask("第二问", "IDLE");
  const { busy, turns, total } = session.getState();
  assert.deepEqual({ busy, turns, total }, { busy: false, turns: 2, total: 2 });
  assert.deepEqual(session.recent(1), [
    { role: "user", content: "第二问" },
    { role: "assistant", content: "自然语言回答" },
  ]);
  for (let i = 0; i < 8; i++) await session.ask(`问题${i}`, "IDLE");
  assert.equal(session.getState().turns, 6, "context stays bounded");
  assert.equal(session.getState().total, 10, "but the count keeps going");
});

test("several equally good books are offered for choosing, then picked by number, title or author", async () => {
  const { pickChoice, choiceSpeech, MAX_CHOICES } = await import("../src/app/dialogue.js");
  const { findBooks } = await import("../src/voice/intent.js");
  const shelf = [
    { bookId: "HX-1", title: "三体Ⅱ·黑暗森林", author: "刘慈欣", keys: [], localBookId: "a" },
    { bookId: "HX-2", title: "三体Ⅲ·死神永生", author: "刘慈欣", keys: [], localBookId: "b" },
    { bookId: "HX-3", title: "红楼梦", author: "曹雪芹", keys: [], localBookId: "c" },
    { bookId: "HX-4", title: "红楼梦", author: "脂砚斋评", keys: [], localBookId: "d" },
    { bookId: "HX-5", title: "三体", author: "刘慈欣", keys: [], localBookId: "e" },
  ];
  // An exact title still wins outright; only a true tie is ambiguous.
  assert.deepEqual(
    findBooks("三体", shelf).map((b) => b.bookId),
    ["HX-5"],
  );
  assert.deepEqual(
    findBooks("红楼梦", shelf).map((b) => b.bookId),
    ["HX-3", "HX-4"],
  );
  const noExact = shelf.filter((b) => b.bookId !== "HX-5");
  const tied = findBooks("三体", noExact);
  assert.deepEqual(
    tied.map((b) => b.bookId),
    ["HX-1", "HX-2"],
  );

  const ctx = { direct: true, phase: "IDLE", understand: true, lookup: () => tied };
  const asked = decide("帮我找三体", ctx);
  assert.equal(asked.type, "choose");
  assert.deepEqual(asked.books, tied);
  const many = Array.from({ length: 6 }, (_, i) => ({ ...tied[0], bookId: `X${i}` }));
  assert.equal(decide("帮我找三体", { ...ctx, lookup: () => many }).books.length, MAX_CHOICES);
  assert.equal(decide("帮我找三体", { ...ctx, lookup: () => [tied[0]] }).type, "present");

  const speech = choiceSpeech(tied);
  assert.match(speech, /第一本《三体Ⅱ·黑暗森林》（刘慈欣），第二本《三体Ⅲ·死神永生》/);
  for (const [answer, id] of [
    ["第一本", "HX-1"],
    ["小和，第二个", "HX-2"],
    ["2", "HX-2"],
    ["最后那本", "HX-2"],
    ["要死神永生", "HX-2"],
    ["黑暗森林", "HX-1"],
  ])
    assert.equal(pickChoice(answer, tied)?.bookId, id, answer);
  const editions = findBooks("红楼梦", shelf);
  assert.equal(pickChoice("脂砚斋评的那本", editions)?.bookId, "HX-4");
  for (const answer of ["第五本", "随便", "刘慈欣", "帮我找时间简史"])
    assert.equal(pickChoice(answer, tied), null, answer);
});

test("a question about 「this page」 while reading carries the page, and only then", async () => {
  const { asksAboutPage } = await import("../src/app/dialogue.js");
  for (const text of [
    "这段什么意思",
    "这里看不懂",
    "解释一下",
    "上面这句是什么意思",
    "刚才那段讲了啥",
  ])
    assert.ok(asksAboutPage(text), text);
  for (const text of ["叶文洁是谁", "下一页", "推荐一本书", ""])
    assert.ok(!asksAboutPage(text), text);
  const backend = service();
  const chat = createChatSession({ request: backend.request });
  await chat.ask("这段什么意思", "READING", "HX-00001", { page: "红岸基地的天线指向天空。" });
  await chat.ask("叶文洁是谁", "READING", "HX-00001");
  assert.equal(backend.calls[0].page, "红岸基地的天线指向天空。");
  assert.ok(!("page" in backend.calls[1]), "no page unless asked about it");
});

test("turns past the budget are folded into a running digest instead of forgotten", async () => {
  const backend = service();
  const session = createChatSession(backend);
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  for (let i = 1; i <= 6; i++) await session.ask(`第${i}问`, "IDLE");
  assert.equal(backend.compacts.length, 0, "within the budget nothing is compacted");
  await session.ask("第7问", "IDLE");
  assert.equal(backend.compacts.length, 1, "one call folds several turns at once");
  assert.deepEqual(
    backend.compacts[0].history
      .filter((entry) => entry.role === "user")
      .map((entry) => entry.content),
    ["第1问", "第2问", "第3问", "第4问"],
  );
  assert.equal(backend.compacts[0].digest, "");
  assert.equal(session.getState().turns, 3);
  await settle();
  assert.equal(session.getState().digest, "摘要1");
  await session.ask("第8问", "IDLE");
  assert.equal(backend.calls.at(-1).digest, "摘要1", "later questions carry the digest");
  for (let i = 9; i <= 11; i++) await session.ask(`第${i}问`, "IDLE");
  await settle();
  assert.equal(backend.compacts.length, 2);
  assert.equal(backend.compacts[1].digest, "摘要1", "the old digest is merged, not replaced");
  backend.setFolding("error");
  for (let i = 12; i <= 15; i++) await session.ask(`第${i}问`, "IDLE");
  await settle();
  assert.equal(backend.compacts.length, 3, "the fold was attempted");
  assert.equal(session.getState().digest, "摘要2", "a failed fold keeps the last digest");
  assert.equal(session.getState().turns, 3, "and the conversation carries on");
  session.clear();
  assert.equal(session.getState().digest, "");
});
