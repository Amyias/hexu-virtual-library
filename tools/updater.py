"""Keep the installed program in step with the Gitee repository.

The update is a source pull followed by a local rebuild, not a downloaded package, and the
reason is a hard constraint rather than a preference:

- The repository is private, so an anonymous download is refused outright.
- A Gitee release attachment may not exceed 100 MB, while the built program is about 327 MB —
  the speech model alone is 229 MB. It does not fit.
- The program must not carry a credential, so it cannot authenticate a download of its own.

What is left is the channel this machine already has: the checkout's own git access. Nothing
secret enters the program, and what gets updated is the whole program — the window, the server
and the site — because it is rebuilt from the source that was just pulled.

The consequence is stated plainly wherever it matters: a copy of the program without a source
checkout on the same machine cannot update itself, and says so instead of pretending.

Every git call here is fixed: no argument comes from a request, prompts are disabled (a program
with no console can never answer one — it would simply hang), and a timeout applies. Windows
would otherwise flash a console window for each call, so those are suppressed too.
"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

#: The repository this program updates itself from. Checked so a mistyped source directory
#: cannot make the updater pull from somewhere else entirely.
EXPECTED_REMOTE = "hexu-virtual-library"
BRANCH = "master"
GIT_TIMEOUT = 15
CACHE_SECONDS = 600
HELPER_NAME = "update.ps1"

#: Suppresses the console window a GUI process would otherwise flash for every git call.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_lock = threading.Lock()
_cache = {"at": 0.0, "payload": None}


def installed_version(site_root):
    """What this build was made from, as recorded by the packaging step."""
    try:
        return json.loads((Path(site_root) / "build-info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def source_directory(site_root, configured=""):
    """Where the checkout lives: what was configured, else where this build came from.

    A checkout running the server straight from source is itself the source directory, so that
    case answers for itself. A packaged build serves from its own bundle, which is not a
    checkout, and falls back to what the packaging step recorded."""
    if configured.strip():
        return Path(configured.strip()).expanduser()
    recorded = installed_version(site_root).get("source_dir")
    if recorded:
        return Path(recorded)
    site_root = Path(site_root)
    return site_root if (site_root / ".git").is_dir() else None


def _environment():
    env = dict(os.environ)
    # Nothing can answer a prompt, and a hang here would look like a frozen program.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=10"
    return env


def _git(source, args, timeout=GIT_TIMEOUT):
    """Run one git command. Returns (ok, output-or-error)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=_environment(), creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        return False, "找不到 git，无法检查更新"
    except subprocess.TimeoutExpired:
        return False, "git 超时（网络不通或被防火墙拦住）"
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"
    text = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        return False, error or text or f"git 退出码 {result.returncode}"
    return True, text


def _blocked(source):
    """Why an update cannot be applied, or None when it can. Ordered by how early it bites."""
    if source is None:
        return "没有配置源码目录，无法自更新"
    if not (source / ".git").is_dir():
        return f"源码目录不是一个 git 仓库：{source}"
    ok, remote = _git(source, ["remote", "get-url", "origin"])
    if not ok:
        return f"读不到 git 远端：{remote}"
    if EXPECTED_REMOTE not in remote:
        return f"源码目录的远端不是本项目：{remote}"
    return None


def status(site_root, source, refresh=False):
    """Everything the page and `--check-update` need, including a plain-language reason."""
    with _lock:
        now = time.time()
        if not refresh and _cache["payload"] and now - _cache["at"] < CACHE_SECONDS:
            return _cache["payload"]
        payload = _inspect(site_root, source)
        _cache.update(at=now, payload=payload)
        return payload


def _inspect(site_root, source):
    installed = installed_version(site_root)
    payload = {
        "installed": {
            "commit": installed.get("commit", ""),
            "built_at": installed.get("built_at", ""),
            "version": installed.get("version", ""),
        },
        "source_dir": str(source) if source else "",
        "state": "unknown",
        "reason": "",
        "behind": 0,
        "commits": [],
        "can_apply": False,
    }

    blocked = _blocked(source)
    if blocked:
        payload.update(state="no-source", reason=blocked)
        return payload

    # Untracked files are ignored on purpose: they cannot make --ff-only fail, and git refuses
    # to overwrite one by itself. What blocks an update is an uncommitted change to a tracked
    # file, which is what this reports.
    ok, dirty = _git(source, ["status", "--porcelain", "--untracked-files=no"])
    if not ok:
        payload.update(state="error", reason=f"无法读取源码目录状态：{dirty}")
        return payload
    payload["dirty"] = bool(dirty)

    ok, error = _git(source, ["fetch", "--quiet", "origin", BRANCH], timeout=25)
    if not ok:
        payload.update(state="error", reason=f"无法连接 Gitee：{error}")
        return payload
    ok, remote_commit = _git(source, ["rev-parse", f"origin/{BRANCH}"])
    if not ok:
        payload.update(state="error", reason=f"读不到远端提交：{remote_commit}")
        return payload
    payload["latest_commit"] = remote_commit[:12]

    if payload["dirty"]:
        payload.update(state="dirty", reason="源码目录有未提交的改动，请先提交或撤销后再更新")
        return payload

    installed_commit = installed.get("commit", "")
    if not installed_commit:
        # A build made where git was unavailable carries no provenance. Rebuilding is the fix,
        # and it is harmless, so it is offered rather than refused.
        payload.update(
            state="unknown",
            reason="这个构建没有版本标记，无法判断是否最新；重新构建一次即可对齐",
            can_apply=True,
        )
        return payload
    if installed_commit == remote_commit:
        payload.update(state="up-to-date", reason="已经是最新版本")
        return payload

    # How far behind, and what is in between. An installed commit the local repository does not
    # know about cannot be compared — that is still worth updating, just without the count.
    behind, commits = 0, []
    ok, count = _git(source, ["rev-list", "--count", f"{installed_commit}..origin/{BRANCH}"])
    if ok and count.isdigit():
        behind = int(count)
    if behind:
        ok, log = _git(source, ["log", "--oneline", "--max-count=20",
                                f"{installed_commit}..origin/{BRANCH}"])
        if ok:
            commits = [line.strip() for line in log.splitlines() if line.strip()]

    # Commits the reader made locally would make --ff-only refuse; say so now rather than let
    # the update spend two minutes and then fail.
    ahead = 0
    ok, count = _git(source, ["rev-list", "--count", f"origin/{BRANCH}..HEAD"])
    if ok and count.isdigit():
        ahead = int(count)

    if not behind and not commits:
        payload.update(
            state="update-available",
            reason="本地仓库与已安装的版本对不上（已安装的提交不在源码历史里），建议重新构建",
            can_apply=True,
        )
        return payload

    if ahead:
        payload.update(
            state="ahead",
            reason=f"源码目录有 {ahead} 个尚未推送的本地提交，先推送或撤销后再更新",
            behind=behind, commits=commits,
        )
        return payload

    payload.update(
        state="update-available",
        reason=f"有 {behind} 个新提交" if behind else "有可用的更新",
        behind=behind, commits=commits, can_apply=True,
    )
    return payload


#: The update helper. PowerShell so that a UTF-8 file with a BOM is decoded correctly — a .cmd
#: read in the console code page turns Chinese into mojibake, which is a trap this project has
#: already been caught by once. Paths come from $PSScriptRoot, so no path literal appears here.
HELPER = r"""# 和序图书馆 · 更新助手（由程序生成，可以随时删除）
$ErrorActionPreference = 'Continue'
$source = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $source 'dist\和序图书馆\和序图书馆.exe'
Start-Transcript -Path (Join-Path $PSScriptRoot 'update.log') -Append | Out-Null
Write-Host ''
Write-Host '和序图书馆 · 正在更新' -ForegroundColor Green
Write-Host "源码目录 $source"
$env:GIT_TERMINAL_PROMPT = '0'

# 1. 等程序退出：先请它关闭，十秒后仍在就强制结束
$program = Get-Process -Id __PID__ -ErrorAction SilentlyContinue
if ($program) {
  Write-Host '等待程序退出…'
  $null = $program.CloseMainWindow()
  for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if (-not (Get-Process -Id __PID__ -ErrorAction SilentlyContinue)) { break }
  }
  if (Get-Process -Id __PID__ -ErrorAction SilentlyContinue) { Stop-Process -Id __PID__ -Force }
}
Start-Sleep -Milliseconds 400

# 2. 拉取更新
Write-Host '从 Gitee 拉取更新…'
git -C $source -c 'core.sshCommand=ssh -o BatchMode=yes' pull --ff-only
if ($LASTEXITCODE -ne 0) {
  Write-Host '拉取失败，程序保持原样，未做任何改动。' -ForegroundColor Red
  Read-Host '按回车关闭这个窗口'
  exit 1
}

# 3. 重新打包（约两分钟）
Write-Host '重新打包，约需两分钟…' -ForegroundColor Cyan
node (Join-Path $source 'tools\package-local.mjs')
if ($LASTEXITCODE -ne 0) {
  Write-Host '打包失败，程序保持原样。' -ForegroundColor Red
  Read-Host '按回车关闭这个窗口'
  exit 1
}

# 4. 重新打开
Write-Host '更新完成，正在重新打开程序…' -ForegroundColor Green
Start-Process -FilePath $exe
Stop-Transcript | Out-Null
Write-Host '这个窗口可以关掉了。'
Start-Sleep -Seconds 4
exit 0
"""


def write_helper(source, pid):
    """Write the update helper next to the checkout and return its path."""
    directory = source / ".cache"
    directory.mkdir(parents=True, exist_ok=True)
    helper = directory / HELPER_NAME
    # utf-8-sig: PowerShell 5.1 decodes a BOM-less script using the console code page and would
    # turn every Chinese string in it into mojibake — silently.
    helper.write_text(HELPER.replace("__PID__", str(int(pid))), encoding="utf-8-sig")
    return helper


def start(source, site_root, pid):
    """Launch the update helper in its own console window. Returns (ok, message)."""
    # Checked again, and freshly: everything that could make the pull fail (no network, a dirty
    # tree, commits only this machine has) is worth catching before the program closes itself.
    site = status(site_root, source, refresh=True)
    if not site.get("can_apply"):
        return False, site.get("reason") or "当前状态无法更新"
    try:
        helper = write_helper(source, pid)
    except OSError as error:
        return False, f"无法写入更新脚本：{error}"
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            cwd=str(source),
            # Its own window on purpose: the rebuild takes a couple of minutes and its progress
            # is the only honest thing to show for it.
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            close_fds=True,
        )
    except Exception as error:
        return False, f"无法启动更新脚本：{type(error).__name__}: {error}"
    return True, "程序即将关闭，随后自动拉取并重新打包，完成后会重新打开（约两分钟）。"
