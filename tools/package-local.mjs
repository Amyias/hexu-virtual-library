/* Build the local, double-clickable build of the library.

What it produces is a folder the reader can copy anywhere and run:

    dist/和序图书馆/和序图书馆.exe      double-click; prints the address and opens the browser
    dist/和序图书馆/_internal/          Python runtime, dependencies, the site, the speech model
    dist/和序图书馆/使用说明.txt

Why this exists as a step rather than a documented set of commands: the site has to be copied
with its pre-compressed .gz siblings, the 228 MiB speech model has to be found and checked, the
build has to use a virtual environment whose interpreter actually has a sherpa-onnx wheel, and
every one of those is easy to get subtly wrong by hand. Running it again is cheap — the
environment and dependencies are reused when they are already there.

    node tools/package-local.mjs [--zip] [--skip-deps]

The model is not in this repository (it is 228 MiB and belongs to nobody's git history). Put it
at .cache/models/<name>/ first, or point HEXU_ASR_MODEL_DIR at it; without it the script prints
the exact command to fetch it from the deployment. See DEPLOY.md, 「本机版打包」. */
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP = "和序图书馆";
const MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17";
const DEPLOY_HOST = "root@64.90.2.91";
const DEPLOY_MODEL_PATH = `/opt/hexu-library/models/${MODEL_NAME}`;

const cache = path.join(root, ".cache");
const venv = path.join(cache, "venv");
const venvPython = path.join(venv, "Scripts", "python.exe");
const modelDir =
  process.env.HEXU_ASR_MODEL_DIR || path.join(cache, "models", MODEL_NAME);
const stage = path.join(cache, "stage", "site");
const dist = path.join(root, "dist");
const appDir = path.join(dist, APP);

/** Files the browser fetches at runtime. Everything else in the tree is build material. */
const SITE_FILES = [
  "index.html",
  "src",
  path.join("public", "settings.html"),
  path.join("public", "vendor"),
  path.join("public", "models", "hexu-library.glb"),
  path.join("public", "models", "smart-book.glb"),
  path.join("public", "models", "manifest.json"),
  path.join("public", "models", "book-inventory.json"),
];
// public/textures is deliberately absent: those seven images are embedded in
// hexu-library.glb already, and the loose copies exist only to feed Blender.

/** Compressed in place, so the server can answer with Content-Encoding: gzip. */
const COMPRESSIBLE = new Set([".html", ".js", ".mjs", ".css", ".json", ".glb", ".svg", ".txt"]);

const log = (text) => process.stdout.write(text + "\n");
const fail = (text) => {
  process.stderr.write(text + "\n");
  process.exit(1);
};

function run(command, args, options = {}) {
  return spawnSync(command, args, { cwd: root, encoding: "utf8", ...options });
}

function sizeOf(target) {
  const stat = fs.statSync(target);
  if (stat.isFile()) return stat.size;
  return fs
    .readdirSync(target)
    .reduce((total, name) => total + sizeOf(path.join(target, name)), 0);
}

function megabytes(bytes) {
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

/** The interpreter the build runs on. A virtual environment, because the dependencies are
 *  installed for this build alone and the machine's own Python is left untouched. */
function ensurePython() {
  if (fs.existsSync(venvPython)) {
    const check = run(venvPython, ["-c", "print(1)"]);
    if (check.status === 0) return venvPython;
    log("构建环境已损坏，重新创建。");
    fs.rmSync(venv, { recursive: true, force: true });
  }
  const candidates = [
    ["py", ["-3.14"]],
    ["py", ["-3"]],
    ["python", []],
    ["python3", []],
  ];
  let base = null;
  for (const [command, prefix] of candidates) {
    const probe = run(command, [
      ...prefix,
      "-c",
      "import sys;print('%d.%d' % sys.version_info[:2])",
    ]);
    if (probe.status !== 0) continue;
    const [major, minor] = probe.stdout.trim().split(".").map(Number);
    if (major === 3 && minor >= 9) {
      base = { command, prefix, version: probe.stdout.trim() };
      break;
    }
  }
  if (!base)
    fail(
      "找不到可用的 Python 3.9+。安装一个（https://www.python.org/downloads/windows/）后重试；\n" +
        "本项目用它的虚拟环境打包，不会改动系统 Python。",
    );
  log(`使用 Python ${base.version}（${base.command}）创建构建环境`);
  const created = run(base.command, [...base.prefix, "-m", "venv", venv], {
    stdio: "inherit",
  });
  if (created.status !== 0) fail("创建虚拟环境失败。");
  return venvPython;
}

const DEPENDENCIES = ["pyinstaller==6.22.3", "sherpa-onnx==1.13.8"];
/* Listed separately because the sherpa-onnx wheel does not pull it in, yet transcribe() needs
   it — and without it the packaged program starts, reports itself ready, and then fails on the
   first utterance. The deployment installs it the same way. */
const ALSO_REQUIRED = ["numpy"];

function ensureDependencies(python) {
  const installed = run(python, ["-m", "pip", "show", ...DEPENDENCIES.map((pin) => pin.split("==")[0]), ...ALSO_REQUIRED]);
  if (installed.status === 0 && !installed.stdout.includes("WARNING")) {
    log("构建依赖已就绪，跳过安装。");
    return;
  }
  log(`安装构建依赖：${[...DEPENDENCIES, ...ALSO_REQUIRED].join(" + ")}（首次约需几分钟）`);
  const result = run(
    python,
    [
      "-m",
      "pip",
      "install",
      "--disable-pip-version-check",
      "--no-input",
      "--retries",
      "6",
      "--timeout",
      "40",
      ...DEPENDENCIES,
      ...ALSO_REQUIRED,
    ],
    { stdio: "inherit" },
  );
  if (result.status !== 0)
    fail(
      "安装依赖失败。网络不稳时可以换镜像源重试：\n" +
        `  "${python}" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ${[...DEPENDENCIES, ...ALSO_REQUIRED].join(" ")}`,
    );
}

function checkModel() {
  const missing = ["model.int8.onnx", "tokens.txt"].filter(
    (name) => !fs.existsSync(path.join(modelDir, name)),
  );
  if (missing.length)
    fail(
      `识别模型不在这里：${modelDir}\n缺少 ${missing.join("、")}\n\n` +
        "从部署机器取回（一次性，约 228 MiB）：\n" +
        `  mkdir -p ".cache/models/${MODEL_NAME}"\n` +
        `  scp -i ~/.ssh/rainyun-rcs-Snowy_Brew.pem "${DEPLOY_HOST}:${DEPLOY_MODEL_PATH}/{model.int8.onnx,tokens.txt,LICENSE}" ".cache/models/${MODEL_NAME}/"\n`,
    );
  const size = sizeOf(path.join(modelDir, "model.int8.onnx"));
  if (size < 200 * 1024 * 1024) fail(`model.int8.onnx 只有 ${megabytes(size)}，看起来不完整。`);
  log(`识别模型  ${megabytes(size)}  ${modelDir}`);
}

function stageSite() {
  fs.rmSync(stage, { recursive: true, force: true });
  for (const relative of SITE_FILES) {
    const source = path.join(root, relative);
    if (!fs.existsSync(source)) fail(`站点文件缺失：${relative}`);
    const destination = path.join(stage, relative);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.cpSync(source, destination, { recursive: true });
  }

  let raw = 0;
  let compressed = 0;
  const walk = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (entry.name.endsWith(".gz")) continue;
      if (!COMPRESSIBLE.has(path.extname(entry.name).toLowerCase())) continue;
      const body = fs.readFileSync(full);
      if (body.length < 1024) continue; // a .gz of a tiny file is larger than the file
      const gzipped = zlib.gzipSync(body, { level: 9 });
      fs.writeFileSync(full + ".gz", gzipped);
      // The server only uses a .gz sibling that is at least as new as its original, so the
      // compressed copy is written with a freshness stamp of its own.
      const stamp = Date.now() / 1000;
      fs.utimesSync(full + ".gz", stamp, stamp);
      raw += body.length;
      compressed += gzipped.length;
    }
  };
  walk(stage);
  const ratio = raw ? (100 - (compressed / raw) * 100).toFixed(0) : "0";
  log(`站点      原始 ${megabytes(raw)} → 预压缩 ${megabytes(compressed)}（省 ${ratio}%）`);
}

function clearPreviousBuild() {
  if (!fs.existsSync(appDir)) return;
  try {
    fs.rmSync(appDir, { recursive: true, force: true });
  } catch (error) {
    // The overwhelmingly likely cause is that the program built last time is still running:
    // Windows locks a mapped executable and its shared libraries.
    fail(
      `无法删除上次的产物：${appDir}\n` +
        `多半是「${APP}」还在运行（或刚关闭、文件仍被占用）。先关掉它的窗口再重新打包。\n` +
        `原始错误：${error.message}`,
    );
  }
}

function build(python) {
  clearPreviousBuild();
  fs.mkdirSync(dist, { recursive: true });
  log("开始打包（PyInstaller，约需一两分钟）…");
  const result = run(
    python,
    [
      "-m",
      "PyInstaller",
      path.join("tools", "hexu-library.spec"),
      "--noconfirm",
      "--distpath",
      "dist",
      "--workpath",
      path.join(".cache", "pyinstaller"),
      "--log-level",
      "WARN",
    ],
    {
      stdio: "inherit",
      // Passed through the environment rather than argv: the project directory has a Chinese
      // name, and this shell converts non-ASCII in argv to the console code page.
      env: { ...process.env, HEXU_ASR_MODEL_DIR: modelDir },
    },
  );
  if (result.status !== 0) fail("打包失败（PyInstaller 的输出见上）。");
}

function verify() {
  const required = [
    path.join(appDir, `${APP}.exe`),
    path.join(appDir, "_internal", "index.html"),
    path.join(appDir, "_internal", "public", "settings.html"),
    path.join(appDir, "_internal", "public", "models", "hexu-library.glb"),
    path.join(appDir, "_internal", "models", "sense-voice", "model.int8.onnx"),
  ];
  const missing = required.filter((file) => !fs.existsSync(file));
  if (missing.length) fail("打包结果缺少文件：\n  " + missing.join("\n  "));
  log(`产物      ${megabytes(sizeOf(appDir))}  ${appDir}`);
}

const INSTRUCTIONS = `和序图书馆 · 本机版
========================

怎么用
  双击「和序图书馆.exe」。会弹出一个黑色窗口，显示地址并自动打开浏览器。
  想停止：关掉那个窗口，或在窗口里按 Ctrl+C。
  浏览器里第一次要允许麦克风权限（点一次「启动语音感知」）；之后每次打开都会自动开始收听，
  直接说「小和」即可。

每个文件是什么
  和序图书馆.exe    程序本体，双击它
  _internal\\        程序运行需要的一切：Python 运行时、站点、语音识别模型（228 MB）
  使用说明.txt      本文件

语音识别完全在本机运行，录音不出这台电脑。

大语言模型（可选，让「霍金写的那本」这类说法也能听懂）
  浏览器打开 http://localhost:8090/settings ，填入你自己的 API 密钥，点「保存并测试连接」。
  不填也完全能用：找书由本地规则即时完成，只是规则看不懂的说法会被礼貌拒绝。
  配置保存在 %APPDATA%\\hexu-library\\llm.env，不在这个文件夹里，所以整个文件夹可以随意
  复制、替换、删除，密钥不受影响；分发给别人时也不会带走你的密钥。
  填写之后，为理解语义，转写文本与馆藏目录会发送给所配置的模型服务。

换个端口
  和序图书馆.exe --port 9000
  不想自动打开浏览器：和序图书馆.exe --no-browser
  端口被占用时会自动挑一个空闲的；如果本程序已经在运行，它会直接打开已在运行的那个。

出问题了看哪里
  识别不可用
    十有八九是 _internal\\models\\sense-voice\\ 里的模型文件被删了或被安全软件隔离了。
    重新解压一份即可。黑色窗口的第一屏会写明原因。
  浏览器没有自动打开
    手动访问窗口里显示的地址（默认 http://localhost:8090/）。必须用 localhost，
    用局域网 IP 打开时浏览器不会给麦克风权限。
  语速慢、第一次说话要等
    第一次会把 228 MB 模型读进内存，之后常驻。程序启动时已经在后台预热，通常察觉不到。
`;

function writeInstructions() {
  fs.writeFileSync(path.join(appDir, "使用说明.txt"), INSTRUCTIONS, "utf8");
}

function zip() {
  const archive = path.join(dist, `${APP}.zip`);
  fs.rmSync(archive, { force: true });
  log("压缩发行包（约 400 MB，需要几分钟）…");
  const result = run("tar", ["-c", "-a", "-f", archive, APP], { cwd: dist, stdio: "inherit" });
  if (result.status !== 0) fail("压缩失败（Windows 10 自带的 tar 应当支持 -a 生成 zip）。");
  log(`压缩包    ${megabytes(sizeOf(archive))}  ${archive}`);
}

log("和序图书馆 · 本机版打包");
const python = ensurePython();
if (!process.argv.includes("--skip-deps")) ensureDependencies(python);
checkModel();
stageSite();
build(python);
verify();
writeInstructions();
if (process.argv.includes("--zip")) zip();
log("");
log(`完成。把「${APP}」整个文件夹复制到任何地方都能运行。`);
