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

    node tools/package-local.mjs [--zip] [--shortcut] [--no-build] [--skip-deps]

The model is not in this repository (it is 228 MiB and belongs to nobody's git history). Put it
at .cache/models/<name>/ first, or point HEXU_ASR_MODEL_DIR at it; without it the script prints
the exact command to fetch it from the deployment. See DEPLOY.md, 「本机版打包」. */
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP = "和序图书馆";
const MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17";
const DEPLOY_HOST = "root@64.90.2.91";
const DEPLOY_MODEL_PATH = `/opt/hexu-library/models/${MODEL_NAME}`;
// The repository of record, and the only one that carries the `model` branch.
const GITHUB_REMOTE = "git@github.com:Amyias/hexu-virtual-library.git";

const cache = path.join(root, ".cache");
const venv = path.join(cache, "venv");
const venvPython = path.join(venv, "Scripts", "python.exe");
// Resolved to an absolute path: the value is handed to PyInstaller, which resolves relative data
// paths against the spec file's directory rather than the working directory — a relative
// HEXU_ASR_MODEL_DIR would otherwise fail with a confusing "unable to find" error.
const modelDir = path.resolve(
  process.env.HEXU_ASR_MODEL_DIR || path.join(cache, "models", MODEL_NAME),
);
const stage = path.join(cache, "stage", "site");
const dist = path.join(root, "dist");
const appDir = path.join(dist, APP);

/** Files the browser fetches at runtime. Everything else in the tree is build material. */
const SITE_FILES = [
  "index.html",
  "src",
  path.join("public", "favicon.ico"),
  path.join("public", "settings.html"),
  path.join("public", "vendor"),
  path.join("public", "models", "hexu-library.glb"),
  path.join("public", "models", "smart-book.glb"),
  path.join("public", "models", "shelf-book.glb"),
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

const DEPENDENCIES = ["pyinstaller==6.22.3", "sherpa-onnx==1.13.8", "pywebview==6.2.1"];
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

/** Rebuild the model out of the `model` branch when there is no local copy.

 *  The model is 228 MiB and GitHub refuses a single file that large, so it lives on a branch of
 *  its own, split into parts (model/README.md explains the arrangement). The parts are read with
 *  `git show`, which leaves master's index and working tree untouched — checking the path out
 *  would stage 228 MiB for the next commit.

 *  Every part, and then the reassembled file, are checked against model/manifest.json. A model
 *  that does not match is worse than no model at all: it would package into a program that fails
 *  on the first utterance, a long way from the cause. */
function restoreModelFromBranch() {
  // A fresh clone from GitHub has the branch only as <remote>/model until it is checked out, so
  // the remote-tracking copies count too.
  const remotes = (run("git", ["-C", root, "remote"]).stdout || "").split(/\s+/).filter(Boolean);
  const ref = ["model", ...remotes.map((remote) => `${remote}/model`)].find(
    (candidate) =>
      run("git", ["-C", root, "rev-parse", "--verify", "--quiet", `${candidate}^{commit}`]).status === 0,
  );
  if (!ref) return false;
  const read = (name, encoding) => {
    const result = spawnSync("git", ["-C", root, "show", `${ref}:model/${name}`], {
      encoding,
      maxBuffer: 512 * 1024 * 1024,
    });
    return result.status === 0 && result.stdout ? result.stdout : null;
  };

  const manifestText = read("manifest.json", "utf8");
  if (!manifestText) return false;
  let manifest;
  try {
    manifest = JSON.parse(manifestText);
  } catch {
    return false;
  }

  log(`本地没有模型，从 model 分支取回（${manifest.parts.length} 块，共 ${megabytes(manifest.bytes)}）…`);
  const pieces = [];
  for (const part of manifest.parts) {
    const bytes = read(part.name, "buffer");
    if (!bytes || bytes.length !== part.bytes) {
      fail(`分块 ${part.name} 取回失败或长度不符，model 分支可能不完整。`);
    }
    if (createHash("sha256").update(bytes).digest("hex") !== part.sha256) {
      fail(`分块 ${part.name} 的 SHA-256 不符，拒绝用它打包。`);
    }
    pieces.push(bytes);
  }
  const whole = Buffer.concat(pieces);
  if (whole.length !== manifest.bytes) fail("拼接后的长度与 manifest 不符。");
  if (createHash("sha256").update(whole).digest("hex") !== manifest.sha256) {
    fail("拼接后的 SHA-256 与 manifest 不符，拒绝用它打包。");
  }

  fs.mkdirSync(modelDir, { recursive: true });
  fs.writeFileSync(path.join(modelDir, manifest.file), whole);
  for (const extra of ["tokens.txt", "LICENSE"]) {
    const bytes = read(extra, "buffer");
    if (bytes) fs.writeFileSync(path.join(modelDir, extra), bytes);
  }
  log(`  校验通过（sha256 ${manifest.sha256.slice(0, 16)}…）`);
  return true;
}

function checkModel() {
  const missing = ["model.int8.onnx", "tokens.txt"].filter(
    (name) => !fs.existsSync(path.join(modelDir, name)),
  );
  if (missing.length && !restoreModelFromBranch()) {
    fail(
      `识别模型不在这里：${modelDir}\n缺少 ${missing.join("、")}\n\n` +
        "它本来会自动从 model 分支取回，但现在也取不到——若这是浅克隆或单分支克隆\n" +
        "（--depth 1 / --single-branch），那个分支默认不在本地，先取下来：\n" +
        `  git fetch ${GITHUB_REMOTE} model:model\n` +
        "仍然不行的话，从部署机器拷一次：\n" +
        `  mkdir -p ".cache/models/${MODEL_NAME}"\n` +
        `  scp -i ~/.ssh/rainyun-rcs-Snowy_Brew.pem "${DEPLOY_HOST}:${DEPLOY_MODEL_PATH}/{model.int8.onnx,tokens.txt,LICENSE}" ".cache/models/${MODEL_NAME}/"\n`,
    );
  }
  const size = sizeOf(path.join(modelDir, "model.int8.onnx"));
  if (size < 200 * 1024 * 1024) fail(`model.int8.onnx 只有 ${megabytes(size)}，看起来不完整。`);
  log(`识别模型  ${megabytes(size)}  ${modelDir}`);
}

/** Record what this build was made from, inside the bundle.

 *  The installed program can then say which commit it is, and the updater — which works by
 *  pulling the source and rebuilding — has a default answer to "where is the checkout". It is
 *  written as a site file, so the page can read it at /build-info.json too. */
function writeBuildInfo() {
  const version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
  const commit = (run("git", ["-C", root, "rev-parse", "HEAD"]).stdout || "").trim();
  const branch = (run("git", ["-C", root, "rev-parse", "--abbrev-ref", "HEAD"]).stdout || "").trim();
  const info = {
    app: APP,
    version,
    commit,
    branch,
    built_at: new Date().toISOString(),
    source_dir: root,
  };
  fs.writeFileSync(path.join(stage, "build-info.json"), JSON.stringify(info, null, 2) + "\n", "utf8");
  log(`版本标记   ${(commit || "(无 git，未记录提交)").slice(0, 12)} · ${info.built_at}`);
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
  writeBuildInfo();

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
  // This list is the contract of what the bundle must carry. Every one of these was once
  // missing from a build for a real reason (a forgotten entry in SITE_FILES above, a data file
  // PyInstaller did not collect), and a build that fails here is much cheaper than a program
  // that fails on the reader's machine.
  const required = [
    path.join(appDir, `${APP}.exe`),
    path.join(appDir, "_internal", "index.html"),
    path.join(appDir, "_internal", "build-info.json"),
    path.join(appDir, "_internal", "public", "favicon.ico"),
    path.join(appDir, "_internal", "public", "settings.html"),
    path.join(appDir, "_internal", "public", "models", "hexu-library.glb"),
    path.join(appDir, "_internal", "public", "models", "smart-book.glb"),
    path.join(appDir, "_internal", "public", "models", "shelf-book.glb"),
    path.join(appDir, "_internal", "models", "sense-voice", "model.int8.onnx"),
  ];
  const missing = required.filter((file) => !fs.existsSync(file));
  if (missing.length) fail("打包结果缺少文件：\n  " + missing.join("\n  "));
  log(`产物      ${megabytes(sizeOf(appDir))}  ${appDir}`);
}

const INSTRUCTIONS = `和序图书馆 · 本机版
========================

怎么用
  双击「和序图书馆.exe」。程序直接打开自己的窗口，图书馆就在窗口里——没有浏览器的标签页，
  也没有黑色的命令行窗口。关掉窗口，程序就退出了。

  麦克风不需要你在窗口里点「允许」：程序已经替这个页面放行了（用系统浏览器打开时才需要点
  一次）。真正的开关在页面里——第一次点一下「启动语音感知」，之后每次打开都会自动开始
  收听，直接说「小和」即可。

每个文件是什么
  和序图书馆.exe    程序本体，双击它
  _internal\\        程序运行需要的一切：Python 运行时、窗口组件、站点、语音识别模型（228 MB）
  使用说明.txt      本文件

语音识别完全在本机运行，录音不出这台电脑。

正文书库与小说阅读
  点击「本地书库」可以搜索、下载正文，也可以导入自己的 TXT / EPUB，或导入静态书源 JSON。
  直接说「小和，帮我找书名」也能查找本地正文；没有缓存时会搜索在线书源并下载。
  打开书本封面后进入正文阅读，可翻页、选择章节、调整字号，阅读位置会自动保存。
  正文和书库索引保存在 %APPDATA%\\hexu-library\\books，更新程序不会覆盖它们。
  在线搜索和下载需要网络；已经下载或导入的正文可以离线阅读。

大语言模型（可选，让「霍金写的那本」这类说法也能听懂）
  在窗口页面底部展开「使用说明 ↗」，里面有「本机设置」的入口；或直接打开
  http://localhost:8090/settings ，填入你自己的 API 密钥，点「保存并测试连接」。
  不填也完全能用：找书由本地规则即时完成，只是规则看不懂的说法会被礼貌拒绝。
  配置保存在 %APPDATA%\\hexu-library\\llm.env，不在这个文件夹里，所以整个文件夹可以随意
  复制、替换、删除，密钥不受影响；分发给别人时也不会带走你的密钥。
  填写之后，为理解语义，转写文本与馆藏目录会发送给所配置的模型服务。

更新
  程序启动后会检查 GitHub 上有没有新版本，有就在设置页里一键更新：下载新版本 → 校验 →
  覆盖 → 自动重新打开。程序包约 99 MB，语音识别模型不在更新里（原地保留），所以更新很快。
  仓库是私有的，因此这台机器需要一个只读的 GitHub 令牌：在设置页「更新」那一栏粘贴即可，
  也可以放在环境变量 GITHUB_TOKEN 里。没有令牌时设置页会明确提示，不会给出看不懂的错误。
  命令行另有：和序图书馆.exe --check-update

命令行开关
  和序图书馆.exe --port 9000     换端口（端口被占用时会自动挑一个空闲的）
  和序图书馆.exe --browser       不开程序窗口，改用系统浏览器打开
  和序图书馆.exe --check-mic     检查窗口里的麦克风能不能用；结论也会写进
                                 %APPDATA%\\hexu-library\\mic-check.txt
  窗口起不来时（例如系统里没装 WebView2 运行时）程序会自动改用浏览器打开，并给出提示。

出问题了看哪里
  听不到我说话
    跑一次 --check-mic 看结论。若是被系统拒绝，在「设置 → 隐私和安全性 → 麦克风」里允许
    桌面应用使用麦克风。
  识别不可用
    多半是 _internal\\models\\sense-voice\\ 里的模型文件被删了或被安全软件隔离了，重新解压
    一份即可；设置页顶部会写明原因。
  第一次说话要等
    第一次会把 228 MB 模型读进内存，之后常驻。程序启动时已经在后台预热，通常察觉不到。
`;

function writeInstructions() {
  fs.writeFileSync(path.join(appDir, "使用说明.txt"), INSTRUCTIONS, "utf8");
}

/* Put a shortcut on the desktop, pointing at the program just built.

   Two details here are not obvious:

   - The values travel in a UTF-8 file, not on the PowerShell command line or inside a script
     file. Windows PowerShell 5.1 decodes a BOM-less script file, and non-ASCII arguments, using
     the console code page — write a .ps1 containing Chinese as UTF-8 and the strings arrive as
     mojibake, silently. Keeping the script pure ASCII and reading the Chinese back with
     `-Encoding UTF8` takes that whole question off the table.
   - The shortcut is read back and compared with what was asked for. A shortcut is opaque binary;
     if a name or target lands wrong the only symptom is a broken icon later, so creation and
     verification happen in the same breath. */
function desktopShortcut() {
  const target = path.join(appDir, `${APP}.exe`);
  if (!fs.existsSync(target)) fail(`找不到程序文件：${target}`);
  fs.mkdirSync(cache, { recursive: true });
  const specPath = path.join(cache, "shortcut.json");
  const reportPath = path.join(cache, "shortcut-report.json");
  fs.rmSync(reportPath, { force: true });
  fs.writeFileSync(specPath, JSON.stringify({
    name: APP,
    target,
    workingDirectory: appDir,
    description: "和序图书馆 · 本机版（自带语音识别）",
  }), "utf8");

  const script = `
$ErrorActionPreference = 'Stop'
$spec = Get-Content -LiteralPath $env:HEXU_SHORTCUT_SPEC -Raw -Encoding UTF8 | ConvertFrom-Json
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop ($spec.name + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $spec.target
$shortcut.WorkingDirectory = $spec.workingDirectory
$shortcut.Description = $spec.description
$shortcut.Save()
$check = $shell.CreateShortcut($link)
$report = [ordered]@{
  link = $link
  desktop = $desktop
  target = $check.TargetPath
  matches = ($check.TargetPath -eq $spec.target) -and ($check.Description -eq $spec.description)
  exists = (Test-Path -LiteralPath $link)
}
($report | ConvertTo-Json) | Out-File -LiteralPath $env:HEXU_SHORTCUT_REPORT -Encoding UTF8
`;
  const result = run("powershell", ["-NoProfile", "-NonInteractive", "-Command", script], {
    env: { ...process.env, HEXU_SHORTCUT_SPEC: specPath, HEXU_SHORTCUT_REPORT: reportPath },
  });
  if (result.error) fail("找不到 PowerShell，无法创建桌面快捷方式。" + result.error.message);
  let report = null;
  try {
    report = JSON.parse(fs.readFileSync(reportPath, "utf8").replace(/^\uFEFF/, ""));
  } catch {
    /* fall through to the message below */
  }
  fs.rmSync(specPath, { force: true });
  fs.rmSync(reportPath, { force: true });
  if (!report) {
    fail(
      "创建桌面快捷方式失败：" +
        (result.stderr || result.stdout || `PowerShell 退出码 ${result.status}`).trim(),
    );
  }
  if (!report.exists || !report.matches || !fs.existsSync(report.link)) {
    fail(`快捷方式写好了但对不上，请检查桌面：${report.link}\n期望指向 ${target}，实际 ${report.target}`);
  }
  log(`快捷方式  ${report.link}`);
  log(`          → ${report.target}`);
  log("          （指向的是 dist 里的那个文件，把 dist 搬走就会失效。）");
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
const noBuild = process.argv.includes("--no-build");
const python = noBuild ? null : ensurePython();
if (python && !process.argv.includes("--skip-deps")) ensureDependencies(python);
if (python) {
  checkModel();
  stageSite();
  build(python);
} else {
  log("--no-build：跳过打包，只做收尾（快捷方式 / 压缩包）。");
}
verify();
writeInstructions();
if (process.argv.includes("--shortcut")) desktopShortcut();
if (process.argv.includes("--zip")) zip();
log("");
log(`完成。把「${APP}」整个文件夹复制到任何地方都能运行。`);
