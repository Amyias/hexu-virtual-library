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
    node tools/release.mjs --assets-only --model-only  repair the existing release's model only

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
import { matchesArchive, requireModelForSkip, requireCompleteRelease } from "./release-policy.mjs";

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

  const head = run("git", ["rev-parse", "HEAD"]).stdout.trim();
  // Remote checks use the authenticated API in publish(); no named github remote is required.
  return head;
}

/** The two archives. Both unpack at the install root: the program archive is everything except
 *  the model, the model archive is the model under the path it belongs at.
 *
 *  Every release carries both files. --model-only repairs an existing release without replacing
 *  its program; --no-model is restricted to an already verified model in that same release. */
function archive(version, withModel, modelOnly = false) {
  if (!modelOnly && !fs.existsSync(path.join(APP_DIR, `${APP}.exe`))) {
    fail(`先打包：${APP_DIR} 里没有程序。运行 node tools/package-local.mjs`);
  }
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const program = path.join(OUT_DIR, `hexu-library-${version}-program.zip`);
  const model = path.join(OUT_DIR, `sense-voice-${version}.zip`);
  for (const file of [modelOnly ? null : program, withModel ? model : null].filter(Boolean)) fs.rmSync(file, { force: true });

  // Python writes the archives, not tar: `tar -a -f x.zip` produces a plain tar with a zip name
  // (GNU tar has no zip compressor), which every zip reader refuses while PowerShell's
  // Expand-Archive "succeeds" by extracting nothing. That is how an install got mirrored over
  // with emptiness. tools/make-archive.py writes a real zip and reads it back to prove it.
  const python = fs.existsSync(path.join(root, ".cache", "venv", "Scripts", "python.exe"))
    ? path.join(root, ".cache", "venv", "Scripts", "python.exe")
    : "python";

  const assets = [];
  if (!modelOnly) {
    const entries = fs.readdirSync(APP_DIR);
    const madeProgram = run(
      python,
      [
        path.join("tools", "make-archive.py"), program, APP_DIR, ...entries,
        "--exclude", "_internal/models",
      ],
      { stdio: "inherit" },
    );
    if (madeProgram.status !== 0) fail("切程序包失败。");
    assets.push({ file: program, name: path.basename(program), label: "程序包（不含模型）" });
  }
  if (!withModel) {
    log("（--no-model：发布前必须确认当前发行版已有完整模型附件）");
    return assets;
  }

  if (!fs.existsSync(path.join(APP_DIR, "_internal", "models"))) fail("模型目录不存在，不能生成模型包。请先运行 tools/package-local.mjs。");
  const madeModel = run(
    python,
    [
      path.join("tools", "make-archive.py"), model, APP_DIR, "_internal/models",
      // Deflating 228 MB of int8 weights saves almost nothing and costs a minute.
      "--store",
      "--require", "_internal/models/sense-voice/model.int8.onnx",
      "--require", "_internal/models/sense-voice/tokens.txt",
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
  return [
    `和序图书馆 v${version}`,
    "",
    `提交 \`${commit.slice(0, 12)}\``,
    "",
    "### 本版包含的提交",
    log15,
    "",
    "### 怎么装",
    "1. 下载 `*-program.zip`，解压覆盖到程序文件夹（模型原地保留，不会被覆盖）。",
    `2. 新机器还需要下载本发行版的 \`sense-voice-${version}.zip\`，解压到同一个文件夹；已有模型的机器更新时只下载程序包。`,
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

/** What GitHub actually objected to. A 422 carries an `errors` list naming the field, and hiding
 *  it turns a one-line fix into a guessing game. */
function why(result) {
  const errors = result.payload?.errors;
  if (Array.isArray(errors) && errors.length) {
    return errors.map((e) => `${e.resource ?? ""}${e.field ? "." + e.field : ""}: ${e.message ?? JSON.stringify(e)}`).join("；");
  }
  return result.payload?.message ?? "";
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

async function publish(version, commit, assets, token, assetsOnly, skipModel) {
  let createdDraft = false;
  let release = await github(`/repos/${REPO}/releases/tags/v${version}`, { token });
  if (skipModel) requireModelForSkip(version, release.ok ? release.payload : null);
  if (release.status === 404) {
    if (assetsOnly) fail(`v${version} 不存在，--assets-only 不允许创建新发行版。`);
    const remote = await github(`/repos/${REPO}/git/ref/heads/master`, { token });
    if (!remote.ok || remote.payload?.object?.sha !== commit) fail("GitHub master 尚未包含当前提交，请先推送再发版。");
    const tag = await github(`/repos/${REPO}/git/ref/tags/v${version}`, { token });
    if (tag.status !== 404) fail(`标签检查失败或 v${version} 标签已存在，不创建发行版。`);
    const created = await github(`/repos/${REPO}/releases`, {
      method: "POST",
      token,
      contentType: "application/json",
      body: JSON.stringify({
        tag_name: `v${version}`,
        target_commitish: commit,
        name: `和序图书馆 v${version}`,
        body: notes(version, commit),
        draft: true,
        prerelease: false,
      }),
    });
    if (!created.ok) fail(`创建发行版失败：HTTP ${created.status} ${why(created)}`);
    release = created;
    createdDraft = true;
    log(`已创建发行草稿 v${version}，附件完整后才公开发布。`);
  } else if (release.ok) {
    if (!assetsOnly) fail(`v${version} 已存在，补传附件请使用 --assets-only。`);
    log(`发行版 v${version} 已存在，补传缺失的附件。`);
  } else {
    fail(`读取发行版失败：HTTP ${release.status} ${why(release)}`);
  }

  /** Remove a half-written asset of this name, so the next attempt does not collide with it.
   *  A failed upload can leave one behind — GitHub calls it a starter asset. */
  const cleanup = async (name) => {
    const current = await github(`/repos/${REPO}/releases/${release.payload.id}/assets`, { token });
    if (!current.ok || !Array.isArray(current.payload)) fail(`读取待清理附件失败：HTTP ${current.status}`);
    for (const asset of current.payload ?? []) {
      if (asset.name === name) {
        const removed = await github(`/repos/${REPO}/releases/assets/${asset.id}`, { method: "DELETE", token });
        if (!removed.ok) fail(`清理附件失败：HTTP ${removed.status}`);
        log(`  清掉上一次留下的半成品 ${name}`);
      }
    }
  };

  const existing = new Map((release.payload?.assets ?? []).map((a) => [a.name, a]));
  for (const asset of assets) {
    const already = existing.get(asset.name);
    if (matchesArchive(already, fs.statSync(asset.file).size, sha256(asset.file))) {
      log(`附件 ${asset.name} 已上传且大小和 SHA-256 一致，跳过。`);
      continue;
    }
    if (already) {
      // The upload endpoint refuses a duplicate name, so the stale one goes first.
      const removed = await github(`/repos/${REPO}/releases/assets/${already.id}`, { method: "DELETE", token });
      if (!removed.ok) fail(`删除旧附件失败：HTTP ${removed.status}`);
      log(`已删除旧的同名附件 ${asset.name}`);
    }
    await upload(release.payload.upload_url, asset, token, cleanup);
  }
  const verified = await github(`/repos/${REPO}/releases/tags/v${version}`, { token });
  if (!verified.ok) fail(`发布后读取附件失败：HTTP ${verified.status}`);
  requireCompleteRelease(version, verified.payload);
  for (const asset of assets) {
    const remote = verified.payload.assets.find(item => item.name === asset.name);
    if (!matchesArchive(remote, fs.statSync(asset.file).size, sha256(asset.file))) fail(`上传后校验失败：${asset.name}`);
  }
  if (createdDraft || verified.payload.draft) {
    const published = await github(`/repos/${REPO}/releases/${verified.payload.id}`, {
      method: "PATCH", token, contentType: "application/json", body: JSON.stringify({ draft: false }),
    });
    if (!published.ok || published.payload?.draft) fail(`附件已齐全但发布草稿失败：HTTP ${published.status}`);
  }
  log("程序包与模型包均已上传，状态、大小和 SHA-256 校验通过。");
  return release.payload?.html_url;
}

/** Publishing credentials come only from the environment, never from settings files. */
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
    /* No configured user environment. */
  }

  return "";
}

const version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const prepareOnly = process.argv.includes("--prepare-only");
const assetsOnly = process.argv.includes("--assets-only");
const modelOnly = process.argv.includes("--model-only");
const skipModel = process.argv.includes("--no-model");
if (modelOnly && (!assetsOnly || skipModel)) fail("--model-only 必须搭配 --assets-only，且不能与 --no-model 同用。");

log(`和序图书馆 · 发版 v${version}`);
const commit = preflight(version, assetsOnly);
log(`提交       ${commit.slice(0, 12)}`);

if (!modelOnly && !process.argv.includes("--skip-build")) {
  log("打包（约两分钟）…");
  const build = run("node", [path.join("tools", "package-local.mjs")], { stdio: "inherit" });
  if (build.status !== 0) fail("打包失败，未发版。");
}

const assets = archive(version, !skipModel, modelOnly);
for (const asset of assets) {
  log(`${asset.label}  ${asset.name}  ${megabytes(fs.statSync(asset.file).size)}  sha256 ${sha256(asset.file).slice(0, 16)}…`);
}

const token = prepareOnly ? "" : readToken();
if (prepareOnly || !token) {
  if (!prepareOnly) {
    log("");
    log("没有找到访问令牌，因此只准备好文件、没有发布。");
    log("要自动发布，请将细粒度 PAT（Contents: Read and write）配置在环境变量 " + TOKEN_VARIABLE + " 中；也可以手动上传：");
  }
  for (const asset of assets) log("  " + asset.file);
  log("");
  log(`  发行版页面 https://github.com/${REPO}/releases/new?tag=v${version}`);
  process.exit(prepareOnly ? 0 : 1);
}

const url = await publish(version, commit, assets, token, assetsOnly, skipModel);
log("");
log(`完成：${url ?? `https://github.com/${REPO}/releases/tag/v${version}`}`);
