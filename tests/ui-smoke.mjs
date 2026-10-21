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
    ...Object.fromEntries(
      Object.entries(process.env).filter(([name]) => !/^HEXU_(LLM|WEB)_/.test(name)),
    ),
    APPDATA: profile,
    XDG_CONFIG_HOME: profile,
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
      const panel = document.getElementById('conversation');
      if (panel.hidden) document.getElementById('chatButton').click();
      const q = panel.querySelector('textarea');
      q.value = ${JSON.stringify(text)};
      q.closest('form').requestSubmit();
      panel.querySelector('[data-close]').click();
      return window.lastProtocol.action;
    })()`);
  const text = (id) => page.evaluate(`document.getElementById(${JSON.stringify(id)}).textContent`);
  const click = (id) => page.evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);

  await page.send("Page.navigate", {
    url: `http://127.0.0.1:${sitePort}/tests/fixtures/music-glass.html`,
  });
  await waitFor(() => page.evaluate("Boolean(window.musicFixture)"), "液态玻璃播放器加载");
  await click("start");
  await waitFor(
    () => page.evaluate("Boolean(document.getElementById('readingMusic').dataset.glassSize)"),
    "生成圆角折射贴图",
  );
  const compactGlass = await page.evaluate(`(()=>{
    const p=document.getElementById('readingMusic');const r=p.getBoundingClientRect();
    return {size:p.dataset.glassSize,width:r.width,height:r.height,filter:getComputedStyle(p,'::before').backdropFilter,src:document.getElementById('readingAudio').getAttribute('src')};
  })()`);
  if (!compactGlass.filter.includes("url(") || !compactGlass.filter.includes("blur("))
    throw Error("播放器缺少真实背景折射滤镜");
  await click("docked");
  await waitFor(
    () =>
      page.evaluate(
        `document.getElementById('readingMusic').dataset.glassSize !== ${JSON.stringify(compactGlass.size)}`,
      ),
    "阅读条重新生成正确比例的折射贴图",
  );
  if (
    !(await page.evaluate(
      `document.querySelector('#dock #readingMusic') && document.getElementById('readingAudio').getAttribute('src')===${JSON.stringify(compactGlass.src)}`,
    ))
  )
    throw Error("切换阅读条丢失音轨或播放器");
  await click("musicNext");
  if (!(await text("musicTitle")).includes("The Trek")) throw Error("玻璃按钮无法切歌");
  await page.evaluate(
    "document.getElementById('musicVolume').value=35; document.getElementById('musicVolume').dispatchEvent(new Event('input'))",
  );
  if ((await page.evaluate("musicFixture.getState().volume")) !== 0.35)
    throw Error("玻璃音量控件不可用");
  await page.send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await waitFor(
    () =>
      page.evaluate("document.getElementById('readingMusic').getBoundingClientRect().width < 390"),
    "窄屏播放器保持可见",
  );
  await click("compact");
  if (
    !(await page.evaluate(
      "document.getElementById('readingMusic').getBoundingClientRect().right <= innerWidth",
    ))
  )
    throw Error("悬浮播放器超出窄屏");
  await click("stop");
  if (
    !(await page.evaluate(
      "document.getElementById('readingMusic').hidden && !musicFixture.getState().active",
    ))
  )
    throw Error("停止后玻璃播放器仍显示");
  await page.send("Emulation.clearDeviceMetricsOverride");
  step("液态玻璃播放器", "背景折射、两种布局自适应、窄屏、切歌、音量和停止通过");

  await page.send("Page.navigate", {
    url: `http://127.0.0.1:${sitePort}/tests/fixtures/window-chrome.html`,
  });
  await waitFor(
    () =>
      page.evaluate(
        "document.querySelector('.desktop-titlebar') && getComputedStyle(document.querySelector('.desktop-titlebar')).backdropFilter.includes('blur')",
      ),
    "玻璃标题栏加载",
  );
  if (
    await page.evaluate(
      "document.querySelectorAll('.desktop-titlebar').length !== 1 || document.querySelectorAll('.window-resize-edge').length !== 8",
    )
  )
    throw new Error("标题栏重复或缺少调整大小边缘");
  await page.evaluate("document.querySelector('[data-window-action=maximize]').click()");
  await waitFor(
    () =>
      page.evaluate(
        "document.documentElement.classList.contains('window-maximized') && document.querySelector('[data-window-action=maximize]').getAttribute('aria-label') === '还原窗口'",
      ),
    "标题栏最大化状态",
  );
  await page.evaluate("document.querySelector('[data-window-action=maximize]').click()");
  await waitFor(
    () => page.evaluate("!document.documentElement.classList.contains('window-maximized')"),
    "标题栏还原状态",
  );
  for (const command of ["minimize", "close"]) {
    await page.evaluate(`document.querySelector('[data-window-action=${command}]').click()`);
    await waitFor(
      () => page.evaluate(`chromeFixture.calls.includes('${command}')`),
      `标题栏 ${command}`,
    );
  }
  step("液态玻璃标题栏", "背景滤镜、单实例、最大化／还原及窗口按钮通过；原生窗口另行实测");

  // Test typewriter timing without a software-WebGL frame blocking every timer callback.
  await page.send("Page.navigate", {
    url: `http://127.0.0.1:${sitePort}/tests/fixtures/pixel-dialogue.html`,
  });
  await waitFor(() => page.evaluate("Boolean(window.pixelFixture)"), "像素反馈模块加载");
  if ((await page.evaluate("pixelFixture.feedback.getState().sound.state")) !== "locked")
    throw new Error("音效在用户操作前创建了 AudioContext");
  const font = await page.evaluate(`(async () => {
    await document.fonts.load('24px "Fusion Pixel"', '有什么需求吗？');
    return [...document.fonts].some(font => font.family === 'Fusion Pixel' && font.status === 'loaded');
  })()`);
  if (!font) throw new Error("离线中文像素字体加载失败");
  const replyRect = await page.evaluate(
    "(() => { const r=document.getElementById('testReply').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()",
  );
  for (const type of ["mousePressed", "mouseReleased"])
    await page.send("Input.dispatchMouseEvent", {
      type,
      ...replyRect,
      button: "left",
      clickCount: 1,
    });
  const prefixes = new Set();
  const typingStarted = Date.now();
  while (Date.now() - typingStarted < 2000) {
    const reply = await page.evaluate(
      "({text:document.getElementById('bubbleText').textContent,state:pixelFixture.feedback.getState()})",
    );
    prefixes.add(reply.text);
    if (!reply.state.typing && reply.text === "有什么需求吗？") break;
    await sleep(15);
  }
  const replyState = await page.evaluate("pixelFixture.feedback.getState()");
  if (
    prefixes.size < 3 ||
    replyState.typing ||
    replyState.sound.state !== "running" ||
    !replyState.sound.pops ||
    !replyState.sound.ticks
  )
    throw new Error(`逐字回应或声音未完成：${JSON.stringify(replyState)} / ${prefixes.size}`);
  await page.evaluate("pixelFixture.feedback.bubble('上一段未完成的长回复',0)");
  await sleep(90);
  await page.evaluate("pixelFixture.feedback.bubble('新的回复',0)");
  await waitFor(async () => (await text("bubbleText")) === "新的回复", "新回复替换旧文本");
  await page.evaluate("pixelFixture.feedback.toggleSounds()");
  const muted = await page.evaluate("pixelFixture.feedback.getState().sound");
  await page.evaluate("pixelFixture.feedback.bubble('静音仍然逐字显示',0)");
  await waitFor(
    async () => !(await page.evaluate("pixelFixture.feedback.getState().typing")),
    "静音文字完成",
  );
  const afterMute = await page.evaluate("pixelFixture.feedback.getState().sound");
  if (afterMute.enabled || afterMute.pops !== muted.pops || afterMute.ticks !== muted.ticks)
    throw new Error("静音后仍播放了音效");
  await page.evaluate("pixelFixture.feedback.toggleSounds()");
  const waveform = await page.evaluate(`(async () => {
    const offline = new OfflineAudioContext(1, 26460, 44100);
    let time=0;
    class Context {
      constructor(){this.destination=offline.destination;this.state='running';}
      get currentTime(){return time;}
      createGain(){return offline.createGain();}
      createOscillator(){return offline.createOscillator();}
      createBiquadFilter(){return offline.createBiquadFilter();}
    }
    const sounds=pixelFixture.createDialogueSounds({host:{AudioContext:Context},storage:{getItem:()=>null}});
    await sounds.unlock();sounds.pop();time=.2;sounds.type('你',1);time=.28;sounds.type('好',2);
    const samples=(await offline.startRendering()).getChannelData(0);
    const peak=(a,b)=>Math.max(...samples.slice(Math.floor(a*44100),Math.floor(b*44100)).map(Math.abs));
    return {pop:peak(0,.14),type:peak(.2,.24),silence:peak(.4,.59),max:peak(0,.59)};
  })()`);
  if (
    waveform.pop < 0.01 ||
    waveform.type < 0.005 ||
    waveform.max > 0.2 ||
    waveform.silence > 0.00001
  )
    throw new Error(`合成音效波形异常：${JSON.stringify(waveform)}`);
  step("像素气泡与逐字音效", `${prefixes.size} 个可见文字阶段；字体加载、静音与声音波形通过`);

  const longBubble = await page.evaluate(`(() => {
    const value='这是完整的长回答，所有内容都应保留在像素气泡里。'.repeat(80)+'终点标记';
    pixelFixture.feedback.say(value,0,{interactive:true});
    document.querySelector('#bubble [data-bubble-finish]').click();
    const copy=document.querySelector('#bubble .bubble-copy');
    copy.scrollTop=copy.scrollHeight;
    document.body.classList.add('reading','novel-reading');
    return {value,shown:document.getElementById('bubbleText').textContent,
      scrollable:copy.scrollHeight>copy.clientHeight,scrolled:copy.scrollTop>0,
      display:getComputedStyle(document.getElementById('bubble')).display,
      persistent:pixelFixture.feedback.getState().persistent};
  })()`);
  if (
    longBubble.shown !== longBubble.value ||
    !longBubble.scrollable ||
    !longBubble.scrolled ||
    longBubble.display === "none" ||
    !longBubble.persistent
  )
    throw new Error("长回答气泡未完整显示或阅读模式隐藏了气泡");
  await page.evaluate("document.querySelector('#bubble [data-bubble-close]').click()");
  if (await page.evaluate("pixelFixture.feedback.getState().visible"))
    throw new Error("气泡收起失败");
  step("完整回答气泡", "长文本不截断、可滚动、显示全文、收起及阅读模式显示通过");

  // Settings use the same local backend in an iframe, never a new browser page.
  const originalUrl = await page.evaluate("location.href");
  const originalPages = (await page.send("Target.getTargets")).result.targetInfos.filter(
    (target) => target.type === "page",
  ).length;
  await page.evaluate(`(async () => {
    const {createSettingsPanel}=await import('/src/app/settings.js');
    const {createConversation}=await import('/src/app/conversation.js');
    window.settingsFixture={closed:0};
    settingsFixture.panel=createSettingsPanel({onClose:()=>settingsFixture.closed++});
    settingsFixture.conversation=createConversation({onSubmit:()=>{},onCancel:()=>{},onClear:()=>{}});
    settingsFixture.conversation.begin('保留本轮对话');
    settingsFixture.conversation.answer('设置关闭后这条记录仍然存在。','fixture-model');
    settingsFixture.conversation.show();
    document.querySelector('#conversation a[href="/settings"]').click();
  })()`);
  await waitFor(
    () =>
      page.evaluate(
        "document.querySelector('#internalSettings iframe')?.contentDocument?.getElementById('model')?.value === 'deepseek-flash'",
      ),
    "程序内加载模型设置",
  );
  if (
    (await page.evaluate("location.href")) !== originalUrl ||
    !(await page.evaluate("settingsFixture.panel.opened"))
  )
    throw new Error("设置错误跳转了主页面");
  if (
    (await page.send("Target.getTargets")).result.targetInfos.filter(
      (target) => target.type === "page",
    ).length !== originalPages
  )
    throw new Error("设置打开了额外浏览器页面");
  // Only the isolated test profile is written; there is no API key and no provider call.
  await page.evaluate(`(() => {
    const doc=document.querySelector('#internalSettings iframe').contentDocument;
    doc.getElementById('model').value='settings-ui-regression';
    doc.getElementById('save').click();
  })()`);
  await waitFor(
    () =>
      page.evaluate(
        "document.querySelector('#internalSettings iframe')?.contentDocument?.getElementById('message')?.textContent.includes('已保存')",
      ),
    "内部设置保存",
  );
  await page.evaluate(
    "document.querySelector('#internalSettings iframe').contentDocument.getElementById('settingsBack').click()",
  );
  await waitFor(
    () => page.evaluate("settingsFixture.closed===1 && !settingsFixture.panel.opened"),
    "设置返回当前图书馆",
  );
  if (
    (await page.evaluate("settingsFixture.conversation.getState().messages")) !== 2 ||
    (await page.evaluate("document.querySelectorAll('#internalSettings iframe').length"))
  )
    throw new Error("关闭设置丢失对话或未卸载设置文档");
  await page.evaluate("document.querySelector('#conversation a[href=\"/settings\"]').click()");
  await waitFor(
    () =>
      page.evaluate(
        "document.querySelector('#internalSettings iframe')?.contentDocument?.getElementById('model')?.value === 'settings-ui-regression'",
      ),
    "重新打开保留配置",
  );
  await page.evaluate(`(() => {
    const frame=document.querySelector('#internalSettings iframe');
    frame.contentDocument.dispatchEvent(new frame.contentWindow.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  })()`);
  await waitFor(
    () => page.evaluate("settingsFixture.closed===2 && !settingsFixture.panel.opened"),
    "设置 Esc 关闭",
  );
  step("程序内模型设置", "不跳转、不新开页面；保存、返回、Esc 与对话保留通过");

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
    loaded.renderedShelfSlots !== 0 ||
    loaded.visibleShelfBooks !== 0
  )
    throw new Error(`场景不完整：${JSON.stringify(loaded)}`);
  step("加载场景", `${loaded.shelfCapacity} 个空槽位，0 本预置书`);
  if (
    loaded.lighting?.pendantLights !== 8 ||
    loaded.lighting.groundAoReceivers !== 1 ||
    loaded.lighting.groundAoResolution[0] !== 2048 ||
    !(loaded.lighting.underlayVertices > 0)
  )
    throw Error("灯光、接触遮蔽或地板暗色衬底未加载");
  if (loaded.sky?.night || !loaded.sky?.sunVisible || loaded.sky.moonVisible)
    throw Error(`默认应为白天且只显示像素太阳：${JSON.stringify(loaded.sky)}`);
  for (const night of [true, false]) {
    await click("sky");
    await waitFor(
      async () => {
        const { sky, lighting } = await state();
        const dark = await page.evaluate("document.body.classList.contains('night')");
        return (
          sky.night === night &&
          sky.blend === (night ? 1 : 0) &&
          sky.moonVisible === night &&
          sky.sunVisible === !night &&
          lighting.night === sky.blend &&
          dark === night
        );
      },
      night ? "切换到像素月亮" : "切换回像素太阳",
    );
  }
  step("日月切换", "像素太阳与月亮同处窗外光源方位；灯光、背景与文字配色随之切换");
  if (
    !(await page.evaluate(
      "Boolean(document.querySelector('.mark img')?.complete && document.querySelector('.mark img').naturalWidth > 0)",
    ))
  )
    throw Error("圆形标识中的小和图标未成功加载");
  if (
    await page.evaluate(
      "Boolean(document.querySelector('.collection, .shelf-link, .top-right, .help, #protocol, #voiceLog'))",
    )
  )
    throw Error("已删除的馆藏索引或说明面板仍然存在");
  if (
    !(await page.evaluate(
      "Boolean(document.querySelector('.mic-indicator #micStatus') && document.getElementById('micDot'))",
    ))
  )
    throw Error("清理右侧面板误删了麦克风状态指示器");
  await page.evaluate(
    "window.addEventListener('xiaohe-response', event => { window.lastProtocol = event.detail; })",
  );

  if (
    !loaded.companion?.loaded ||
    loaded.companion.source !== "blender" ||
    loaded.companion.legs !== 4 ||
    loaded.companion.eyes !== 2
  )
    throw new Error("Blender 小和宠物未完整加载");
  const home = loaded.orb;
  for (const type of ["mousePressed", "mouseReleased"])
    await page.send("Input.dispatchMouseEvent", {
      type,
      x: loaded.petScreen[0],
      y: loaded.petScreen[1],
      button: "left",
      clickCount: 1,
    });
  await waitFor(
    async () => (await state()).dialogue.message === "有什么需求吗？",
    "点击 Blender 小和回应",
  );
  const wakeState = await state();
  const protocol = await page.evaluate("window.lastProtocol");
  if (
    wakeState.phase !== "IDLE" ||
    JSON.stringify(wakeState.orb) !== JSON.stringify(home) ||
    protocol.speech !== "有什么需求吗？" ||
    !protocol.is_wake_only
  )
    throw new Error("仅唤醒时宠物错误位移或响应不符");
  step("宠物加载与仅唤醒", "四条腿、两只眼睛；锚点保持前台");

  // Isolated mocked provider response: speech uses the full bubble, never an automatic panel.
  await page.evaluate(`(() => {
    window.chatTest = { fetch: window.fetch.bind(window), calls: [], config: 'first' };
    window.fetch = async (url, options) => {
      if (url === '/chat/ready') return new Response(JSON.stringify({ready:true,configuration:chatTest.config}),{status:200});
      if (url === '/chat') {
        chatTest.calls.push(JSON.parse(options.body));
        return new Response(JSON.stringify({reply:'机器学习通过数据学习规律。'+ '这是完整回答。'.repeat(25) + '<img src=x onerror=alert(1)>',model:'mock-chat-model',configuration:chatTest.config,sources:[{id:1,title:'<img src=x onerror=alert(1)>参考资料',url:'https://example.com/evidence'},{url:'javascript:alert(1)'}]}),{status:200});
      }
      return chatTest.fetch(url,options);
    };
    libraryDebug.processText('小和，什么是机器学习？');
  })()`);
  await waitFor(
    async () => (await state()).chat.turns === 1 && !(await state()).chat.pending,
    "自由提问完成",
  );
  await page.evaluate("document.querySelector('#bubble [data-bubble-finish]').click()");
  const chatCheck = await page.evaluate(`({
    panelHidden:document.getElementById('conversation').hidden,
    visible:libraryDebug.getState().dialogue.visible,
    persistent:libraryDebug.getState().dialogue.persistent,
    answer:document.querySelector('.conversation-message.assistant div').textContent,
    injected:document.querySelectorAll('#conversation img, #bubble img').length,
    full:document.getElementById('bubbleText').textContent,
    speech:window.lastProtocol.speech,
    preview:libraryDebug.getState().dialogue.message,
    pet:libraryDebug.getState().petBounds,
    bubble:(()=>{const r=document.getElementById('bubble').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,height:r.height};})(),
    placement:libraryDebug.getState().dialoguePlacement,
    sourceCount:document.querySelectorAll('#bubble .web-sources a').length,
    sourceUrl:document.querySelector('#bubble .web-sources a')?.href,
    sourceRel:document.querySelector('#bubble .web-sources a')?.rel,
    historySources:document.querySelectorAll('#conversation .web-sources a').length,
    protocol:window.lastProtocol.action,
    phase:libraryDebug.getState().phase
  })`);
  if (
    !chatCheck.visible ||
    !chatCheck.panelHidden ||
    !chatCheck.persistent ||
    chatCheck.full !== chatCheck.speech ||
    chatCheck.answer.length < 150 ||
    chatCheck.injected ||
    chatCheck.sourceCount !== 1 ||
    chatCheck.historySources !== 1 ||
    chatCheck.sourceUrl !== "https://example.com/evidence" ||
    !chatCheck.sourceRel.includes("noreferrer") ||
    chatCheck.preview !== chatCheck.answer ||
    chatCheck.protocol !== "IDLE" ||
    chatCheck.phase !== "IDLE"
  )
    throw new Error("自由问答显示或动作隔离失败：" + JSON.stringify(chatCheck));
  const { bubble: replyBounds, pet: petBounds } = chatCheck;
  if (
    !petBounds ||
    replyBounds.height <= 240 ||
    !(
      replyBounds.right <= petBounds.left - 22 ||
      replyBounds.left >= petBounds.right + 22 ||
      replyBounds.bottom <= petBounds.top - 22 ||
      replyBounds.top >= petBounds.bottom + 22
    )
  )
    throw new Error("恢复原气泡大小后遮挡了小和：" + JSON.stringify(chatCheck));
  await page.evaluate("libraryDebug.processText('请再举一个例子',true)");
  await waitFor(async () => (await state()).chat.turns === 2, "多轮追问");
  if ((await page.evaluate("chatTest.calls[1].history.length")) !== 2)
    throw new Error("追问未携带历史");
  await page.evaluate(
    "chatTest.config='second'; libraryDebug.processText('现在换一个解释方式',true)",
  );
  await waitFor(
    async () =>
      (await state()).chat.turns === 1 && (await page.evaluate("chatTest.calls.length")) === 3,
    "切换模型后重置上下文",
  );
  if ((await page.evaluate("chatTest.calls[2].history.length")) !== 0)
    throw new Error("更换模型残留旧上下文");
  await page.evaluate(
    "document.querySelector('#conversation [data-clear]').click(); document.querySelector('#conversation [data-close]').click(); window.fetch=chatTest.fetch; delete window.chatTest",
  );
  step("大模型对话", "语音自由提问、完整气泡、手动展开全文、多轮上下文与模型切换；未调用真实 API");

  if (await page.evaluate("document.querySelector('#searchForm, #query')"))
    throw new Error("重复的底部文字入口仍然存在");
  if (await page.evaluate("document.querySelectorAll('[data-query], .suggestions, .chip').length"))
    throw new Error("预置推荐入口仍然存在");
  await waitFor(async () => (await state()).localLibrary.ready, "连接空书库");
  // Only the external download transport is simulated. Completion writes a real TXT
  // into this test's isolated backend, then the production refresh/binding/GPU path runs.
  await page.evaluate(`(() => {
    window.downloadFixture = { fetch: window.fetch.bind(window), book: null };
    window.fetch = async (url, options) => {
      const json = payload => new Response(JSON.stringify(payload), {status:200, headers:{'Content-Type':'application/json'}});
      if (String(url).startsWith('/library/search?')) return json({local:[], results:[{title:'回归阅读甲',author:'测试作者',source:'回归书源',source_id:'fixture'}], errors:[]});
      if (url === '/library/download') {
        const bytes = new TextEncoder().encode('这是第一页的本地正文。'.repeat(1500));
        const response = await downloadFixture.fetch('/library/import', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({filename:'回归阅读甲.txt',data:btoa(String.fromCharCode(...bytes))})});
        if (!response.ok) throw Error('下载完成入库失败');
        downloadFixture.book = await response.json();
        return json({id:'shelving-fixture'});
      }
      if (url === '/library/jobs/shelving-fixture') return json({state:'completed',message:'下载完成',book:downloadFixture.book});
      return downloadFixture.fetch(url, options);
    };
    document.getElementById('libraryButton').click();
    document.getElementById('libraryQuery').value = '回归阅读甲';
    document.getElementById('librarySearch').requestSubmit();
  })()`);
  await waitFor(
    () =>
      page.evaluate(
        "document.querySelector('#libraryResults button')?.textContent === '下载并上架'",
      ),
    "显示可下载书籍",
  );
  await page.evaluate("document.querySelector('#libraryResults button').click()");
  await waitFor(
    async () => (await state()).visibleShelfBooks === 1 && !(await state()).localLibrary.working,
    "下载完成新增一本实体书",
  );
  const shelved = await state();
  const downloadedBook = await page.evaluate("window.libraryDebug.books[0]");
  if (
    shelved.phase !== "IDLE" ||
    shelved.book ||
    JSON.stringify(shelved.shelfView.focus) !== JSON.stringify(downloadedBook.worldPosition) ||
    JSON.stringify(shelved.shelfHighlight) !== JSON.stringify(downloadedBook.worldPosition) ||
    !(await page.evaluate("document.getElementById('localLibrary').hidden")) ||
    !(await text("locationText")).includes(downloadedBook.title)
  )
    throw Error("下载上架后没有定位真实槽位，或自动取走了刚下载的书");
  await page.evaluate("window.fetch=downloadFixture.fetch");
  step(
    "下载后在对应格子新增实体书",
    "自动定位书脊、保持在架上；外部下载使用测试响应，真实入库与场景绑定",
  );
  const imports = await page.evaluate(`(async () => {
    const saved = [downloadFixture.book];
    delete window.downloadFixture;
    for (const [title, content] of [["回归阅读乙", "另一册真实正文。".repeat(300)]]) {
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
  const libraryControls = await page.evaluate(`({
    urlForm: !!document.getElementById('libraryUrlImport'),
    urlInput: !!document.getElementById('libraryBookUrl'),
    urlButton: !!document.getElementById('previewBookUrl'),
    search: !!document.getElementById('librarySearch'),
    fileImport: !!document.getElementById('importBookFile'),
    sourceImport: !!document.getElementById('importSourceFile'),
    sources: [...document.getElementById('librarySource').options].map(o => o.value)
  })`);
  if (
    libraryControls.urlForm ||
    libraryControls.urlInput ||
    libraryControls.urlButton ||
    !libraryControls.search ||
    !libraryControls.fileImport ||
    !libraryControls.sourceImport
  )
    throw new Error(`书库入口清理不完整：${JSON.stringify(libraryControls)}`);
  if (
    JSON.stringify(libraryControls.sources) !== JSON.stringify(["all", "wyshu", "tianya", "shubao"])
  )
    throw new Error(`内置书源列表不正确：${JSON.stringify(libraryControls.sources)}`);
  step("书库入口与无忧／天涯／书包网内置书源");
  await page.evaluate(`(() => {
    window.networkTest = { fetch: window.fetch.bind(window), calls: [], retries: 0 };
    window.fetch = async (url, options) => {
      if (!String(url).startsWith('/library/search?')) return networkTest.fetch(url, options);
      const params = new URL(String(url), location.origin).searchParams;
      const source = params.get('source');
      networkTest.calls.push({ source, query: params.get('q') });
      const candidate = id => ({ source_id: id, title:'网络回归书', author:'测试作者', source:id, source_key:'fixture-'+id });
      let payload;
      if (source === 'all') payload = { local:[], results:[candidate('tianya')], errors:[{source_id:'shubao',source_name:'书包网 · 简体',message:'DNS 解析失败，请检查当前网络的域名解析后重试'}] };
      else if (++networkTest.retries === 1) payload = {local:[],results:[],errors:[{source_id:'shubao',source_name:'书包网 · 简体',message:'书源连接超时，请稍后重试或换源'}]};
      else payload = { local:[], results:[candidate('shubao')], errors:[] };
      return new Response(JSON.stringify(payload), {status:200,headers:{'Content-Type':'application/json'}});
    };
    document.getElementById('libraryQuery').value = '网络回归书';
    document.getElementById('librarySearch').requestSubmit();
  })()`);
  await waitFor(
    () =>
      page.evaluate(
        "document.querySelector('[data-retry-source=shubao]') && !document.getElementById('searchOnline').disabled",
      ),
    "显示具体失败书源与重试按钮",
  );
  const partialSearch = await page.evaluate(
    "document.getElementById('libraryResults').textContent",
  );
  if (
    !partialSearch.includes("书包网 · 简体") ||
    !partialSearch.includes("DNS") ||
    !partialSearch.includes("下载并上架") ||
    partialSearch.includes("没有找到")
  )
    throw new Error("部分书源失败时丢失成功结果或误报没有书：" + partialSearch);
  await page.evaluate("document.querySelector('[data-retry-source=shubao]').click()");
  await waitFor(
    () =>
      page.evaluate(
        "networkTest.retries === 1 && !document.getElementById('searchOnline').disabled",
      ),
    "失败书源重试仍失败",
  );
  if (
    !(await page.evaluate(
      "document.getElementById('libraryResults').textContent.includes('超时') && document.querySelectorAll('#libraryResults .book-result').length === 2",
    ))
  )
    throw new Error("重试失败清空了成功结果或重复显示错误");
  await page.evaluate(
    "document.getElementById('libraryQuery').value='尚未提交的其他书名'; document.querySelector('[data-retry-source=shubao]').click()",
  );
  await waitFor(
    () =>
      page.evaluate(
        "networkTest.retries === 2 && !document.getElementById('searchOnline').disabled",
      ),
    "仅重试失败书源并合并成功结果",
  );
  const retriedSearch = await page.evaluate(`({
    calls:networkTest.calls, rows:document.querySelectorAll('#libraryResults .book-result').length,
    retry:!!document.querySelector('[data-retry-source]'), source:document.getElementById('librarySource').value
  })`);
  if (
    retriedSearch.rows !== 2 ||
    retriedSearch.retry ||
    retriedSearch.source !== "all" ||
    JSON.stringify(retriedSearch.calls.map((c) => c.source)) !==
      JSON.stringify(["all", "shubao", "shubao"]) ||
    retriedSearch.calls.some((c) => c.query !== "网络回归书")
  )
    throw new Error(
      "单书源重试改变查询、重复访问成功书源或丢失结果：" + JSON.stringify(retriedSearch),
    );
  await page.evaluate(
    "window.fetch=networkTest.fetch; delete window.networkTest; document.getElementById('libraryResults').replaceChildren(); document.getElementById('libraryQuery').value=''",
  );
  step(
    "书源网络失败与单独重试",
    "准确显示来源和原因；重试失败不丢书，恢复后合并结果；未改网络或连接外站",
  );
  await click("closeLibrary");
  const bound = await page.evaluate("window.libraryDebug.books");
  const firstBook = bound.find((b) => b.localBookId === imports[0].id);
  const secondBook = bound.find((b) => b.localBookId === imports[1].id);
  if (!firstBook || !secondBook) throw new Error("导入书籍未绑定真实槽位");
  await click("libraryButton");
  await waitFor(
    () =>
      page.evaluate(`Boolean(document.querySelector('[data-locate-book="${firstBook.bookId}"]'))`),
    "已入库书籍提供定位入口",
  );
  await page.evaluate(`document.querySelector('[data-locate-book="${firstBook.bookId}"]').click()`);
  if ((await state()).visibleShelfBooks !== 2 || (await state()).phase !== "IDLE")
    throw Error("定位书架时取走了实体书");
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
      const shot = await Promise.race([
        page.send("Page.captureScreenshot", { format: "png" }),
        sleep(10000).then(() => {
          throw new Error("Failure screenshot timed out");
        }),
      ]);
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
