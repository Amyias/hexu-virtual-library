"""Serve the library, transcribe recorded speech, and optionally parse intent with a model.

Deployment counterpart to tools/serve.mjs. It exists because the browser's own Web Speech API
is unusable on some networks: the API is hard-wired to the browser vendor's cloud service and
its endpoint cannot be pointed elsewhere, so recognition starts and then never returns a
result. Here the page records a segment and posts it, and the transcript comes back from a
local model.

    HEXU_ASR_MODEL_DIR=/opt/.../sherpa-onnx-sense-voice-... python tools/asr-server.py

Routes:
    GET  /asr/ready        -> {"ready": bool, ...}  the page probes this and only then uses /asr
    POST /asr              -> 16 kHz mono WAV body, returns {"text": ...}
    GET  /understand/ready -> {"ready": bool, ...}  whether a semantic layer is configured
    POST /understand       -> {"text": ..., "phase": ...}, returns a parsed intent
    GET  <anything>        -> static file under the project root

Recognition and static serving never leave this host. The semantic layer is the one exception,
and only when it is configured: it posts the transcript and the catalogue to the model service
named by HEXU_LLM_BASE_URL, whose key is read from the environment per request and never
written anywhere.
"""
import io
import ipaddress
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("PORT", "8090"))
HOST = os.environ.get("HOST", "127.0.0.1")

#: Where the SenseVoice model lives. Deliberately configurable: the deployment points this at
#: model files that may belong to another application on the same host, and we only read them.
MODEL_DIR = Path(
    os.environ.get(
        "HEXU_ASR_MODEL_DIR",
        "/opt/hiyori-voice/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
    )
)
MODEL_FILE = MODEL_DIR / "model.int8.onnx"
TOKENS_FILE = MODEL_DIR / "tokens.txt"

MAX_BODY = 1_500_000        # ~47 s of 16 kHz mono 16-bit PCM, half a megabyte of slack
MIN_SECONDS = 0.25
MAX_SECONDS = 45.0
SILENCE_RMS = 0.0015        # below this the segment carries no speech worth decoding

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".glb": "model/gltf-binary",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

_recognizer = None
_result_lock = threading.Lock()   # one decode at a time; the model is not reentrant


def model_state():
    if MODEL_FILE.is_file() and TOKENS_FILE.is_file():
        return True, {
            "ready": True,
            "model": "sensevoice",
            "languages": ["zh", "en", "ja", "ko", "yue"],
            "model_dir": str(MODEL_DIR),
            "max_seconds": MAX_SECONDS,
        }
    return False, {"ready": False, "model_dir": str(MODEL_DIR), "reason": "model files not found"}


def transcribe(raw):
    """Decode one 16 kHz mono WAV body into text.

    Returns (http_status, payload). Raises nothing: the caller turns every outcome into a
    response, because a failed segment should leave the page listening rather than break it."""
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 16000):
                return 400, {"error": "录音需为 16kHz 单声道 16 位 PCM WAV"}
            duration = w.getnframes() / 16000
            if duration < MIN_SECONDS or duration > MAX_SECONDS:
                return 400, {"error": f"录音时长需在 {MIN_SECONDS}–{MAX_SECONDS} 秒之间"}
            pcm = w.readframes(w.getnframes())
            if len(pcm) != w.getnframes() * 2:
                return 400, {"error": "录音数据不完整"}
    except (wave.Error, EOFError):
        return 400, {"error": "录音文件格式无效"}

    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    # Silence: report an empty transcript instead of spending a decode on noise.
    if float(np.sqrt(np.mean(samples * samples))) < SILENCE_RMS:
        return 200, {"text": "", "duration": round(duration, 3), "silent": True}

    global _recognizer
    started = time.perf_counter()
    if not _result_lock.acquire(timeout=10):
        return 503, {"error": "正在识别上一段录音，请稍候"}
    try:
        if _recognizer is None:
            import sherpa_onnx

            _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(MODEL_FILE),
                tokens=str(TOKENS_FILE),
                num_threads=2,
                use_itn=True,
                language="zh",
                debug=False,
            )
        stream = _recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        _recognizer.decode_stream(stream)
        # Tags such as <|zh|> are already split out of .text by this build; strip defensively.
        text = re.sub(r"<\|.*?\|>", "", stream.result.text).strip()
        return 200, {
            "text": text,
            "duration": round(duration, 3),
            "seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        _result_lock.release()


# --- semantic layer (optional) ------------------------------------------------
# Local rules place most requests instantly and for free, so the model is only consulted when
# they cannot. It is entirely optional: without a key the endpoints report not-ready and the
# page keeps working on the rules alone.
LLM_BASE_URL = os.environ.get("HEXU_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
LLM_MODEL = os.environ.get("HEXU_LLM_MODEL", "deepseek-flash")
LLM_TIMEOUT = float(os.environ.get("HEXU_LLM_TIMEOUT", "12"))
MAX_JSON_BODY = 4_096

CATALOG_PATH = ROOT / "public" / "models" / "book-inventory.json"


def load_catalog():
    """Ids for validating what the model returns, plus the few books worth naming in the prompt.

    Most of the catalogue is numbered stock whose title *is* its id, so listing those would
    cost thousands of tokens and teach the model nothing — they are reachable by code, which
    the local rules already do. Only the books with real titles need describing."""
    by_id, named = {}, []
    try:
        entries = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"  语义层：读取馆藏清单失败（{error}）", flush=True)
        return by_id, named
    for entry in entries:
        book_id = entry.get("bookId")
        if not book_id:
            continue
        by_id[book_id] = entry
        if not entry.get("placeholder"):
            named.append(f"{book_id} | {entry.get('title','')} | {entry.get('author','')} | {entry.get('category','')}")
    return by_id, named


CATALOG_BY_ID, CATALOG_NAMED = load_catalog()
_SYSTEM_PROMPT = None


def system_prompt():
    """Built once. A stable prefix is what lets the provider cache it between calls."""
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = (
            "你是图书馆的语义解析器。把读者的一句话解析成一个动作，只输出 JSON。\n\n"
            "action 的取值：\n"
            "- find：读者想找某本书，必须在 bookId 里给出编号\n"
            "- return：把正在阅读的书放回书架\n"
            "- open：翻开当前书的封面\n"
            "- close：合上当前书的封面\n"
            "- chip：查看当前书的芯片\n"
            "- none：与图书馆无关，或无法判断\n\n"
            "带正式书名的馆藏只有下面这些，bookId 必须从中选择：\n"
            + "\n".join(CATALOG_NAMED)
            + f"\n\n其余 {len(CATALOG_BY_ID) - len(CATALOG_NAMED)} 本只有编号（形如 HX-0001），"
            "没有书名，无法按内容查找；读者直接报编号时由本地规则处理，你不需要管。\n\n"
            '只输出这个 JSON，不要输出任何其它文字：\n'
            '{"action": "find|return|open|close|chip|none", "bookId": "HX-0000 或空字符串", '
            '"say": "不超过 20 字的中文回应"}\n\n'
            "规则：\n"
            "- 不确定就用 none，不要猜。\n"
            "- 读者的说法与上表只是部分相关时，也要选最接近的那一本"
            "（例如「讲宇宙的那本」对应《时间简史》）。\n"
            "- action 不是 find 时，bookId 留空字符串。\n"
        )
    return _SYSTEM_PROMPT


def llm_state():
    """Readiness and the key, read from the environment at call time and never cached."""
    key = os.environ.get("HEXU_LLM_API_KEY", "").strip()
    if not key:
        return None, {"ready": False, "reason": "HEXU_LLM_API_KEY 未配置", "model": LLM_MODEL}
    if not CATALOG_NAMED:
        return None, {"ready": False, "reason": "馆藏清单不可读", "model": LLM_MODEL}
    return key, {"ready": True, "model": LLM_MODEL, "base_url": LLM_BASE_URL,
                 "named_books": len(CATALOG_NAMED), "total_books": len(CATALOG_BY_ID)}


def validate_endpoint(url):
    """The address comes from configuration rather than from a request, so there is no SSRF
    surface here. This still refuses anything but https to a public host, so a mistyped
    setting cannot quietly point the service at something on the internal network."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("模型接入地址必须是 https")
    host = (parsed.hostname or "").strip().rstrip(".")  # "localhost." is still loopback
    if not host:
        raise ValueError("模型接入地址缺少主机名")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("模型接入地址不能指向本机或内网")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if (address.is_loopback or address.is_private or address.is_link_local
            or address.is_reserved or address.is_multicast or address.is_unspecified):
        raise ValueError("模型接入地址不能是回环、私有或保留地址")


def understand(text, phase):
    """Map one utterance onto an action. Returns (http_status, payload)."""
    key, info = llm_state()
    if key is None:
        return 503, info
    text = (text or "").strip()
    if not text:
        return 400, {"error": "缺少要解析的文本"}
    try:
        validate_endpoint(LLM_BASE_URL)
    except ValueError as error:
        return 503, {"error": str(error)}
    try:
        # `thinking` defaults to enabled on this API generation. Intent extraction is a
        # constrained classification, so thinking only adds latency and cost — and it would
        # also silently ignore `temperature`, which is what keeps the output stable.
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt()},
                {
                    "role": "user",
                    "content": f"当前状态：{'正在阅读一本书' if phase == 'READING' else '待命中'}\n读者说：{text}",
                },
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 300,
            "stream": False,
            # JSON mode requires the prompt above to ask for JSON explicitly, which it does.
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            LLM_BASE_URL + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # The key is used here and nowhere else: not logged, not stored.
                "Authorization": "Bearer " + key,
            },
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8")[:200]
        except Exception:
            pass
        return 502, {"error": f"模型服务返回 {error.code}", "detail": detail}
    except Exception as error:
        return 502, {"error": f"无法连接模型服务：{type(error).__name__}"}

    try:
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(re.sub(r"```(?:json)?|```", "", content).strip())
    except (KeyError, IndexError, ValueError):
        return 502, {"error": "模型返回的内容无法解析为 JSON"}

    action = parsed.get("action")
    book_id = (parsed.get("bookId") or "").strip()
    say = (parsed.get("say") or "").strip()[:60]
    if action not in ("find", "return", "open", "close", "chip", "none"):
        return 200, {"action": "none", "say": "", "via": "llm",
                     "seconds": round(time.perf_counter() - started, 3)}
    # Never trust the model's target: an id it invented must not reach the scene, where it
    # would resolve to nothing and break navigation.
    if action == "find" and book_id not in CATALOG_BY_ID:
        action, book_id = "none", ""
    return 200, {"action": action, "bookId": book_id, "say": say, "via": "llm",
                 "seconds": round(time.perf_counter() - started, 3)}


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "hexu-library"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- helpers -----------------------------------------------------------
    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status, payload):
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _static_path(self, pathname):
        """Resolve a URL path inside ROOT, or None if it escapes."""
        relative = pathname.lstrip("/") or "index.html"
        target = (ROOT / relative).resolve()
        if target != ROOT and ROOT not in target.parents:
            return None
        return target

    # --- routes ------------------------------------------------------------
    def do_GET(self):
        pathname = self.path.split("?", 1)[0]
        if pathname == "/asr/ready":
            ready, payload = model_state()
            self._send_json(200 if ready else 503, payload)
            return
        if pathname == "/understand/ready":
            key, payload = llm_state()
            self._send_json(200 if key else 503, payload)
            return

        target = self._static_path(pathname)
        if target is None:
            self.send_error(403, "Forbidden")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self.send_error(404, "Not found")
            return
        self._send_file(target)

    def _send_file(self, target):
        """Serve a file, revalidating instead of re-sending.

        The model is 18 MiB and the uplink is the bottleneck, so a repeat visit must not
        transfer it again: an ETag lets the browser revalidate and take a 304. A pre-compressed
        sibling is used when the client accepts gzip — the deploy step writes those, which keeps
        this process read-only."""
        stat = target.stat()
        etag = '"%d-%d"' % (stat.st_size, int(stat.st_mtime))
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return

        serving = target
        encoding = None
        compressed = target.with_name(target.name + ".gz")
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if accepts_gzip and compressed.is_file() and compressed.stat().st_mtime >= stat.st_mtime:
            serving = compressed
            encoding = "gzip"

        try:
            body = serving.read_bytes()
        except OSError:
            self.send_error(500, "Read failed")
            return
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(body)

    def _post_understand(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_JSON_BODY:
            self._send_json(413, {"error": "请求体超出限制"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求体不是合法 JSON"})
            return
        status, payload = understand(body.get("text"), body.get("phase"))
        self._send_json(status, payload)

    def do_POST(self):
        if self.path.split("?", 1)[0] == "/understand":
            self._post_understand()
            return
        if self.path.split("?", 1)[0] != "/asr":
            self.send_error(404, "Not found")
            return
        ready, _ = model_state()
        if not ready:
            self._send_json(503, {"error": "识别模型不可用"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send_json(413, {"error": "录音体积超出限制"})
            return
        raw = self.rfile.read(length)
        status, payload = transcribe(raw)
        self._send_json(status, payload)


def main():
    ready, info = model_state()
    print(f"和序 · 服务模式 http://{HOST}:{PORT}", flush=True)
    print(f"  站点根目录 {ROOT}", flush=True)
    print(f"  识别模型   {MODEL_DIR}  {'就绪' if ready else '不可用'}", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), partial(Handler, directory=str(ROOT)))
    server.serve_forever()


if __name__ == "__main__":
    main()
