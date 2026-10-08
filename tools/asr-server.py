"""Serve the library, transcribe recorded speech, and optionally parse intent with a model.

It exists because the browser's own Web Speech API is unusable on some networks: the API is
hard-wired to the browser vendor's cloud service and its endpoint cannot be pointed elsewhere,
so recognition starts and then never returns a result. Here the page records a segment and posts
it, and the transcript comes back from a local model.

The same file runs two ways. On a server it is the deployment counterpart to tools/serve.mjs:
systemd starts it, an SSH tunnel carries the page, and the environment supplies the model path
and the key. Frozen with PyInstaller it is a local program instead — the site and the model ship
inside the bundle, so double-clicking is enough, and `http://localhost` provides the secure
context the microphone needs.

    HEXU_ASR_MODEL_DIR=/opt/.../sherpa-onnx-sense-voice-... python tools/asr-server.py

Routes:
    GET  /healthz          -> {"app": "hexu-library", ...}  lets a second launch find the first
    GET  /asr/ready        -> {"ready": bool, ...}  the page probes this and only then uses /asr
    POST /asr              -> 16 kHz mono WAV body, returns {"text": ...}
    GET  /understand/ready -> {"ready": bool, ...}  whether a semantic layer is configured
    POST /understand       -> {"text": ..., "phase": ...}, returns a parsed intent
    GET  /settings         -> local settings page; /settings/state, /settings/key and
                              /settings/test answer it, and all four are loopback-only
    GET  <anything>        -> static file under the site root

Recognition and static serving never leave this host. The semantic layer is the one exception,
and only when it is configured: it posts the transcript and the catalogue to the model service
named by HEXU_LLM_BASE_URL. That key is read from the environment, or from the reader's own
settings file, at call time — never cached, never logged, never written into this repository.
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
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import updater

MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"


def frozen():
    """True inside a PyInstaller build, where __file__ no longer sits beside the site."""
    return bool(getattr(sys, "frozen", False))


def site_root():
    """The directory holding index.html, src/ and public/.

    An explicit override wins, which is what lets a packaged build be pointed at an unpacked
    site. Otherwise a frozen build serves the tree it unpacked itself into, and a plain script
    serves the checkout it lives in — the layout the deployment has always used."""
    override = os.environ.get("HEXU_SITE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if frozen():
        return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent).resolve()
    return Path(__file__).resolve().parents[1]


def model_dir():
    """Where the SenseVoice model lives.

    Configurable first: a deployment points this at model files that may belong to another
    application on the same host and only reads them. A packaged build carries its own copy,
    right beside the site it serves."""
    override = os.environ.get("HEXU_ASR_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if frozen():
        return site_root() / "models" / "sense-voice"
    if os.name == "nt":
        # A Windows checkout has no sensible absolute default — a bare "/opt/..." would silently
        # resolve against the current drive. The packaging step puts the model here instead.
        return Path(__file__).resolve().parents[1] / ".cache" / "models" / MODEL_NAME
    return Path("/opt/hexu-library/models") / MODEL_NAME


def config_path():
    """The reader's own settings, kept outside this program's directory.

    A packaged build has to stay a replaceable folder with no state inside it: configuration that
    lived next to the executable would be lost on the next upgrade, and it would also mean the
    distributed folder carries a copy of somebody's key."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "hexu-library" / "llm.env"


ROOT = site_root()
PORT = int(os.environ.get("PORT", "8090"))
HOST = os.environ.get("HOST", "127.0.0.1")

MODEL_DIR = model_dir()
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

_engine_probe = None              # None until checked, then "" or the failure text


def engine_probe():
    """Whether the recogniser's own library actually loads, checked once.

    The two model files being present is not enough. A bundle can carry the model and still be
    missing a shared library, and then the page commits to this transport and only finds out on
    the first utterance, where all it can say is that the service was unreachable. Probing here
    turns that into a stated reason."""
    global _engine_probe
    if _engine_probe is None:
        try:
            import numpy  # noqa: F401
            import sherpa_onnx  # noqa: F401
            _engine_probe = ""
        except Exception as error:
            _engine_probe = f"{type(error).__name__}: {error}"
    return _engine_probe


def model_state():
    if not (MODEL_FILE.is_file() and TOKENS_FILE.is_file()):
        return False, {"ready": False, "model_dir": str(MODEL_DIR), "reason": "model files not found"}
    failure = engine_probe()
    if failure:
        return False, {"ready": False, "model_dir": str(MODEL_DIR),
                       "reason": f"识别引擎无法加载：{failure}"}
    return True, {
        "ready": True,
        "model": "sensevoice",
        "languages": ["zh", "en", "ja", "ko", "yue"],
        "model_dir": str(MODEL_DIR),
        "max_seconds": MAX_SECONDS,
    }


def recognizer():
    """The loaded model. The caller holds _result_lock."""
    global _recognizer
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
    return _recognizer


def warm_model():
    """Load the model before anyone speaks, so the first reply is not the slow one."""
    ready, _ = model_state()
    if not ready or not _result_lock.acquire(timeout=30):
        return False
    try:
        recognizer()
        return True
    except Exception:
        return False
    finally:
        _result_lock.release()


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

    started = time.perf_counter()
    if not _result_lock.acquire(timeout=25):
        return 503, {"error": "正在准备识别模型，请稍后再说一次"}
    try:
        stream = recognizer().create_stream()
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
LLM_BASE_URL_DEFAULT = "https://api.deepseek.com"
LLM_MODEL_DEFAULT = "deepseek-flash"
LLM_TIMEOUT = float(os.environ.get("HEXU_LLM_TIMEOUT", "12"))
MAX_JSON_BODY = 4_096

CATALOG_PATH = ROOT / "public" / "models" / "book-inventory.json"
CONFIG_PATH = config_path()
SETTINGS_KEYS = ("HEXU_LLM_BASE_URL", "HEXU_LLM_MODEL", "HEXU_LLM_API_KEY", "HEXU_SOURCE_DIR")


def load_settings():
    """The reader's settings file, re-read on every request and never cached.

    Not cached on purpose: reading the key at the moment it is needed is the same discipline the
    environment-variable path has always had, and it means a change made on the settings page
    takes effect on the next utterance rather than the next restart."""
    settings = {}
    try:
        lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return settings
    for line in lines:
        name, separator, value = line.strip().partition("=")
        name = name.strip()
        if separator and name in SETTINGS_KEYS and not name.startswith("#"):
            settings[name] = value.strip()
    return settings


def save_settings(updates):
    """Write the reader's settings. Values are stripped, and an empty one removes its line.

    This is the only place a credential is ever written, and it is written because the reader
    typed it on their own machine and expects it to persist. It goes to the user's profile, not
    to the program's directory, and no endpoint ever reads it back out."""
    stored = load_settings()
    for name, value in updates.items():
        if name in SETTINGS_KEYS:
            stored[name] = value if isinstance(value, str) else ""
            stored[name] = stored[name].strip()
    body = ("# 和序图书馆本机设置。位于你的用户目录，不属于程序本体，也不会随程序分发。\n"
            + "".join(f"{name}={stored[name]}\n" for name in SETTINGS_KEYS if stored.get(name)))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass  # Windows has no mode bits; the file is already inside the user's own profile
    os.replace(temporary, CONFIG_PATH)
    return stored


def settings_state():
    """Every setting, resolved and with its source. Environment first.

    A deployed service configures itself entirely through the environment, and a leftover file in
    someone's profile must not be able to redirect it."""
    stored = load_settings()
    resolved, sources = {}, {}
    for name, default in (("HEXU_LLM_BASE_URL", LLM_BASE_URL_DEFAULT),
                          ("HEXU_LLM_MODEL", LLM_MODEL_DEFAULT),
                          ("HEXU_LLM_API_KEY", ""),
                          ("HEXU_SOURCE_DIR", "")):
        from_environment = os.environ.get(name, "").strip()
        if from_environment:
            resolved[name], sources[name] = from_environment, "env"
        elif stored.get(name):
            resolved[name], sources[name] = stored[name], "file"
        else:
            resolved[name], sources[name] = default, "default"
    return resolved, sources


def settings_summary():
    """What the settings page is allowed to see: never the key, only whether there is one."""
    resolved, sources = settings_state()
    return {
        "configured": bool(resolved["HEXU_LLM_API_KEY"]),
        "base_url": resolved["HEXU_LLM_BASE_URL"],
        "model": resolved["HEXU_LLM_MODEL"],
        "key_source": sources["HEXU_LLM_API_KEY"],
        "key_from_environment": sources["HEXU_LLM_API_KEY"] == "env",
        "source_dir_setting": resolved["HEXU_SOURCE_DIR"],
        "path": str(CONFIG_PATH),
        "asr_ready": model_state()[0],
    }


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
    """(key, resolved, info): what to call, and whether it can be called at all.

    The key and the address are resolved at call time from the environment or the reader's own
    settings file — never cached, never logged."""
    resolved, sources = settings_state()
    info = {"model": resolved["HEXU_LLM_MODEL"], "base_url": resolved["HEXU_LLM_BASE_URL"],
            "key_source": sources["HEXU_LLM_API_KEY"]}
    if not resolved["HEXU_LLM_API_KEY"]:
        return None, resolved, {"ready": False, "reason": "尚未配置模型密钥", **info}
    if not CATALOG_NAMED:
        return None, resolved, {"ready": False, "reason": "馆藏清单不可读", **info}
    return resolved["HEXU_LLM_API_KEY"], resolved, {
        "ready": True, **info,
        "named_books": len(CATALOG_NAMED), "total_books": len(CATALOG_BY_ID),
    }


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


def redact(text, key):
    """Keep a credential out of an error message. Providers do not normally echo the
    Authorization header back, but this costs nothing and a leaked key cannot be recalled."""
    return text.replace(key, "[已隐去]") if key and key in text else text


def understand(text, phase):
    """Map one utterance onto an action. Returns (http_status, payload)."""
    key, resolved, info = llm_state()
    if key is None:
        return 503, info
    base_url = resolved["HEXU_LLM_BASE_URL"].rstrip("/")
    model = resolved["HEXU_LLM_MODEL"]
    text = (text or "").strip()
    if not text:
        return 400, {"error": "缺少要解析的文本"}
    try:
        validate_endpoint(base_url)
    except ValueError as error:
        return 503, {"error": str(error)}
    try:
        # `thinking` defaults to enabled on this API generation. Intent extraction is a
        # constrained classification, so thinking only adds latency and cost — and it would
        # also silently ignore `temperature`, which is what keeps the output stable.
        payload = {
            "model": model,
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
            base_url + "/chat/completions",
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
            detail = redact(error.read().decode("utf-8")[:200], key)
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
        if sys.stderr is None:  # windowless build: there is nowhere to write
            return
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

    def _loopback_only(self):
        """The settings surface belongs to the person at this machine.

        The default bind is loopback already, but HOST can be widened for a LAN deployment, and
        the settings page must not become remotely writable if it is."""
        try:
            if ipaddress.ip_address(self.client_address[0]).is_loopback:
                return True
        except ValueError:
            pass
        self._send_json(403, {"error": "本机设置只能从本机访问"})
        return False

    def _static_path(self, pathname):
        """Resolve a URL path inside ROOT, or None if it escapes."""
        relative = pathname.lstrip("/") or "index.html"
        target = (ROOT / relative).resolve()
        if target != ROOT and ROOT not in target.parents:
            return None
        return target

    def _serve_static(self, target):
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self.send_error(404, "Not found")
            return
        self._send_file(target)

    def _post_update_apply(self):
        ok, message = updater.start(update_source(), ROOT, os.getpid())
        self._send_json(200 if ok else 409, {"ok": ok, "message": message})
        if ok:
            # The helper waits for this process to disappear before it touches anything, so the
            # program now closes itself — the reply above has already been written out.
            threading.Timer(0.7, stop_everything).start()

    def _read_json(self):
        """One small JSON body, or None after answering the request itself."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_JSON_BODY:
            self._send_json(413, {"error": "请求体超出限制"})
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求体不是合法 JSON"})
            return None

    # --- routes ------------------------------------------------------------
    def do_GET(self):
        pathname = self.path.split("?", 1)[0]
        if pathname == "/healthz":
            self._send_json(200, {"app": "hexu-library", "asr_ready": model_state()[0],
                                  "semantic_ready": llm_state()[0] is not None})
            return
        if pathname == "/asr/ready":
            ready, payload = model_state()
            self._send_json(200 if ready else 503, payload)
            return
        if pathname == "/understand/ready":
            key, _, payload = llm_state()
            self._send_json(200 if key else 503, payload)
            return
        if pathname == "/settings" or pathname == "/settings/":
            if not self._loopback_only():
                return
            self._serve_static(ROOT / "public" / "settings.html")
            return
        if pathname == "/settings/state":
            if not self._loopback_only():
                return
            self._send_json(200, settings_summary())
            return
        if pathname == "/update/status":
            if not self._loopback_only():
                return
            self._send_json(200, updater.status(ROOT, update_source(),
                                                refresh="refresh=1" in self.path))
            return

        target = self._static_path(pathname)
        if target is None:
            self.send_error(403, "Forbidden")
            return
        self._serve_static(target)

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
        body = self._read_json()
        if body is None:
            return
        status, payload = understand(body.get("text"), body.get("phase"))
        self._send_json(status, payload)

    def _post_settings_key(self):
        """Store what the reader typed. The reply carries the new summary, never the value."""
        body = self._read_json()
        if body is None:
            return
        updates = {}
        for field, name in (("key", "HEXU_LLM_API_KEY"), ("baseUrl", "HEXU_LLM_BASE_URL"),
                            ("model", "HEXU_LLM_MODEL")):
            if field in body:
                updates[name] = body.get(field)
        save_settings(updates)
        self._send_json(200, {"ok": True, "message": "已保存。下一次说话就会用新的设置。",
                              **settings_summary()})

    def _post_settings_test(self):
        """Prove the whole path with one real, tiny request: key, address, TLS and parsing."""
        status, payload = understand("测试连接", "IDLE")
        if status == 200:
            seconds = payload.get("seconds", "")
            self._send_json(200, {"ok": True, "message": f"连接成功，模型已应答（{seconds} 秒）",
                                  **settings_summary()})
            return
        detail = payload.get("error") or payload.get("reason") or "未知原因"
        if payload.get("detail"):
            detail += "：" + str(payload["detail"])[:200]
        if "401" in detail or "403" in detail:
            hint = "密钥无效或已过期。"
        elif detail.startswith("无法连接"):
            hint = "网络或证书问题，无法到达模型服务。"
        elif detail.startswith("尚未配置"):
            hint = "请先填写并保存密钥。"
        else:
            hint = "服务未就绪。"
        self._send_json(502, {"ok": False, "message": hint + detail, **settings_summary()})

    def do_POST(self):
        pathname = self.path.split("?", 1)[0]
        if pathname == "/understand":
            self._post_understand()
            return
        if pathname in ("/settings/key", "/settings/test"):
            if not self._loopback_only():
                return
            if pathname == "/settings/key":
                self._post_settings_key()
            else:
                self._post_settings_test()
            return
        if pathname == "/update/apply":
            if not self._loopback_only():
                return
            self._post_update_apply()
            return
        if pathname != "/asr":
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


def parse_argv(argv):
    """The switches this program answers to, and nothing else.

    `--port` so a port already in use is the reader's choice rather than a traceback;
    `--browser` to use an external browser instead of the built-in window; `--no-browser` to open
    nothing at all (the deployment and the tests use it); `--check-mic` to report whether the
    built-in window can reach the microphone and exit."""
    options = {"port": PORT, "browser": True, "window": None, "check_mic": False,
               "check_update": False}
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--no-browser":
            options["browser"] = False
        elif argument == "--browser":
            options["window"] = False
        elif argument == "--window":
            options["window"] = True
        elif argument == "--check-mic":
            options["check_mic"] = True
        elif argument == "--check-update":
            options["check_update"] = True
        elif argument == "--port" and index + 1 < len(argv):
            try:
                options["port"] = int(argv[index + 1])
            except ValueError:
                pass
            index += 1
        elif argument.startswith("--port="):
            try:
                options["port"] = int(argument.split("=", 1)[1])
            except ValueError:
                pass
        index += 1
    return options


class Server(ThreadingHTTPServer):
    """The plain server, except for one platform difference in what SO_REUSEADDR means.

    On POSIX, reusing the address keeps a restart from tripping over TIME_WAIT — which matters
    to the deployment: systemd restarting the unit has to come back on 8090, not somewhere else.
    On Windows the same flag does something else entirely: it lets a second process bind a port
    another process is already listening on and take over its connections, which would turn a
    launch during startup into two servers fighting over one port. Listeners do not linger in
    TIME_WAIT on Windows, so there is nothing to lose by turning it off there."""

    allow_reuse_address = os.name != "nt"


def local_host(host):
    """What to put in a URL for this bind address. localhost keeps the page a secure context,
    which is what the microphone permission depends on."""
    return "localhost" if host in ("127.0.0.1", "0.0.0.0", "::", "") else host


def running_instance(host, port):
    """The URL of an instance already serving this program, or None.

    A double-clicked program gets launched twice sooner or later, and a second copy that dies on
    an address-in-use traceback teaches the reader nothing. Asking /healthz distinguishes
    "already running" from "something else owns this port"."""
    if not 0 < port < 65536:
        return None
    # Both parts of this address come from this process's own configuration — HOST and --port —
    # never from a request, and the only thing that travels is a GET for a fixed path.
    probe = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    address = f"http://{probe}:{port}/healthz"
    try:
        # No proxy: a machine-wide proxy setting must not swallow a loopback probe.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(address, timeout=0.8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    if payload.get("app") != "hexu-library":
        return None
    return f"http://{local_host(host)}:{port}/"


def attach_console():
    """Give a packaged run back its console, when it was started from one.

    The window build is a GUI binary, so Windows gives it no standard streams at all — and a
    diagnostic like `--check-mic`, run from a terminal, would print into nothing. Attaching to
    the parent's console when there is one fixes that and changes nothing when the program is
    started by double-clicking, where there is no parent console to attach to."""
    if sys.stdout is not None or os.name != "nt":
        return
    try:
        import ctypes

        if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            # "CONOUT$" is a Windows device name, not a path: this is how a GUI process that has
            # just attached to its parent's console gets a stream to write to. The name is a
            # literal with nothing interpolated into it, and Windows does not let a normal file
            # take a device name's place, so there is nothing here to divert.
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = sys.stdout
    except Exception:
        pass


_stop = threading.Event()


def stop_everything():
    """Let the program end, so an update helper can rebuild it.

    Set from the update request after its reply has been written: the helper waits for this
    process to disappear before it touches a single file, and closing the window first is what
    makes the window loop return so main() can finish."""
    _stop.set()
    try:
        import window_host

        window_host.close_windows()
    except Exception:
        pass


def update_source():
    """The checkout to update from: what was configured, else where this build was made."""
    resolved, _ = settings_state()
    return updater.source_directory(ROOT, resolved.get("HEXU_SOURCE_DIR", ""))


def note(text):
    """Say something where the reader can actually see it.

    The packaged build has no console — that is what the window is for — so a message that only
    went to stdout would vanish exactly when it matters most. With no console it becomes a
    dialog instead."""
    print(text, flush=True)
    if sys.stdout is None and os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, "和序图书馆", 0x40)
        except Exception:
            pass


def window_mode(options):
    """Whether to show the page in the built-in window.

    The packaged program is a program, so that is its default. A plain script — the deployment,
    or a checkout being worked on — serves and hands the address to a browser, exactly as
    before. `--window` and `--browser` override either way."""
    if options["window"] is not None:
        return options["window"]
    return frozen() and os.name == "nt"


def show_window(url):
    """Show the page in a native window, or report that none could be shown.

    True means the window was shown and has now been closed — the reader quitting, which is how
    this program is meant to stop. False means there was nothing to show, so the caller should
    fall back to something visible rather than leave the reader staring at nothing."""
    try:
        import window_host
    except Exception as error:
        note(f"内嵌窗口不可用（{type(error).__name__}: {error}）")
        return False
    ready, reason = window_host.available()
    if not ready:
        note(f"内嵌窗口不可用：{reason}")
        return False
    return window_host.run(url)


def microphone_check():
    """Report whether the built-in window can reach the microphone, then exit.

    Worth having as a first-class command: the microphone is the one capability that differs
    between the browser and the window, WebView2 refuses it unless the host answers the
    permission request, and the answer here comes from the page itself — so it also covers the
    secure-origin requirement for a loopback address.

    The verdict is written next to the settings as well as reported, because the window build has
    no console: started from a terminal the text appears there, and started any other way there
    would otherwise be nothing to read afterwards."""
    try:
        import window_host
    except Exception as error:
        note(f"麦克风检测无法进行：缺少内嵌窗口组件（{type(error).__name__}: {error}）")
        return 1
    ready, reason = window_host.available()
    if not ready:
        note(f"麦克风检测无法进行：{reason}")
        return 1
    server = Server((HOST, 0), partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{local_host(HOST)}:{server.server_address[1]}/"
    try:
        ok, message = window_host.microphone_report(url)
    finally:
        server.shutdown()
        server.server_close()
    verdict = ("麦克风检测通过：" if ok else "麦克风检测未通过：") + message
    report = CONFIG_PATH.with_name("mic-check.txt")
    try:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(verdict + "\n", encoding="utf-8")
        verdict += f"\n（同时写入 {report}）"
    except OSError:
        pass
    note(verdict)
    return 0 if ok else 1


def update_check():
    """Report whether Gitee has something newer, then exit.

    0 = already current, 1 = an update is available, 2 = could not be determined. The same three
    answers the settings page shows, so a script and a reader never disagree."""
    resolved, _ = settings_state()
    source = updater.source_directory(ROOT, resolved.get("HEXU_SOURCE_DIR", ""))
    payload = updater.status(ROOT, source, refresh=True)
    installed = payload["installed"]
    lines = [
        f"已安装   {installed.get('commit') or '（未记录）'}"
        f"  {installed.get('built_at') or ''}".rstrip(),
        f"源码目录 {payload['source_dir'] or '（未配置）'}",
        f"状态     {payload['reason']}",
    ]
    for commit in payload.get("commits", [])[:10]:
        lines.append("         " + commit)
    note("\n".join(lines))
    if payload["state"] == "up-to-date":
        return 0
    if payload["state"] in ("update-available", "unknown"):
        return 1
    return 2


def main():
    attach_console()
    options = parse_argv(sys.argv[1:])

    if options["check_mic"]:
        return microphone_check()
    if options["check_update"]:
        return update_check()

    existing = running_instance(HOST, options["port"])
    if existing:
        note(f"和序图书馆已经在运行：{existing}")
        if window_mode(options) and show_window(existing):
            return 0
        if options["browser"]:
            webbrowser.open(existing)
        return 0

    try:
        server = Server((HOST, options["port"]), partial(Handler, directory=str(ROOT)))
    except OSError as error:
        if not options["port"]:
            note(f"和序图书馆无法启动：{error}")
            return 1
        note(f"端口 {options['port']} 无法使用（{error.strerror}），改为自动选择空闲端口。")
        server = Server((HOST, 0), partial(Handler, directory=str(ROOT)))

    address = f"http://{local_host(HOST)}:{server.server_address[1]}/"
    note(f"和序图书馆 · {address}")
    print(f"  站点根目录 {ROOT}", flush=True)
    ready, info = model_state()
    print(f"  识别模型   {MODEL_DIR}", flush=True)
    print(f"             {'就绪' if ready else '不可用 —— ' + info.get('reason', '')}", flush=True)
    key, _, semantic = llm_state()
    print(f"  语义解析   {semantic['model']} · {'已配置' if key else '未配置'}"
          f"（在 {address}settings 里填写）", flush=True)

    # Serving moves to a background thread so the window loop can own the main thread, which is
    # where WinForms needs its message loop.
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=warm_model, daemon=True).start()
    # One check shortly after startup, off the critical path: the page asks for the answer when
    # it loads, and a cached answer is what keeps that a fast request.
    threading.Thread(
        target=lambda: (time.sleep(1.5), updater.status(ROOT, update_source())), daemon=True
    ).start()

    if window_mode(options):
        if show_window(address):
            server.shutdown()
            server.server_close()
            return 0
        note("无法显示程序窗口，已改用浏览器打开。")
        if options["browser"]:
            webbrowser.open(address)
    elif options["browser"]:
        threading.Thread(
            target=lambda: (time.sleep(0.4), webbrowser.open(address)), daemon=True
        ).start()

    try:
        _stop.wait()
    except KeyboardInterrupt:
        note("和序图书馆已停止。")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
