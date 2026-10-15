/* Browser smoke test for the whole reading loop: load the scene → find a book → open the cover →
   inspect the chip → put it back → idle → find another one by its position code.

   Run with `npm run test:ui`. It is not part of `npm test`: it needs a local Chrome or Edge and
   takes a few minutes, because headless Chrome renders WebGL in software here (well under one
   frame a second). Nothing to install — it drives the browser over the DevTools protocol with
   Node's own WebSocket (Node 22 or later), against the same static server `npm start` uses.

   Set CHROME_PATH to pick a browser. On failure a screenshot of the page is left in the system
   temp directory and its path is printed. */
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const STEP_TIMEOUT = 180_000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function findBrowser() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate));
}

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = http.createServer().listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
    probe.on("error", reject);
  });
}

async function waitFor(check, what, timeout = STEP_TIMEOUT) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    try {
      if (await check()) return;
    } catch {
      /* not ready yet */
    }
    await sleep(300);
  }
  throw new Error(`超时：${what}（${Math.round(timeout / 1000)} 秒）`);
}

/** A minimal DevTools client: one page, Runtime.evaluate, and the page's own errors. */
async function connect(debugPort) {
  let targets;
  await waitFor(
    async () => {
      targets = await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json();
      return targets.some((target) => target.type === "page");
    },
    "浏览器调试端口",
    20_000,
  );
  const socket = new WebSocket(
    targets.find((target) => target.type === "page").webSocketDebuggerUrl,
  );
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  let id = 0;
  const pending = new Map();
  const errors = [];
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Runtime.exceptionThrown") {
      const detail = message.params.exceptionDetails;
      errors.push(detail.exception?.description ?? detail.text);
    } else if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      errors.push(message.params.args.map((arg) => arg.value ?? arg.description).join(" "));
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const n = ++id;
      pending.set(n, resolve);
      socket.send(JSON.stringify({ id: n, method, params }));
    });
  const evaluate = async (expression) => {
    const reply = await send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (reply.result?.exceptionDetails) throw new Error(reply.result.exceptionDetails.text);
    return reply.result?.result?.value;
  };
  await send("Runtime.enable");
  await send("Page.enable");
  return { send, evaluate, errors, close: () => socket.close() };
}

const browserPath = findBrowser();
if (!browserPath) {
  console.error("找不到 Chrome 或 Edge。请设置 CHROME_PATH 指向浏览器可执行文件。");
  process.exit(1);
}
if (typeof WebSocket !== "function") {
  console.error(`界面冒烟测试需要 Node 22 或更高版本（当前 ${process.version}）。`);
  process.exit(1);
}

const sitePort = await freePort();
const debugPort = await freePort();
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "hexu-ui-"));
const site = spawn(process.execPath, [path.join(root, "tools", "serve.mjs")], {
  cwd: root,
  env: {
    ...process.env,
    PORT: String(sitePort),
    HEXU_BOOK_LIBRARY_DIR: path.join(profile, "books"),
  },
  stdio: "ignore",
});
const browser = spawn(
  browserPath,
  [
    "--headless=new",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${profile}`,
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--autoplay-policy=no-user-gesture-required",
    "--window-size=1280,820",
    "about:blank",
  ],
  { stdio: "ignore" },
);

let page;
let failed = false;
const started = Date.now();
const step = (name, detail = "") =>
  console.log(
    `✔ ${name}${detail ? "  " + detail : ""}  (${Math.round((Date.now() - started) / 1000)} s)`,
  );

try {
  await waitFor(
    async () => (await fetch(`http://127.0.0.1:${sitePort}/`)).ok,
    "静态服务启动",
    20_000,
  );
  page = await connect(debugPort);
  const state = () => page.evaluate("window.libraryDebug && window.libraryDebug.getState()");
  const phaseIs = (phase) => async () => (await state())?.phase === phase;
  const search = (text) =>
    page.evaluate(`(() => {
      const q = document.getElementById('query');
      q.value = ${JSON.stringify(text)};
      q.closest('form').requestSubmit();
      return JSON.parse(document.getElementById('protocol').textContent).action;
    })()`);
  const text = (id) => page.evaluate(`document.getElementById(${JSON.stringify(id)}).textContent`);
  const click = (id) => page.evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);

  await page.send("Page.navigate", { url: `http://127.0.0.1:${sitePort}/` });
  await waitFor(
    async () =>
      (await page.evaluate("getComputedStyle(document.getElementById('loading')).display")) ===
        "none" && (await state()),
    "场景加载",
  );
  // Test-only: at software-rendered frame rates GSAP would otherwise stretch every tween, a
  // three-second walk becoming many minutes. With lag smoothing off, animations keep wall time.
  await page.evaluate("gsap.ticker.lagSmoothing(0)");
  const loaded = await state();
  if (
    !loaded.modelLoaded ||
    loaded.shelfCapacity !== 11360 ||
    loaded.interactiveBooks !== 0 ||
    loaded.visibleShelfBooks !== 0
  )
    throw new Error(`场景不完整：${JSON.stringify(loaded)}`);
  step("加载场景", `${loaded.shelfCapacity} 个空槽位，0 本预置书`);
  if (
    !loaded.companion?.loaded ||
    loaded.companion.source !== "blender" ||
    loaded.companion.legs !== 4 ||
    loaded.companion.eyes !== 2
  )
    throw new Error("Blender 小和宠物未完整加载");
  const home = loaded.orb;
  await page.evaluate("window.libraryDebug.processText('小和')");
  const wakeState = await state();
  const protocol = JSON.parse(await text("protocol"));
  if (
    wakeState.phase !== "IDLE" ||
    JSON.stringify(wakeState.orb) !== JSON.stringify(home) ||
    protocol.speech !== "有什么需求吗？" ||
    !protocol.is_wake_only
  )
    throw new Error("仅唤醒时宠物错误位移或响应不符");
  step("宠物加载与仅唤醒", "四条腿、两只眼睛；锚点保持前台");

  if (await page.evaluate("document.querySelectorAll('[data-query], .suggestions, .chip').length"))
    throw new Error("预置推荐入口仍然存在");
  await waitFor(async () => (await state()).localLibrary.ready, "连接空书库");
  const imports = await page.evaluate(`(async () => {
    const saved = [];
    for (const [title, content] of [["回归阅读甲", "这是第一页的本地正文。".repeat(1500)], ["回归阅读乙", "另一册真实正文。".repeat(300)]]) {
      const bytes = new TextEncoder().encode(content);
      const data = btoa(String.fromCharCode(...bytes));
      const response = await fetch('/library/import', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({filename:title+'.txt', data}) });
      if (!response.ok) throw Error('TXT 导入失败');
      saved.push(await response.json());
    }
    document.getElementById('libraryButton').click();
    return saved;
  })()`);
  await waitFor(
    async () => (await state()).interactiveBooks === 2 && (await state()).visibleShelfBooks === 2,
    "真实书籍上架",
  );
  await click("closeLibrary");
  const bound = await page.evaluate("window.libraryDebug.books");
  const firstBook = bound.find((b) => b.localBookId === imports[0].id);
  const secondBook = bound.find((b) => b.localBookId === imports[1].id);
  if (!firstBook || !secondBook) throw new Error("导入书籍未绑定真实槽位");
  step("导入两册真实 TXT", `${firstBook.bookId} / ${secondBook.bookId}`);
  if ((await search(firstBook.bookId)) !== "NAVIGATE_TO_BOOK")
    throw new Error("按编号找书没有发出导航");
  await waitFor(phaseIs("READING"), "取书并进入阅读");
  const location = await text("bookLocation");
  if (!location.startsWith(firstBook.bookId + " /"))
    throw new Error(`取到的不是已导入书籍：${location}`);
  step("找书", location);

  await click("openBook");
  await waitFor(async () => (await state()).turn > 0.99, "翻开封面");
  step("翻开封面");
  await waitFor(async () => (await state()).novel.visible, "显示真实正文");
  if (!(await text("novelText")).includes("这是第一页的本地正文"))
    throw new Error("没有显示导入正文");
  await click("nextPage");
  await waitFor(async () => (await state()).novel.offset > 0, "正文翻到下一页");
  step("正文翻页");
  await click("closeNovel");

  await click("inspectChip");
  await waitFor(async () => (await text("chipId")) === firstBook.bookId, "芯片特写显示编号");
  step("查看芯片", `${await text("chipId")} · ${(await text("chipLocation")).split(" · ")[0]}`);
  await click("closeChip");

  await click("returnBook");
  await waitFor(phaseIs("IDLE"), "放回书架并回到待命");
  const idle = await state();
  if (idle.book || idle.music?.active)
    throw new Error(
      `回到待命后仍有残留：${JSON.stringify({ book: idle.book, music: idle.music })}`,
    );
  step("放回书架 → 回到待命", "音乐已停");

  if ((await search(secondBook.locationCode)) !== "NAVIGATE_TO_BOOK")
    throw new Error("按位置码找书没有发出导航");
  await waitFor(phaseIs("READING"), "再次取书");
  const second = await text("bookLocation");
  if (!second.startsWith(secondBook.bookId + " /"))
    throw new Error(`位置码取到错误书籍：${second}`);
  step("按位置码再找一本", second);
  await click("returnBook");
  await waitFor(phaseIs("IDLE"), "第二本放回");
  step("第二本放回");
  await page.send("Page.reload");
  await waitFor(
    async () =>
      (await state())?.localLibrary.count === 2 && (await state()).visibleShelfBooks === 2,
    "重载后恢复真实书籍",
  );
  const rebound = await page.evaluate(
    "window.libraryDebug.books.map(b => [b.localBookId, b.bookId])",
  );
  if (JSON.stringify(rebound) !== JSON.stringify(bound.map((b) => [b.localBookId, b.bookId])))
    throw new Error("重新加载后真实书籍的位置发生变化");
  step("重载后保留书籍与编号");

  if (page.errors.length) throw new Error("页面报错：\n  " + page.errors.join("\n  "));
  console.log(`\n界面冒烟测试通过（${Math.round((Date.now() - started) / 1000)} 秒）`);
} catch (error) {
  failed = true;
  console.error(`\n✖ ${error.message}`);
  if (page) {
    try {
      const shot = await page.send("Page.captureScreenshot", { format: "png" });
      const file = path.join(os.tmpdir(), `hexu-ui-failure-${Date.now()}.png`);
      fs.writeFileSync(file, Buffer.from(shot.result.data, "base64"));
      console.error(`  失败时的页面截图：${file}`);
      if (page.errors.length) console.error("  页面报错：\n    " + page.errors.join("\n    "));
    } catch {
      /* the page may already be gone */
    }
  }
} finally {
  page?.close();
  site.kill();
  // Chrome's helper processes keep files in the profile open for a moment after the main one is
  // killed, so wait for it to exit and then retry. A profile that still cannot be removed is a
  // leftover in the temp directory, not a failed test.
  const exited = new Promise((resolve) => browser.once("exit", resolve));
  browser.kill();
  await Promise.race([exited, sleep(5000)]);
  try {
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 250 });
  } catch {
    console.warn(`（临时浏览器配置未能删除，可手动清理：${profile}）`);
  }
}
process.exit(failed ? 1 : 0);
