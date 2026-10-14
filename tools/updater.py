"""Keep the installed program in step with the released versions.

An update is a download now, not a rebuild. The program asks GitHub for the latest release,
downloads the program archive, checks it against the digest GitHub publishes, and hands the
swap to a small helper that unpacks it while the program is closed. Nothing here needs a source
checkout, git, Node or a compiler: a copy of the program plus a read token is enough, which is
what makes this work on a machine that only ever received the built folder.

Two things about this network shaped the design, both measured rather than assumed:

- The asset host fails roughly one TLS handshake in five, and a 99 MB archive takes about thirty
  seconds to arrive. A single-attempt download would simply not finish often enough, so the
  download retries and resumes with a Range request — a resumed attempt costs only the part that
  is missing.
- The model is 228 MB and never changes. It therefore travels as its own release asset and is
  fetched only by a machine that does not have it, keeping routine updates at ~99 MB.

The repository is private, so the API needs a token. It is passed in per call and never copied,
cached in a file, or written into a URL — and the redirect handler below makes sure it is not
sent on to the second host that serves the actual bytes.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

#: Where releases are published.
REPO = "Amyias/hexu-virtual-library"
API = "https://api.github.com"
#: Asset names carry the version, so they are matched by these fragments.
PROGRAM_ASSET = "-program.zip"
MODEL_ASSET = "sense-voice-"
MODEL_RELATIVE = Path("_internal") / "models" / "sense-voice" / "model.int8.onnx"

CACHE_SECONDS = 600
REQUEST_TIMEOUT = 30
DOWNLOAD_ATTEMPTS = 6
WORK_DIR_NAME = "hexu-library-update"
HELPER_NAME = "update.ps1"
SPEC_NAME = "update.json"

_lock = threading.Lock()
_cache = {"at": 0.0, "payload": None, "identity": None}
_progress = {"state": "idle", "message": ""}
#: Set when a download finishes or gives up, so a program whose window is closed mid-download can
#: wait for it instead of taking it down with the process.
_finished = threading.Event()
BUSY_STATES = ("checking", "downloading", "retrying", "installing")


# --- talking to GitHub --------------------------------------------------------
class _DropTokenBeyondGitHub(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but do not carry the token to another host.

    A private repository's asset download answers with a redirect to
    release-assets.githubusercontent.com carrying a signed, expiring URL — the signature is the
    authentication there, and the token has no business travelling to a second host."""

    def redirect_request(self, request, fp, code, msg, headers, new_url):
        redirected = super().redirect_request(request, fp, code, msg, headers, new_url)
        if redirected is not None:
            host = urllib.parse.urlsplit(new_url).hostname or ""
            if not host.endswith("github.com"):
                redirected.remove_header("Authorization")
        return redirected


def _opener():
    # No proxy handling of our own: a machine-wide proxy setting must not decide whether an update
    # can be fetched.
    return urllib.request.build_opener(_DropTokenBeyondGitHub, urllib.request.ProxyHandler({}))


def _headers(token, accept):
    headers = {
        "Accept": accept,
        "User-Agent": "hexu-library-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _repository_visible(token):
    """Whether the token can see the repository at all — used to read a 404 correctly."""
    try:
        _api(f"/repos/{REPO}", token)
        return True
    except Exception:
        return False


def _api(path, token, attempts=4):
    """One API call, retried.

    The API itself is small and quick, but this network drops connections: measured, roughly one
    TLS handshake in five fails, and a fresh connection is the flakiest thing there is. Reporting
    that as "cannot reach GitHub" makes the reader retry by hand for no reason — and it is exactly
    what happened the first time this ran end to end. An HTTP error, by contrast, is a real answer
    from GitHub and is never retried."""
    last = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            API + path, headers=_headers(token, "application/vnd.github+json")
        )
        try:
            with _opener().open(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except Exception as error:
            last = error
            if attempt < attempts:
                time.sleep(min(1.5 * attempt, 6))
    raise last


# --- what is installed --------------------------------------------------------
def installed(site_root):
    """What this build was made from, as the packaging step recorded it."""
    try:
        return json.loads((Path(site_root) / "build-info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def version_tuple(text):
    """v2.10.0 compares greater than 2.9.0, and anything unparsable compares as oldest."""
    numbers = re.findall(r"\d+", text or "")
    return tuple(int(number) for number in numbers[:3]) if numbers else (0,)


def has_model(install_root):
    """Whether this install carries the model already — checked before downloading 228 MB of it.
    A source checkout has no install folder, so it has no model in this sense either."""
    return bool(install_root) and (Path(install_root) / MODEL_RELATIVE).is_file()


# --- status -------------------------------------------------------------------
def status(site_root, install_root, token, refresh=False):
    """What the settings page and `--check-update` show, including a plain-language reason."""
    with _lock:
        now = time.time()
        identity = hashlib.sha256(token.encode()).hexdigest()
        if (not refresh and _cache["payload"] and _cache["identity"] == identity
                and now - _cache["at"] < CACHE_SECONDS):
            return _cache["payload"]
        payload = _inspect(site_root, install_root, token)
        _cache.update(at=now, payload=payload, identity=identity)
        return payload


def _inspect(site_root, install_root, token):
    info = installed(site_root)
    payload = {
        "installed": {
            "version": info.get("version", ""),
            "commit": info.get("commit", ""),
            "built_at": info.get("built_at", ""),
        },
        "install_root": str(install_root or ""),
        "latest": None,
        "state": "unknown",
        "reason": "",
        "can_apply": False,
        "needs_token": not bool(token),
        "needs_model": not has_model(install_root),
    }

    if install_root is None:
        payload.update(
            state="not-packaged",
            reason="这是源码运行（未打包），不参与自更新；打包后的程序才会从发行版更新",
        )
        return payload
    if not token:
        payload.update(
            state="no-token",
            reason="未配置访问令牌：仓库是私有的，检查与安装更新都需要一个令牌（只读即可）",
        )
        return payload

    try:
        release = _api(f"/repos/{REPO}/releases/latest", token)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            # Three different situations all answer 404 here: the repository does not exist, the
            # token cannot see it, or it simply has no releases yet. Asking for the repository
            # itself settles which one it is, so the reader is not told to check a token that
            # is perfectly fine.
            if _repository_visible(token):
                payload.update(state="no-release", reason="这个仓库还没有发布任何发行版")
            else:
                payload.update(state="error", reason="GitHub 返回 404：仓库地址不对，或令牌没有权限（私有仓库两种情况都是 404）")
        elif error.code in (401, 403):
            payload.update(state="error", reason=f"令牌无效或权限不足（HTTP {error.code}）")
        else:
            payload.update(state="error", reason=f"GitHub 返回 HTTP {error.code}")
        return payload
    except Exception as error:
        payload.update(state="error", reason=f"连不上 GitHub（{type(error).__name__}），稍后再试")
        return payload

    tag = release.get("tag_name") or ""
    assets = [
        {
            "name": asset.get("name", ""),
            "size": asset.get("size", 0),
            "url": asset.get("url", ""),
            "digest": asset.get("digest") or "",
        }
        for asset in release.get("assets", [])
    ]
    payload["latest"] = {
        "tag": tag,
        "version": tag.lstrip("v"),
        "published_at": release.get("published_at", ""),
        "notes": (release.get("body") or "").strip()[:1600],
        "assets": assets,
    }

    current = info.get("version", "")
    if not current:
        current = "0.0.0"
    if version_tuple(tag) <= version_tuple(current):
        payload.update(state="up-to-date", reason=f"已经是最新版本（{current}）")
        return payload

    program = next((asset for asset in assets if PROGRAM_ASSET in asset["name"]), None)
    if not program:
        payload.update(state="error", reason=f"发行版 {tag} 里没有程序包附件，无法自动更新")
        return payload
    payload["program_asset"] = program
    # Only looked for when a machine actually needs it: the model never changes between versions,
    # so a release does not have to re-upload 228 MB of it, and the model archive from the newest
    # release that carries one is the same bytes.
    payload["model_asset"] = None
    if payload["needs_model"]:
        payload["model_asset"] = _model_asset(token, assets)
        if not payload["model_asset"]:
            payload.update(state="error", reason="本机缺少模型，发行版也没有可用模型包，暂不更新")
            return payload
    payload.update(
        state="update-available",
        can_apply=True,
        reason=f"有新版 {tag}（当前 {current}）",
    )
    return payload


def _model_asset(token, assets):
    """The model archive to use, from this release or from the newest one that carries it.

    The model does not change between versions, so re-uploading 228 MB with every release is waste
    — and on this network, waste with a one-in-five failure rate. A release therefore only needs a
    program archive; a machine that lacks the model gets it from whichever release has one."""
    here = next((asset for asset in assets if MODEL_ASSET in asset["name"]), None)
    if here:
        return here
    try:
        releases = _api(f"/repos/{REPO}/releases?per_page=20", token)
    except Exception:
        return None
    for release in releases:
        for asset in release.get("assets", []):
            if MODEL_ASSET in (asset.get("name") or ""):
                return {
                    "name": asset.get("name", ""),
                    "size": asset.get("size", 0),
                    "url": asset.get("url", ""),
                    "digest": asset.get("digest") or "",
                }
    return None


# --- downloading --------------------------------------------------------------
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fetch_to(asset, target, token, label, offset):
    """One attempt: stream the asset into `target`, appending when `offset` is non-zero."""
    request = urllib.request.Request(
        asset["url"],
        headers=_headers(token, "application/octet-stream"),
    )
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    written = offset
    with _opener().open(request, timeout=REQUEST_TIMEOUT) as response:
        # A server that ignores the Range header answers 200 with the whole file; honour that by
        # starting the file over rather than appending to a prefix.
        mode = "ab" if offset and response.status == 206 else "wb"
        if mode == "wb":
            written = 0
        with open(target, mode) as handle:
            while True:
                block = response.read(256 * 1024)
                if not block:
                    break
                handle.write(block)
                written += len(block)
                _progress.update(bytes=written, state="downloading", message=f"正在下载{label}")
    return written


def _download(asset, target, token, label):
    """Fetch one asset, resuming after a break and retrying.

    Roughly one TLS handshake in five fails against the asset host on this network, and a 99 MB
    transfer is a long enough window to lose one. Retrying is therefore not politeness — it is the
    only way the download finishes — and a resumed attempt costs only what is missing."""
    target = Path(target)
    total = int(asset.get("size") or 0)
    digest = (asset.get("digest") or "").split(":")[-1] if asset.get("digest") else ""
    if total <= 0 or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        _progress.update(state="failed", message=f"{label}缺少有效大小或 SHA-256，未安装")
        return False
    _progress.update(state="downloading", label=label, bytes=0, total=total, message=f"正在下载{label}")

    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        offset = target.stat().st_size if target.exists() else 0
        if total and offset > total:
            target.unlink()
            offset = 0
        try:
            _fetch_to(asset, target, token, label, offset)
        except Exception as error:
            _progress.update(
                state="retrying",
                message=f"{label} 第 {attempt} 次失败（{type(error).__name__}），重试…",
            )
            time.sleep(min(1.5 * attempt, 8))
            continue
        if total and target.stat().st_size != total:
            _progress.update(state="retrying", message=f"{label} 只收到 {target.stat().st_size}/{total} 字节，继续…")
            time.sleep(1)
            continue
        if digest and _sha256(target) != digest:
            # A wrong file is worse than no file, and it is cheap to notice now.
            target.unlink()
            _progress.update(state="retrying", message=f"{label} 校验不符，重新下载…")
            continue
        _progress.update(state="downloaded", message=f"{label} 下载完成")
        return True

    _progress.update(state="failed", message=f"{label} 多次尝试后仍未下载成功")
    return False


# --- swapping in the new version ---------------------------------------------
#: The helper, in PowerShell because a UTF-8 file with a BOM is decoded correctly: a .cmd read in
#: the console code page turns Chinese into mojibake, a trap this project has already been caught
#: by. Every path it needs arrives through update.json rather than the command line, for the same
#: reason — non-ASCII arguments do not survive PowerShell's own parsing.
HELPER = Path(__file__).with_name("update-helper.ps1").read_text(encoding="utf-8")


def work_dir():
    """Where downloads and the helper live. Outside the program folder on purpose: the install
    directory may be anywhere, and none of this belongs in it."""
    directory = Path(tempfile.gettempdir()) / WORK_DIR_NAME / uuid.uuid4().hex
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_helper(directory, install_root, program_zip, model_zip, pid, restart_args=(), expected_version=""):
    # Only supported non-secret switches can cross into the helper's on-disk spec.
    arguments = []
    port = 8090
    for index, argument in enumerate(restart_args):
        if argument in ("--no-browser", "--browser", "--window"):
            arguments.append(argument)
        elif argument == "--port" and index + 1 < len(restart_args):
            value = str(restart_args[index + 1])
            if value.isdigit() and 0 < int(value) < 65536:
                port = int(value)
                arguments.extend(("--port", str(port)))
    spec = {
        "install": str(install_root),
        "programZip": program_zip.name,
        "modelZip": model_zip.name if model_zip else "",
        "pid": int(pid),
        "runId": uuid.uuid4().hex,
        "restartArgs": arguments,
        "restartPort": port,
        "executable": Path(sys.executable).name if getattr(sys, "frozen", False) else "和序图书馆.exe",
        "expectedVersion": expected_version,
    }
    (directory / SPEC_NAME).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    helper = directory / HELPER_NAME
    helper.write_text(HELPER, encoding="utf-8-sig")
    return helper


def begin(site_root, install_root, token, pid, on_ready, restart_args=()):
    """Download in the background, then hand over to the helper. Returns (ok, message).

    Downloading here — inside the running program, with the page able to show progress — is what
    keeps the machine down for seconds instead of minutes: the helper only has to unpack and
    relaunch."""
    with _lock:
        if _progress.get("state") in BUSY_STATES:
            return False, "已经在下载更新了，请稍候。"
        _progress.clear()
        _progress.update(state="checking", message="正在检查更新…")
        _finished.clear()

    if install_root is None:
        _progress.update(state="idle", message="")
        return False, "这是源码运行（未打包），请用打包后的程序更新"
    payload = status(site_root, install_root, token, refresh=True)
    if not payload.get("can_apply"):
        _progress.update(state="idle", message="")
        return False, payload.get("reason") or "当前状态无法更新"

    threading.Thread(
        target=_apply, args=(payload, install_root, token, pid, on_ready, restart_args), daemon=True
    ).start()
    return True, "正在下载更新，页面会显示进度；下载完成后程序会自动关闭并重新打开。"


def _apply(payload, install_root, token, pid, on_ready, restart_args=()):
    try:
        _apply_inner(payload, install_root, token, pid, on_ready, restart_args)
    finally:
        _finished.set()


def _apply_inner(payload, install_root, token, pid, on_ready, restart_args=()):
    directory = work_dir()
    program = payload["program_asset"]
    program_zip = directory / program["name"]
    try:
        if not _download(program, program_zip, token, "程序包"):
            _progress.update(state="failed", message="程序包下载失败，未做任何改动")
            return
        # Validate before closing the working app, including archives with a misleading .zip name.
        with zipfile.ZipFile(program_zip) as archive:
            if archive.testzip() is not None:
                raise ValueError("程序包 CRC 校验失败")
            executable = Path(sys.executable).name if getattr(sys, "frozen", False) else "和序图书馆.exe"
            if archive.getinfo(executable).file_size <= 0:
                raise ValueError("程序包缺少可运行文件")
            info = json.loads(archive.read("_internal/build-info.json"))
            if info.get("version") != payload.get("latest", {}).get("version"):
                raise ValueError("程序包版本与发行版不一致")
            for entry in archive.namelist():
                parts = entry.replace("\\", "/").split("/")
                if entry.startswith(("/", "\\")) or ".." in parts or ":" in entry:
                    raise ValueError("程序包包含不安全路径")

        model_zip = None
        if payload.get("needs_model") and payload.get("model_asset"):
            asset = payload["model_asset"]
            candidate = directory / asset["name"]
            if _download(asset, candidate, token, "语音识别模型"):
                with zipfile.ZipFile(candidate) as archive:
                    if archive.testzip() is not None:
                        raise ValueError("模型包 CRC 校验失败")
                    for name in ("model.int8.onnx", "tokens.txt"):
                        if archive.getinfo("_internal/models/sense-voice/" + name).file_size <= 0:
                            raise ValueError("模型包不完整")
                model_zip = candidate
            else:
                _progress.update(state="failed", message="模型包下载失败，未做任何改动")
                return

        _progress.update(state="installing", message="下载完成，正在安装…")
        helper = _write_helper(directory, install_root, program_zip, model_zip, pid,
                               restart_args, payload.get("latest", {}).get("version", ""))
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            cwd=str(directory),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        # The helper waits for this process to disappear before touching a single file.
        on_ready()
    except Exception as error:
        _progress.update(state="failed", message=f"更新未能完成：{type(error).__name__}: {error}")


def progress():
    with _lock:
        return dict(_progress)


def busy():
    """Whether an update is being downloaded or installed right now."""
    return _progress.get("state") in BUSY_STATES


def wait(seconds):
    """Block until the download settles. Returns True when it finished, False on timeout."""
    return _finished.wait(seconds)
