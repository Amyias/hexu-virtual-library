"""Bounded Schannel/IPv4 fallback for compiled-in HTTPS book origins."""
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from email.parser import BytesParser
from urllib.parse import urljoin, urlsplit

from source_rules import SourceError

HOSTS = {"cn.shubaoc.com", "tianyashuku.net", "www.wyshu.com"}
HEADER_LIMIT = 65536


def client_path():
    if os.name != "nt":
        return None
    root = os.environ.get("SystemRoot")
    path = Path(root) / "System32" / "curl.exe" if root else None
    return path if path and path.is_file() else None


def _run(arguments, payload, limit, timeout):
    # No shell, curlrc, credentials, files, or raw diagnostic output. A watchdog and bounded
    # pipe read also protect older system curl versions whose max-filesize needs Content-Length.
    with subprocess.Popen(arguments, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        def stop():
            try:
                if process.poll() is None:
                    process.kill()
            except OSError:
                pass  # The same process may have finished between poll() and kill().
        watchdog = threading.Timer(timeout, stop)
        watchdog.daemon = True
        watchdog.start()
        try:
            if payload is not None:
                try:
                    process.stdin.write(payload)
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            output = process.stdout.read(limit + 1)
            if len(output) > limit:
                process.kill()
                process.wait()
                return 63, b""
            process.wait()
            return process.returncode, output
        finally:
            if process.poll() is None:
                process.kill()
            watchdog.cancel()


def _origin(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in HOSTS or parts.port not in {None, 443}
            or parts.username or parts.password or parts.fragment):
        raise SourceError("系统 HTTPS 重试仅接受内置书源的本站安全地址")
    return parts.hostname


def _response(raw, maximum):
    consumed = 0
    for _ in range(8):
        header, separator, body = raw.partition(b"\r\n\r\n")
        consumed += len(header) + 4
        if not separator or consumed > HEADER_LIMIT:
            raise SourceError("系统 HTTPS 重试返回的响应头无效或过大")
        status_line, _, fields = header.partition(b"\r\n")
        match = re.fullmatch(rb"HTTP/[\d.]+\s+(\d{3})(?:\s+.*)?", status_line)
        if not match:
            raise SourceError("系统 HTTPS 重试未收到有效的 HTTP 响应")
        status = int(match[1])
        if status in {100, 102, 103}:
            raw = body
            continue
        if len(body) > maximum:
            raise SourceError("书源响应过大")
        return status, BytesParser().parsebytes(fields + b"\r\n\r\n"), body
    raise SourceError("系统 HTTPS 重试返回过多临时响应")


def fetch(url, check, headers, method, payload, maximum):
    host = _origin(url)
    client = client_path()
    if client is None:
        return None
    deadline = time.monotonic() + 12
    for _ in range(5):
        if _origin(url) != host:
            raise SourceError("系统 HTTPS 重试拒绝跨站跳转")
        check(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError("系统 HTTPS 重试超时")
        arguments = [str(client), "-q", "--silent", "--ipv4", "--include", "--suppress-connect-headers",
                     "--proto", "=https", "--max-redirs", "0", "--connect-timeout", str(min(5, remaining)),
                     "--max-time", str(remaining), "--max-filesize", str(maximum), "--request", method]
        for name, value in headers.items():
            arguments += ["--header", name + ": " + value]
        if payload is not None:
            arguments += ["--data-binary", "@-"]
        arguments += ["--url", url]
        code, raw = _run(arguments, payload, maximum + HEADER_LIMIT, remaining + 0.5)
        if code:
            messages = {6: "DNS 解析失败", 7: "连接被拒绝或不可达", 28: "连接超时", 35: "HTTPS 握手失败",
                        60: "HTTPS 证书校验失败", 63: "书源响应过大", 52: "连接中断", 56: "连接中断"}
            raise SourceError("系统 HTTPS／IPv4 重试仍失败：" + messages.get(code, "连接未完成"))
        status, response_headers, body = _response(raw, maximum)
        if status in {301, 302, 303, 307, 308}:
            location = response_headers.get("Location")
            if not location:
                raise SourceError("系统 HTTPS 重试收到无目标跳转")
            url = urljoin(url, location)
            if _origin(url) != host:
                raise SourceError("系统 HTTPS 重试拒绝跨站跳转")
            if status == 303 or (status in {301, 302} and method == "POST"):
                method, payload = "GET", None
            continue
        if not 200 <= status < 300:
            raise SourceError("书源返回 HTTP %d，请稍后重试或换源" % status)
        return body, response_headers.get_content_charset() or "utf-8"
    raise SourceError("系统 HTTPS 重试跳转次数过多")
