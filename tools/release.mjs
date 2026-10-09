/* Publish a version: build, cut the two archives, and put them on the GitHub release.

What a release carries, and why it is two files rather than one:

    hexu-library-<version>-program.zip   the program, ~99 MB, without the model
    sense-voice-<version>.zip            the model on its own, ~228 MB

The model never changes, so shipping it inside the program archive would mean downloading 228 MB
on every update for nothing — 30 seconds of transfer instead of 95, and three times the surface
for the intermittent TLS failures this network has (measured at roughly one connection in five).
An update therefore downloads the program archive and leaves the model where it is; only a machine
that has no model yet downloads the model archive.

Both archives unpack at the install root, so applying either is a plain overwrite.

    node tools/release.mjs                 build, archive, publish
    node tools/release.mjs --prepare-only  build and archive, print the paths, publish nothing

Publishing needs a token in GITHUB_TOKEN (fine-grained, Contents: Read and write). It is read in
the few requests that need it and never copied, logged or written anywhere — the same rule the
Gitee token follows in DEVELOPMENT.md. Without it, --prepare-only leaves the archives ready to
drag into the release page by hand.

Before publishing this bumps nothing: the version comes from package.json, so a release is always
"commit the version, then run this".
*/
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP = "和序图书馆";
const REPO = "Amyias/hexu-virtual-library";
const API = "https://api.github.com";
const TOKEN_VARIABLE = "GITHUB_TOKEN";
const APP_DIR = path.join(root, "dist", APP);
const OUT_DIR = path.join(root, "dist", "release");

const log = (text) => process.stdout.write(text + "\n");
const fail = (text) => {
  process.stderr.write(text + "\n");
  process.exit(1);
};

function run(command, args, options = {}) {
  return spawnSync(command, args, { cwd: root, encoding: "utf8", ...options });
}

function megabytes(bytes) {
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

function sha256(file) {
  return createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

/** Everything that has to be true before a version can be called a version.
 *
 *  `--assets-only` relaxes the tag checks: nothing new is being published, an archive is being
 *  added to a release that already exists — re-uploading the model after a model change, or
 *  replacing one that turned out to be unusable. The rest still applies: the tree has to be clean,
 *  because the archive is built from it. */
function preflight(version, assetsOnly) {
  const branch = run("git", ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.trim();
  if (branch !== "master") fail(`发版要在 master 上，当前在 ${branch}。`);

  const dirty = run("git", ["status", "--porcelain", "--untracked-files=no"]).stdout.trim();
  if (dirty) {
    fail(
      "工作区有未提交的改动，先提交再发版——发行版必须对应一个确切的提交：\n" + dirty,
    );
  }

  if (assetsOnly) {
    log(`补传附件到已发布的 v${version}`);
    return run("git", ["rev-parse", "HEAD"]).stdout.trim();
  }

  const local = run("git", ["tag", "-l", `v${version}`]).stdout.trim();
  if (local) fail(`标签 v${version} 已存在。改 package.json 的版本号再发。`);

  const remote = run("git", ["ls-remote", "--tags", "github", `v${version}`]).stdout.trim();
  if (remote) fail(`GitHub 上已经有 v${version} 这个标签了。要往它上面补传附件，加 --assets-only。`);
  return run("git", ["rev-parse", "HEAD"]).stdout.trim();
}

/** The two archives. Both unpack at the install root: the program archive is everything except
 *  the model, the model archive is the model under the path it belongs at.
 *
 *  `--no-model` leaves the model archive out entirely. The model never changes between versions,
 *  and the program already finds it in the newest release that carries one, so uploading 228 MB
 *  again — with a one-in-five chance of a stalled connection per session — buys nothing. */
function archive(version, withModel) {
  if (!fs.existsSync(path.join(APP_DIR, `${APP}.exe`))) {
    fail(`先打包：${APP_DIR} 里没有程序。运行 node tools/package-local.mjs`);
  }
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const program = path.join(OUT_DIR, `hexu-library-${version}-program.zip`);
  const model = path.join(OUT_DIR, `sense-voice-${version}.zip`);
  for (const file of [program, model]) fs.rmSync(file, { force: true });

  const entries = fs
    .readdirSync(APP_DIR)
    .filter((name) => name !== "_internal");
  entries.push("_internal");

  // Python writes the archives, not tar: `tar -a -f x.zip` produces a plain tar with a zip name
  // (GNU tar has no zip compressor), which every zip reader refuses while PowerShell's
  // Expand-Archive "succeeds" by extracting nothing. That is how an install got mirrored over
  // with emptiness. tools/make-archive.py writes a real zip and reads it back to prove it.
  const python = fs.existsSync(path.join(root, ".cache", "venv", "Scripts", "python.exe"))
    ? path.join(root, ".cache", "venv", "Scripts", "python.exe")
    : "python";

  const madeProgram = run(
    python,
    [
      path.join("tools", "make-archive.py"), program, APP_DIR, ...entries,
      // The model is the one thing left behind.
      "--exclude", "_internal/models",
    ],
    { stdio: "inherit" },
  );
  if (madeProgram.status !== 0) fail("切程序包失败。");

  const assets = [{ file: program, name: path.basename(program), label: "程序包（不含模型）" }];
  if (!withModel) {
    log("（--no-model：模型包跳过，更新器会从带了模型的那个发行版里取）");
    return assets;
  }

  const madeModel = run(
    python,
    [
      path.join("tools", "make-archive.py"), model, APP_DIR, "_internal/models",
      // Deflating 228 MB of int8 weights saves almost nothing and costs a minute.
      "--store",
    ],
    { stdio: "inherit" },
  );
  if (madeModel.status !== 0) fail("切模型包失败。");
  assets.push({ file: model, name: path.basename(model), label: "模型包" });
  return assets;
}

/** The release notes: the commits that are in this version. */
function notes(version, commit) {
  const log15 = run("git", ["log", "--pretty=format:- %s", "-n", "15"]).stdout.trim();
  // The remote's tags, not this checkout's: releases are created through the API, which makes
  // the tag on GitHub without leaving one here.
  const tags = run("git", ["ls-remote", "--tags", "github"]).stdout.trim();
  const first = !tags;
  return [
    first ? `和序图书馆 首个发行版 v${version}` : `和序图书馆 v${version}`,
    "",
    `提交 \`${commit.slice(0, 12)}\``,
    "",
    "### 本版包含的提交",
    log15,
    "",
    "### 怎么装",
    "1. 下载 `*-program.zip`，解压覆盖到程序文件夹（模型原地保留，不会被覆盖）。",
    "2. 只有新机器才需要再下载模型包，解压到同一个文件夹。",
    "",
    "程序里的「本机设置 → 更新」可以直接检查并安装新版本（需要在该机器上放一个只读令牌，",
    "因为仓库是私有的）。",
  ].join("\n");
}

async function github(pathname, { method = "GET", token, body, contentType } = {}) {
  const headers = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "hexu-library-release",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (contentType) headers["Content-Type"] = contentType;
  const response = await fetch(pathname.startsWith("http") ? pathname : API + pathname, {
    method,
    headers,
    body,
  });
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { raw: text.slice(0, 300) };
  }
  return { ok: response.ok, status: response.status, payload };
}

/** Upload one archive. Streamed rather than buffered: 228 MB in memory for no reason.
 *
 *  Retried, because this network resets connections partway through: measured, roughly one TLS
 *  handshake in five fails, and a 228 MB upload is a long enough window to lose one — which is
 *  exactly how the first attempt at re-uploading the model ended (`ECONNRESET` on write, exit 1,
 *  nothing on the release). A 4xx is GitHub answering and is reported instead of retried; a 5xx or
 *  a dropped connection is worth another try.
 *
 *  GitHub's asset endpoint is not resumable, so an attempt starts over — and a failed attempt can
 *  leave a half-written asset behind, which makes the next one collide on the name. `cleanup` is
 *  called before every attempt after the first to remove it. */
async function upload(uploadUrl, asset, token, cleanup, attempts = 4) {
  const size = fs.statSync(asset.file).size;
  const url = uploadUrl.replace("{?name,label}", "") + `?name=${encodeURIComponent(asset.name)}`;

  for (let attempt = 1; attempt <= attempts; attempt++) {
    if (attempt > 1) {
      log(`  重试第 ${attempt} 次（共 ${attempts} 次）`);
      await cleanup(asset.name);
    }
    log(`上传 ${asset.name}（${megabytes(size)}）…`);
    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "hexu-library-release",
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/zip",
          "Content-Length": String(size),
        },
        body: fs.createReadStream(asset.file),
        duplex: "half",
      });
    } catch (error) {
      log(`  连接中断（${error.cause?.code ?? error.message}）`);
      await new Promise((resolve) => setTimeout(resolve, attempt * 3000));
      continue;
    }
    const payload = await response.json().catch(() => ({}));
    if (response.ok) return payload;
    if (response.status < 500) {
      fail(`上传 ${asset.name} 失败：HTTP ${response.status} ${payload.message ?? ""}`);
    }
    log(`  服务器返回 HTTP ${response.status}，稍后重试`);
    await new Promise((resolve) => setTimeout(resolve, attempt * 3000));
  }
  fail(`上传 ${asset.name} 连试 ${attempts} 次都没成功。网络恢复后重跑一次即可（--skip-build --assets-only）。`);
}

async function publish(version, commit, assets, token) {
  let release = await github(`/repos/${REPO}/releases/tags/v${version}`, { token });
  if (release.status === 404) {
    const created = await github(`/repos/${REPO}/releases`, {
      method: "POST",
      token,
      contentType: "application/json",
      body: JSON.stringify({
        tag_name: `v${version}`,
        target_commitish: commit,
        name: `和序图书馆 v${version}`,
        body: notes(version, commit),
        draft: false,
        prerelease: false,
      }),
    });
    if (!created.ok) fail(`创建发行版失败：HTTP ${created.status} ${created.payload?.message ?? ""}`);
    release = created;
    log(`已创建发行版 v${version}`);
  } else if (release.ok) {
    log(`发行版 v${version} 已存在，补传缺失的附件。`);
  } else {
    fail(`读取发行版失败：HTTP ${release.status} ${release.payload?.message ?? ""}`);
  }

  /** Remove a half-written asset of this name, so the next attempt does not collide with it.
   *  A failed upload can leave one behind — GitHub calls it a starter asset. */
  const cleanup = async (name) => {
    const current = await github(`/repos/${REPO}/releases/${release.payload.id}/assets`, { token });
    for (const asset of current.payload ?? []) {
      if (asset.name === name) {
        await github(`/repos/${REPO}/releases/assets/${asset.id}`, { method: "DELETE", token });
        log(`  清掉上一次留下的半成品 ${name}`);
      }
    }
  };

  const existing = new Map((release.payload?.assets ?? []).map((a) => [a.name, a]));
  for (const asset of assets) {
    const already = existing.get(asset.name);
    if (already && already.size === fs.statSync(asset.file).size) {
      log(`附件 ${asset.name} 已存在且大小一致，跳过。`);
      continue;
    }
    if (already) {
      // The upload endpoint refuses a duplicate name, so the stale one goes first.
      await github(`/repos/${REPO}/releases/assets/${already.id}`, { method: "DELETE", token });
      log(`已删除旧的同名附件 ${asset.name}`);
    }
    await upload(release.payload.upload_url, asset, token, cleanup);
  }
  return release.payload?.html_url;
}

/** The publishing token: the environment first, then the settings file the program keeps it in.

 *  One paste covers both jobs — the same value that lets the program check and install updates
 *  also lets this script publish them — so the token is stored in one place, the settings page,
 *  rather than also having to be set as an environment variable. The value is read here and used
 *  in the requests below; it is never printed, logged or written anywhere. */
function readToken() {
  const fromEnvironment = (process.env[TOKEN_VARIABLE] ?? "").trim();
  if (fromEnvironment) return fromEnvironment;

  // The user scope, where setx puts it: this shell's own environment was fixed when the session
  // started, so a token set afterwards is not in it even though it is set.
  try {
    const read = spawnSync(
      "powershell",
      ["-NoProfile", "-NonInteractive", "-Command",
       `[Environment]::GetEnvironmentVariable('${TOKEN_VARIABLE}','User')`],
      { cwd: root, encoding: "utf8" },
    );
    const value = (read.stdout ?? "").trim();
    if (value) return value;
  } catch {
    /* fall through to the settings file */
  }

  const settings = path.join(
    process.env.APPDATA ?? path.join(process.env.USERPROFILE ?? "", "AppData", "Roaming"),
    "hexu-library",
    "llm.env",
  );
  try {
    for (const line of fs.readFileSync(settings, "utf8").splitlines()) {
      const separator = line.indexOf("=");
      if (separator > 0 && line.slice(0, separator).trim() === "HEXU_GITHUB_TOKEN") {
        return line.slice(separator + 1).trim();
      }
    }
  } catch {
    /* No settings file: the environment was the only chance. */
  }
  return "";
}

const version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const prepareOnly = process.argv.includes("--prepare-only");
const assetsOnly = process.argv.includes("--assets-only");

log(`和序图书馆 · 发版 v${version}`);
const commit = preflight(version, assetsOnly);
log(`提交       ${commit.slice(0, 12)}`);

if (!process.argv.includes("--skip-build")) {
  log("打包（约两分钟）…");
  const build = run("node", [path.join("tools", "package-local.mjs")], { stdio: "inherit" });
  if (build.status !== 0) fail("打包失败，未发版。");
}

const assets = archive(version, !process.argv.includes("--no-model"));
for (const asset of assets) {
  log(`${asset.label}  ${asset.name}  ${megabytes(fs.statSync(asset.file).size)}  sha256 ${sha256(asset.file).slice(0, 16)}…`);
}

const token = readToken();
if (prepareOnly || !token) {
  if (!prepareOnly) {
    log("");
    log("没有找到访问令牌，因此只准备好文件、没有发布。");
    log("要自动发布，把细粒度 PAT（Contents: Read and write）粘到程序设置页的「访问令牌」一栏，");
    log("或放在环境变量 " + TOKEN_VARIABLE + " 里；也可以打开发行版页面自己把文件拖进去：");
  }
  for (const asset of assets) log("  " + asset.file);
  log("");
  log(`  发行版页面 https://github.com/${REPO}/releases/new?tag=v${version}`);
  process.exit(prepareOnly ? 0 : 1);
}

const url = await publish(version, commit, assets, token);
log("");
log(`完成：${url ?? `https://github.com/${REPO}/releases/tag/v${version}`}`);
