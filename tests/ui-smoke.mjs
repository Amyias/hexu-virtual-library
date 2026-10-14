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
  await waitFor(async () => {
    targets = await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json();
    return targets.some((target) => target.type === "page");
  }, "浏览器调试端口", 20_000);
  const socket = new WebSocket(targets.find((target) => target.type === "page").webSocketDebuggerUrl);
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
    const reply = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
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
  env: { ...process.env, PORT: String(sitePort) },
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
  console.log(`✔ ${name}${detail ? "  " + detail : ""}  (${Math.round((Date.now() - started) / 1000)} s)`);

try {
  await waitFor(async () => (await fetch(`http://127.0.0.1:${sitePort}/`)).ok, "静态服务启动", 20_000);
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
    async () => (await page.evaluate("getComputedStyle(document.getElementById('loading')).display")) === "none" && (await state()),
    "场景加载",
  );
  // Test-only: at software-rendered frame rates GSAP would otherwise stretch every tween, a
  // three-second walk becoming many minutes. With lag smoothing off, animations keep wall time.
  await page.evaluate("gsap.ticker.lagSmoothing(0)");
  const loaded = await state();
  if (!loaded.modelLoaded || loaded.interactiveBooks < 10000) throw new Error(`场景不完整：${JSON.stringify(loaded)}`);
  step("加载场景", `${loaded.interactiveBooks} 本书`);

  if ((await search("HX-09881")) !== "NAVIGATE_TO_BOOK") throw new Error("按编号找书没有发出导航");
  await waitFor(phaseIs("READING"), "取书并进入阅读");
  const location = await text("bookLocation");
  if (!location.startsWith("HX-09881 /")) throw new Error(`取到的不是 HX-09881：${location}`);
  step("找书", location);

  await click("openBook");
  await waitFor(async () => (await state()).turn > 0.99, "翻开封面");
  step("翻开封面");

  await click("inspectChip");
  await waitFor(async () => (await text("chipId")) === "HX-09881", "芯片特写显示编号");
  step("查看芯片", `${await text("chipId")} · ${(await text("chipLocation")).split(" · ")[0]}`);
  await click("closeChip");

  await click("returnBook");
  await waitFor(phaseIs("IDLE"), "放回书架并回到待命");
  const idle = await state();
  if (idle.book || idle.music?.active) throw new Error(`回到待命后仍有残留：${JSON.stringify({ book: idle.book, music: idle.music })}`);
  step("放回书架 → 回到待命", "音乐已停");

  if ((await search("S5-B-L4-P284")) !== "NAVIGATE_TO_BOOK") throw new Error("按位置码找书没有发出导航");
  await waitFor(phaseIs("READING"), "再次取书");
  const second = await text("bookLocation");
  if (!second.startsWith("HX-11360 /")) throw new Error(`位置码 S5-B-L4-P284 应是 HX-11360：${second}`);
  step("按位置码再找一本", second);
  await click("returnBook");
  await waitFor(phaseIs("IDLE"), "第二本放回");
  step("第二本放回");

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
  browser.kill();
  site.kill();
  await sleep(500); // let the browser release its profile before it is removed
  fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
process.exit(failed ? 1 : 0);
