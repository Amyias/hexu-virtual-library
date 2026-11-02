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
    GET  /tts/ready        -> {"ready": bool, "voice": ...}  local Taiwan-Mandarin voice (tools/tts.py)
    POST /tts              -> {"text": ...}, returns 16 kHz WAV; the page falls back to the
                              browser's speechSynthesis while this answers 503
    POST /chat             -> general conversation with bounded, browser-owned history
    POST /chat/stream      -> the same conversation as newline-delimited JSON events, so the
                              page can show and speak the reply while it is still being written
    GET  /chat/ready       -> configured model and non-secret configuration identity
    POST /understand       -> {"text": ..., "phase": ...}, returns a parsed intent; 429 past
                              HEXU_LLM_PER_MINUTE calls a minute from one address
    GET  /memory/state     -> what 小和 remembers (facts, books opened, conversation summaries);
    POST /memory/*         -> fact / reading / summarize / delete / clear / enabled. All
                              loopback-only: the reader's own memory, kept in %APPDATA%
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
import sqlite3
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
import book_library
import app_actions
import book_text_search
import listener
import reader_memory
import tts
import llm_chat
import web_tools

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


def tts_model_dir():
    """Where the PrimeTTS voice lives: beside the site in a packaged build, under .cache in a
    checkout (tools/package-local.mjs downloads it there), or wherever the deployment says."""
    override = os.environ.get("HEXU_TTS_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if frozen():
        return site_root() / "models" / "primetts"
    return Path(__file__).resolve().parents[1] / ".cache" / "models" / "primetts-v2.1"


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
# Names a loopback-only route answers to; urlsplit gives "::1" for a "[::1]:8090" Host.
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}

MODEL_DIR = model_dir()
MODEL_FILE = MODEL_DIR / "model.int8.onnx"
LISTENER = listener.Listener(listener.model_dir(site_root(), frozen()))
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
    ".mp3": "audio/mpeg",
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
        # Continuous listening (POST /asr/stream): the page streams audio and is told the moment
        # 小和 is named. Without its small models the page uploads whole segments instead.
        "streaming": LISTENER.state()[0],
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
    try:
        text = decode(samples)
    except TimeoutError:
        return 503, {"error": "正在准备识别模型，请稍后再说一次"}
    return 200, {
        "text": text,
        "duration": round(duration, 3),
        "seconds": round(time.perf_counter() - started, 3),
    }


def decode(samples):
    """Text for 16 kHz float samples; TimeoutError when the model stays busy. Shared by whole
    uploads (transcribe) and continuous listening (listener.Session)."""
    if not _result_lock.acquire(timeout=25):
        raise TimeoutError("recogniser busy")
    try:
        stream = recognizer().create_stream()
        stream.accept_waveform(16000, samples)
        _recognizer.decode_stream(stream)
        # Tags such as <|zh|> are already split out of .text by this build; strip defensively.
        return re.sub(r"<\|.*?\|>", "", stream.result.text).strip()
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
# Model calls allowed per client address in any sixty seconds. A person needs a handful a minute —
# only what the local rules cannot place goes to the model — so this is far above real use and
# exists for the runaway case: a recogniser looping on background noise, or a page bug resending,
# billing the reader's quota until somebody notices. 0 turns the limit off.
LLM_PER_MINUTE = int(os.environ.get("HEXU_LLM_PER_MINUTE", "20"))


class RateLimit:
    """A sliding sixty-second window per key, safe across the server's request threads.

    Keyed by client address. Through the deployment's SSH tunnel every request arrives from
    loopback, so there it is one budget for the whole service; a LAN bind gets one per machine."""

    def __init__(self, per_minute, window=60.0, clock=time.monotonic):
        self.per_minute, self.window, self.clock = per_minute, window, clock
        self._calls = {}
        self._lock = threading.Lock()

    def allow(self, key):
        """Record a call and return 0, or return the seconds until one is allowed again."""
        if self.per_minute <= 0:
            return 0
        now = self.clock()
        with self._lock:
            # Drop every key whose window has emptied, so idle addresses cannot pile up.
            for other in [k for k, calls in self._calls.items() if calls[-1] <= now - self.window]:
                del self._calls[other]
            calls = [t for t in self._calls.get(key, []) if t > now - self.window]
            if len(calls) >= self.per_minute:
                self._calls[key] = calls
                return max(1, int(calls[0] + self.window - now + 0.999))
            calls.append(now)
            self._calls[key] = calls
            return 0


UNDERSTAND_LIMIT = RateLimit(LLM_PER_MINUTE)
# A sentence costs a fraction of a second of CPU; generous for a reader, a ceiling for a script.
SPEECH_LIMIT = RateLimit(int(os.environ.get("HEXU_TTS_PER_MINUTE", "240")))
SPEAKER = tts.Speaker(tts_model_dir())

CATALOG_PATH = ROOT / "public" / "models" / "book-inventory.json"
try:
    book_library.configure_shelves(CATALOG_PATH)
except (OSError, ValueError, KeyError):
    pass  # without the inventory new books fall back to the next free number
CONFIG_PATH = config_path()
SETTINGS_KEYS = ("HEXU_LLM_BASE_URL", "HEXU_LLM_MODEL", "HEXU_LLM_API_KEY", "HEXU_GITHUB_TOKEN",
                 "HEXU_WEB_ENABLED", "HEXU_WEB_API_KEY")


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
                          ("HEXU_WEB_ENABLED", "1"),
                          ("HEXU_WEB_API_KEY", ""),
                          ("HEXU_GITHUB_TOKEN", "")):
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
        "update_token_set": bool(resolved["HEXU_GITHUB_TOKEN"]),
        "update_token_source": sources["HEXU_GITHUB_TOKEN"],
        "path": str(CONFIG_PATH),
        "asr_ready": model_state()[0],
        **web_tools.summary(resolved),
        "web_key_source": sources["HEXU_WEB_API_KEY"],
    }


def load_catalog():
    """Only real, persisted books are semantic targets; empty shelf IDs are never books."""
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        physical = book_library.physical_rows(data)
        by_id = {}
        for book in book_library.instance().list_books():
            slot = book["slot"]
            if isinstance(slot, int) and 0 <= slot < len(physical):
                by_id[f"HX-{physical[slot] + 1:05d}"] = book
        named = [f"{identifier} | {book['title']} | {book.get('author', '')}"
                 for identifier, book in by_id.items()]
        return by_id, named
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"  语义层：读取本地书库失败（{type(error).__name__}）", flush=True)
        return {}, []


def system_prompt():
    """Read fresh metadata so books imported during this session are immediately searchable."""
    _, named = load_catalog()
    return (
        "你是图书馆的语义解析器。把读者的一句话解析成动作，只输出 JSON。\n"
        "动作：find 找书；return 归还；open 翻开；close 合上；chip 查看芯片；none 无法判断。\n"
        "仅以下已入库的真实书籍可供选择，find 的 bookId 必须来自本表：\n"
        + "\n".join(named)
        + '\n只输出 {"action":"find|return|open|close|chip|none","bookId":"编号或空字符串","say":"不超过20字的中文回应"}。'
        "不确定、目录为空或读者想找未入库的书时返回 none；不得把空槽位当成书。"
        "非 find 动作的 bookId 留空。"
    )


def llm_state():
    """(key, resolved, info): what to call, and whether it can be called at all.

    The key and the address are resolved at call time from the environment or the reader's own
    settings file — never cached, never logged."""
    resolved, sources = settings_state()
    info = {"model": resolved["HEXU_LLM_MODEL"], "base_url": resolved["HEXU_LLM_BASE_URL"],
            "key_source": sources["HEXU_LLM_API_KEY"]}
    if not resolved["HEXU_LLM_API_KEY"]:
        return None, resolved, {"ready": False, "reason": "尚未配置模型密钥", **info}
    by_id, named = load_catalog()
    return resolved["HEXU_LLM_API_KEY"], resolved, {
        "ready": True, **info,
        "named_books": len(named), "total_books": len(by_id),
    }


def validate_endpoint(url):
    """The address comes from configuration rather than from a request, so there is no SSRF
    surface here. This still refuses anything but https to a public host, so a mistyped
    setting cannot quietly point the service at something on the internal network."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("模型接入地址必须是 https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("接入地址不能含账号、查询参数或片段")
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
    if not isinstance(text, str):
        return 400, {"error": "缺少要解析的文本"}
    text = text.strip()
    if not text:
        return 400, {"error": "缺少要解析的文本"}
    try:
        validate_endpoint(base_url)
    except ValueError as error:
        return 503, {"error": str(error)}
    started = time.perf_counter()
    status, answer = llm_chat.completion(resolved, [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": f"当前状态：{phase}\n读者说：{text}"},
    ], validate_endpoint, timeout=LLM_TIMEOUT, intent=True)
    if status != 200:
        return status, answer
    try:
        parsed = json.loads(re.sub(r"```(?:json)?|```", "", answer["reply"]).strip())
        if not isinstance(parsed, dict):
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        return 502, {"error": "模型返回的内容无法解析为 JSON"}

    action = parsed.get("action")
    book_id = str(parsed.get("bookId") or "").strip()
    say = str(parsed.get("say") or "").strip()[:60]
    if action not in ("find", "return", "open", "close", "chip", "none"):
        return 200, {"action": "none", "say": "", "via": "llm",
                     "seconds": round(time.perf_counter() - started, 3)}
    # Never trust the model's target: an id it invented must not reach the scene, where it
    # would resolve to nothing and break navigation.
    if action == "find" and book_id not in load_catalog()[0]:
        action, book_id = "none", ""
    return 200, {"action": action, "bookId": book_id, "say": say, "via": "llm",
                 "seconds": round(time.perf_counter() - started, 3)}


def describe_book(book_id):
    """What the reading library knows about one book, for memory; None once it is deleted."""
    try:
        book = book_library.instance().get(book_id, include_text=False)
    except (book_library.SourceError, OSError, ValueError):
        return None
    chapter = int(book.get("progress", {}).get("chapter", 0))
    chapters = book.get("chapters") or []
    title = chapters[chapter]["title"] if 0 <= chapter < len(chapters) else ""
    return {"title": book.get("title", ""), "author": book.get("author", ""), "chapter": chapter,
            "chapters": len(chapters), "chapter_title": title if chapter > 0 else ""}


def memory_context(body=None):
    """The memory block for one chat request, ranked against what the reader just asked."""
    question = body.get("text") if isinstance(body, dict) and isinstance(body.get("text"), str) else ""
    try:
        return reader_memory.context_if_present(describe_book, question)
    except (sqlite3.Error, OSError):
        return ""  # a broken memory file must never stop 小和 answering


_text_search = None


def text_search():
    global _text_search
    if _text_search is None:
        _text_search = book_text_search.BookTextSearch(book_library.instance())
    return _text_search


def chapter_label(number, title):
    # Many imported books already title chapters 「第十二章 红岸之四」; do not say it twice.
    return title if title.startswith("第") else f"第{number + 1}章 {title}".strip()


# The reader asks to hear what lies ahead. Checked after REFUSES_SPOILERS, so 「别剧透结局」
# keeps the protection.
WANTS_SPOILERS = re.compile(
    r"(不怕|不介意|不在乎|没关系|无所谓|可以|允许|随便)[^。！？，,]{0,3}剧透"
    r"|剧透[^。！？，,]{0,4}(没关系|没事|无所谓|也行|也可以|吧)"
    r"|结局|结尾|最后[^。！？，,]{0,4}(怎么样|怎样|如何|结果)|后面[^。！？，,]{0,4}(会|发生|怎么)")
REFUSES_SPOILERS = re.compile(r"(不要|别|不想|不许|不准|不能|不用)[^。！？，,]{0,6}(剧透|结局|结尾|后面)")


def wants_spoilers(text):
    return not REFUSES_SPOILERS.search(text) and bool(WANTS_SPOILERS.search(text))


# A question that leans on the one before: 「她后来怎么样了」 names nobody to search for.
FOLLOW_UP = re.compile(r"他|她|它|这个人|那个人|这件事|那件事|后来|然后|接着|之后|那时|为什么|怎么回事|还有呢|继续")
FOLLOW_UP_CHARS = 12


def previous_question(body):
    """The reader's last question in this conversation, or ""."""
    history = body.get("history") if isinstance(body, dict) else None
    if not isinstance(history, list):
        return ""
    for entry in reversed(history):
        if isinstance(entry, dict) and entry.get("role") == "user" and isinstance(entry.get("content"), str):
            return entry["content"][:400]
    return ""


def named_books(question, books):
    """Ids of the local books a question names: the whole title, or a part of it, since 「星海」
    names 《星海Ⅰ·启航》 as readers say it."""
    found = []
    for book in sorted(books, key=lambda item: -len(item.get("title", ""))):
        title = book.get("title", "")
        parts = [title, *re.split(r"[·・:：\-—_（）()\[\]【】ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ\s]+", title)]
        if any(len(part) >= 2 and part in question for part in parts) and book["id"] not in found:
            found.append(book["id"])
    return found


def book_passages(body, selected):
    """Passages from local books for the chat prompt, as labelled text; "" when no local book is
    involved or nothing matches. The book being read always counts; so does any local title the
    question names. Only these short passages are sent on, never a whole book.

    A follow-up (short, or leaning on 他 / 后来 / 为什么) is searched together with the reader's
    previous question, and keeps the book that question named: 「叶文洁在红岸做了什么」 then
    「她后来怎么样了」 searches for 叶文洁 in 《三体》. A rule, not a model call: no quota is spent."""
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        return ""
    try:
        books = book_library.instance().list_books()
        question = re.sub(r"\s+", "", body["text"])
        earlier = re.sub(r"\s+", "", previous_question(body))
        follow_up = bool(earlier) and (len(question) <= FOLLOW_UP_CHARS or bool(FOLLOW_UP.search(question)))
        targets = [selected["id"]] if selected and selected.get("id") else []
        targets += [book_id for book_id in named_books(question, books) if book_id not in targets]
        if follow_up and not targets:
            targets = named_books(earlier, books)
        if not targets:
            return ""
        targets = targets[:3]
        # Books the reader has opened are searched only up to the furthest chapter reached, unless
        # they ask for what comes later: a rule the retrieval keeps, not a request to the model.
        spoilers = wants_spoilers(question)
        up_to = {} if spoilers else book_library.instance().read_up_to(targets)
        search_for = body["text"] + ("\n" + earlier if follow_up else "")
        hits = text_search().search(targets, search_for, up_to=up_to)
    except (sqlite3.Error, OSError, book_library.SourceError):
        return ""
    names = {book["id"]: book.get("title", "") for book in books}
    lines = [f"【《{names.get(hit['book_id'], '')}》{chapter_label(hit['chapter'], hit['chapter_title'])}】{hit['text']}"
             for hit in hits]
    for book_id, chapter in up_to.items():
        lines.append(f"（读者读到《{names.get(book_id, '')}》第 {chapter + 1} 章，片段只取自这一章及之前；"
                     "之后的情节不要讲，读者明确想听后面的内容时才可以。）")
    if spoilers and hits:
        lines.append("（读者明确表示想听后面的情节，可以讲，但先提醒一句会剧透。）")
    # With no passage but a book in progress, the note alone still stops a spoiler from memory.
    return "\n".join(lines) if hits or up_to else ""


def _chain(first, rest):
    yield first
    yield from rest


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

    def _refuse(self, status, payload):
        """Answer an early refusal cleanly. A small body is read first: closing a Windows socket
        that still holds unread data resets the connection, and the client then sees "connection
        aborted" instead of this status. Anything larger is left unread and the connection closed."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if 0 < length <= 65_536:
            try:
                self.rfile.read(length)
            except OSError:
                pass
        self.close_connection = True
        self._send_json(status, payload)

    def _cross_site(self):
        """True when a browser reports that another site's page sent this request.

        A loopback address does not prove the reader asked for it: any page open in a browser on
        this machine can post to 127.0.0.1:8090 too, and a text/plain body is a "simple" request
        that needs no preflight. Browsers always label such a request — Sec-Fetch-Site, and an
        Origin on every POST — so a mismatch is refused. A request with neither header did not
        come from a web page (curl, the tests), and no page can strip them."""
        site = self.headers.get("Sec-Fetch-Site")
        if site and site not in ("same-origin", "none"):
            return True
        origin = self.headers.get("Origin")
        if origin is None:
            return False
        # "null" (sandboxed frames, file://) has no netloc and so never matches.
        host = (self.headers.get("Host") or "").lower()
        return urllib.parse.urlsplit(origin).netloc.lower() != host

    def _loopback_only(self):
        """The settings surface belongs to the person at this machine.

        The default bind is loopback already, but HOST can be widened for a LAN deployment, and
        the settings page must not become remotely writable if it is. The Host header must name
        loopback as well: DNS rebinding points an attacker's domain at 127.0.0.1, which makes its
        page same-origin with this one — only the name it asked for gives it away."""
        try:
            loopback = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            loopback = False
        host = urllib.parse.urlsplit("//" + (self.headers.get("Host") or "")).hostname or ""
        if not loopback or host.rstrip(".").lower() not in LOOPBACK_NAMES:
            self._refuse(403, {"error": "本机设置只能从本机访问"})
            return False
        if self._cross_site():
            self._refuse(403, {"error": "本机设置不接受来自其它网页的请求"})
            return False
        return True

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
        # The download itself runs in a worker thread so this reply is immediate and the page can
        # poll /update/progress while 99 MB arrive.
        ok, message = updater.begin(ROOT, install_root(), update_token(), os.getpid(),
                                    stop_everything, restart_args=self.server.restart_args)
        self._send_json(200 if ok else 409, {"ok": ok, "message": message})

    def _read_json(self, limit=MAX_JSON_BODY):
        """One small JSON body, or None after answering the request itself."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > limit:
            self._send_json(413, {"error": "请求体超出限制"})
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求体不是合法 JSON"})
            return None

    # --- routes ------------------------------------------------------------
    def do_GET(self):
        if book_library.handle_request(self):
            return
        pathname = self.path.split("?", 1)[0]
        if pathname == "/healthz":
            self._send_json(200, {"app": "hexu-library", "pid": os.getpid(), "asr_ready": model_state()[0],
                                  "semantic_ready": llm_state()[0] is not None})
            return
        if pathname == "/asr/ready":
            ready, payload = model_state()
            self._send_json(200 if ready else 503, payload)
            return
        if pathname == "/memory/state":
            if self._loopback_only():
                peek = "peek=1" in self.path  # the page's greeting: never creates the file
                self._send_json(200, (reader_memory.snapshot_if_present if peek
                                      else reader_memory.instance().snapshot)(describe_book))
            return
        if pathname == "/tts/ready":
            ready, payload = SPEAKER.state()
            self._send_json(200 if ready else 503, payload)
            return
        if pathname in ("/understand/ready", "/chat/ready"):
            if pathname == "/chat/ready" and not self._loopback_only():
                return
            key, resolved, payload = llm_state()
            payload["configuration"] = llm_chat.configuration(resolved)
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
            self._send_json(200, updater.status(ROOT, install_root(), update_token(),
                                                refresh="refresh=1" in self.path))
            return
        if pathname == "/update/progress":
            if not self._loopback_only():
                return
            self._send_json(200, updater.progress())
            return

        target = self._static_path(pathname)
        if target is None:
            self.send_error(403, "Forbidden")
            return
        self._serve_static(target)

    def _send_audio(self, target):
        """Single byte ranges let the browser seek without downloading the whole MP3 again."""
        size = target.stat().st_size
        start, end = 0, size - 1
        byte_range = None if self.headers.get("If-Range") else self.headers.get("Range")
        if byte_range:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range)
            valid = bool(match and (match[1] or match[2]))
            if valid:
                start = int(match[1]) if match[1] else max(0, size - int(match[2]))
                end = min(int(match[2]), end) if match[1] and match[2] else end
                valid = start < size and start <= end and bool(match[1] or int(match[2]) > 0)
            if not valid:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if byte_range else 200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if byte_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with target.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Switching tracks cancels the previous browser request.

    def _send_file(self, target):
        """Serve a file, revalidating instead of re-sending.

        The model is 18 MiB and the uplink is the bottleneck, so a repeat visit must not
        transfer it again: an ETag lets the browser revalidate and take a 304. A pre-compressed
        sibling is used when the client accepts gzip — the deploy step writes those, which keeps
        this process read-only."""
        if target.suffix == ".mp3":
            self._send_audio(target)
            return
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

    def _post_understand(self, conversation=False):
        body = self._read_json(128_000 if conversation else MAX_JSON_BODY)
        if body is None:
            return
        wait = UNDERSTAND_LIMIT.allow(self.client_address[0])
        if wait:
            # The page shows this and falls back to the local rules, exactly as when no model is
            # configured; nothing is sent to the provider.
            self.send_response(429)
            payload = json.dumps({"action": "none", "error": f"语义服务调用过于频繁，请 {wait} 秒后再试"}).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Retry-After", str(wait))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "请求必须是 JSON 对象"})
            return
        if conversation:
            resolved, _ = settings_state()
            selected = load_catalog()[0].get(str(body.get("bookId", "")))
            status, payload = llm_chat.chat(body, resolved, validate_endpoint,
                                          timeout=float(os.environ.get("HEXU_LLM_CHAT_TIMEOUT", "60")),
                                          selected=selected, memory=memory_context(body),
                                          passages=book_passages(body, selected))
        else:
            status, payload = understand(body.get("text"), body.get("phase"))
        self._send_json(status, payload)

    def _post_chat_stream(self):
        """Stream one reply as NDJSON: {"type":"delta","text":...} lines, then "done" or "error".

        Validation failures still answer with a plain JSON status before any streaming starts.
        Once streaming, the connection closes at the end, so no Content-Length is needed; if the
        reader cancels, the broken pipe stops the generator, which closes the provider request."""
        body = self._read_json(128_000)
        if body is None:
            return
        wait = UNDERSTAND_LIMIT.allow(self.client_address[0])
        if wait:
            self._send_json(429, {"error": f"对话调用过于频繁，请 {wait} 秒后再试"})
            return
        resolved, _ = settings_state()
        catalog = load_catalog()[0]
        selected = catalog.get(str(body.get("bookId", ""))) if isinstance(body, dict) else None
        phase = body.get("phase") if isinstance(body, dict) else None
        app = app_actions.AppActions(phase, describe_book(selected["id"]) if selected else None, catalog)
        events = llm_chat.chat_stream(body, resolved, validate_endpoint,
                                      timeout=float(os.environ.get("HEXU_LLM_CHAT_TIMEOUT", "60")),
                                      selected=selected, memory=memory_context(body),
                                      passages=book_passages(body, selected), app=app)
        first = next(events, None)
        if first is None or (first["type"] == "error" and "status" in first):
            first = first or {"error": "对话服务没有返回内容"}
            self._send_json(first.pop("status", 502), {k: v for k, v in first.items() if k != "type"})
            return
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in _chain(first, events):
                self.wfile.write(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            events.close()

    def _post_settings_key(self):
        """Store what the reader typed. The reply carries the new summary, never the value."""
        body = self._read_json()
        if body is None:
            return
        updates = {}
        for field, name in (("key", "HEXU_LLM_API_KEY"), ("baseUrl", "HEXU_LLM_BASE_URL"),
                            ("model", "HEXU_LLM_MODEL"),
                            ("webEnabled", "HEXU_WEB_ENABLED"), ("webKey", "HEXU_WEB_API_KEY"),
                            ("updateToken", "HEXU_GITHUB_TOKEN")):
            if field in body:
                value = body.get(field)
                if not isinstance(value, str) or "\n" in value or "\r" in value:
                    self._send_json(400, {"error": "设置必须是单行文本"})
                    return
                if field == "webEnabled" and value not in ("0", "1"):
                    self._send_json(400, {"error": "联网开关无效"})
                    return
                updates[name] = value
        save_settings(updates)
        self._send_json(200, {"ok": True, "message": "已保存。下一次说话就会用新的设置。",
                              **settings_summary()})

    def _post_settings_test(self):
        """Prove the whole path with one real, tiny request: key, address, TLS and parsing."""
        resolved, _ = settings_state()
        status, payload = llm_chat.chat({"text": "请只回答：连接成功", "web": False}, resolved, validate_endpoint)
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

    def _post_memory(self, pathname):
        body = self._read_json(128_000 if pathname == "/memory/summarize" else MAX_JSON_BODY)
        if body is None:
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "请求必须是 JSON 对象"})
            return
        memory = reader_memory.instance()
        try:
            if pathname == "/memory/fact":
                self._send_json(200, {"ok": True, "fact": memory.add_fact(body.get("text"))})
            elif pathname == "/memory/reading":
                self._send_json(200, {"ok": memory.record_opened(body.get("bookId"))})
            elif pathname == "/memory/delete":
                self._send_json(200, {"ok": memory.delete(body.get("kind"), body.get("id"))})
            elif pathname == "/memory/clear":
                memory.clear()
                self._send_json(200, {"ok": True})
            elif pathname == "/memory/enabled":
                self._send_json(200, {"ok": True, "enabled": memory.set_enabled(body.get("enabled") is True)})
            elif pathname == "/memory/inference":
                self._send_json(200, {"ok": True, "inference": memory.set_inference(body.get("enabled") is True)})
            elif pathname == "/memory/profile":  # the reader's own edit; "" clears it
                self._send_json(200, {"ok": memory.set_profile(body.get("text"), by_reader=True),
                                      "profile": memory.profile()})
            elif pathname == "/memory/summarize":
                self._post_memory_summary(memory, body)
            else:
                self.send_error(404, "Not found")
        except PermissionError as error:
            self._send_json(409, {"error": str(error)})
        except ValueError as error:
            self._send_json(400, {"error": str(error)})

    def _post_memory_summary(self, memory, body):
        if not memory.enabled():
            self._send_json(200, {"summary": "", "skipped": "记忆已关闭"})
            return
        wait = UNDERSTAND_LIMIT.allow(self.client_address[0])
        if wait:
            self._send_json(429, {"error": f"调用过于频繁，请 {wait} 秒后再试"})
            return
        resolved, _ = settings_state()
        # Guessing on: the same call also proposes changes to 小和's notes and the impression.
        record = None
        if memory.inference():
            record = {"facts": [fact["text"] for fact in memory.snapshot(lambda _: None)["facts"]],
                      "notes": [{"id": note["id"], "text": note["text"]} for note in memory.active_notes()],
                      "profile": memory.profile()}
        status, payload = llm_chat.summarize(body.get("history"), resolved, validate_endpoint, record=record)
        if status != 200:
            self._send_json(status, payload)
            return
        if payload.get("summary"):
            memory.add_summary(payload["summary"], len(body.get("history") or []) // 2, payload.get("importance"))
        applied = memory.apply_notes(payload.get("notes")) if record is not None else 0
        profiled = bool(record is not None and payload.get("profile") and memory.set_profile(payload["profile"]))
        # The page needs only to know what happened, not the proposals themselves.
        self._send_json(200, {"summary": payload.get("summary", ""), "notes": applied, "profile": profiled})

    def _post_tts(self):
        if not SPEAKER.state()[0]:
            self._refuse(503, {"error": "本机语音模型不可用"})
            return
        wait = SPEECH_LIMIT.allow(self.client_address[0])
        if wait:
            self._refuse(429, {"error": "朗读请求过于频繁"})
            return
        body = self._read_json()
        if body is None:
            return
        try:
            audio = SPEAKER.synthesize(body.get("text") if isinstance(body, dict) else None)
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return
        self._send(200, audio, "audio/wav")

    def do_POST(self):
        # Recognition, the semantic layer and the reading library cost CPU, the reader's model
        # quota and their own shelf; none of it is for other sites' pages to spend or rewrite.
        # Checked before the library routes too, which also honour Sec-Fetch-Site this way.
        if self._cross_site():
            self._refuse(403, {"error": "不接受来自其它网页的请求"})
            return
        if book_library.handle_request(self):
            return
        pathname = self.path.split("?", 1)[0]
        if pathname == "/chat":
            if self._loopback_only():
                self._post_understand(conversation=True)
            return
        if pathname == "/chat/stream":
            if self._loopback_only():
                self._post_chat_stream()
            return
        if pathname == "/understand":
            self._post_understand()
            return
        if pathname == "/tts":
            self._post_tts()
            return
        if pathname.startswith("/memory/"):
            if self._loopback_only():
                self._post_memory(pathname)
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
        if pathname == "/asr/stream":
            self._post_asr_stream()
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


    def _post_asr_stream(self):
        """One chunk of a page's continuous audio (16 kHz mono 16-bit PCM, ?session=<id>):
        answers the wake words heard and the utterances finished since the last chunk."""
        if not (model_state()[0] and LISTENER.state()[0]):
            self._send_json(503, {"error": "连续收听不可用"})
            return
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        identifier = (query.get("session") or [""])[0]
        if (query.get("end") or [""])[0] == "1":  # the page stopped listening
            LISTENER.close(identifier)
            self._send_json(200, {"events": [], "speaking": False})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > listener.MAX_CHUNK_SECONDS * listener.RATE * 2:
                raise ValueError("音频块无效")
            session = LISTENER.session(identifier)
            samples = listener.samples_from_pcm(self.rfile.read(length))
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return

        def recognize(audio):
            try:
                return decode(audio)
            except TimeoutError:
                return ""

        events, speaking = session.feed(samples, recognize)
        self._send_json(200, {"events": events, "speaking": speaking})


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


def utf8_streams():
    """Let a piped or console run print Chinese on any Windows code page.

    A script-mode start under a test harness, Git Bash or a legacy console may hand Python a
    pipe encoded with the machine's ANSI code page (cp950, cp936, ...). Printing the startup
    banner then raised UnicodeEncodeError before the server ever bound its port, so the tests
    saw only "asr-server did not start". Everything the project writes is UTF-8 already, and a
    real Windows console is UTF-8 too, so reconfiguring changes nothing there."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


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


def install_root():
    """The folder holding the program itself — what an update replaces.

    Not the site root: a packaged build serves from `_internal` inside the program folder, and the
    thing a release archive overwrites is the folder around it.

    Running from a source checkout there is no such folder. An update there would mirror a release
    over the repository — robocopy /MIR deletes what the new version does not contain — so a
    checkout is not updatable at all, and says so instead. Rebuilding is what a checkout does."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return None


def user_environment(name):
    """One variable from the user scope, where `setx` puts it.

    A process inherits the environment as it was when it started, so a token added while this
    program was already running is invisible to it. Reading the variable at its source makes
    "put it in GITHUB_TOKEN" work whether the program started before or after."""
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
        return value if isinstance(value, str) else ""
    except OSError:
        return ""


def update_token():
    """The token the release check needs, per request and never cached.

    The repository is private, so the API cannot be asked without one. `GITHUB_TOKEN` first — the
    same variable the release tool reads — then the reader's own settings file, which is where a
    machine that never sees this checkout can put it from the settings page."""
    for candidate in (os.environ.get("GITHUB_TOKEN", ""), user_environment("GITHUB_TOKEN")):
        if candidate.strip():
            return candidate.strip()
    resolved, _ = settings_state()
    return resolved.get("HEXU_GITHUB_TOKEN", "").strip()


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
    if not options["browser"]:
        return False
    return frozen() and os.name == "nt"


def window_icon():
    """The window's icon, from the site the window is showing."""
    icon = ROOT / "public" / "favicon.ico"
    return icon if icon.is_file() else None


def show_window(url):
    """Show the page in a native window, or report that none could be shown.

    True means the window was shown and has now been closed — the reader quitting, which is how
    this program is meant to stop. False means there was nothing to show, so the caller should
    fall back to something visible rather than leave the reader staring at nothing."""
    try:
        import window_host
    except Exception as error:
        print(f"内嵌窗口不可用（{type(error).__name__}: {error}）", flush=True)
        return False
    ready, reason = window_host.available()
    if not ready:
        print(f"内嵌窗口不可用：{reason}", flush=True)
        return False
    return window_host.run(url, icon=window_icon())


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
        ok, message = window_host.microphone_report(url, icon=window_icon())
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
    """Report whether a newer release exists, then exit.

    0 = already current, 1 = an update is available, 2 = could not be determined. The same three
    answers the settings page shows, so a script and a reader never disagree."""
    resolved, _ = settings_state()
    payload = updater.status(ROOT, install_root(), update_token(), refresh=True)
    installed = payload["installed"]
    latest = payload.get("latest") or {}
    lines = [
        f"已安装   {installed.get('version') or '（未记录）'}"
        f"  {installed.get('commit', '')[:12]}  {installed.get('built_at') or ''}".rstrip(),
        f"最新版本 {latest.get('tag') or '（读不到）'}"
        + (f"  发布于 {latest.get('published_at', '')[:10]}" if latest else ""),
        f"安装目录 {payload.get('install_root', '')}",
        f"状态     {payload['reason']}",
    ]
    if latest.get("notes"):
        lines.extend(["", latest["notes"]])
    note("\n".join(lines))
    if payload["state"] == "up-to-date":
        return 0
    if payload["state"] in ("update-available", "unknown"):
        return 1
    return 2


def automatic_updates(interval=300, restart_args=()):
    """Check at startup and every five minutes; a complete release installs without a UI click."""
    if install_root() is None or _stop.wait(1.5):
        return
    while not _stop.is_set():
        if not updater.busy():
            try:
                info = updater.status(ROOT, install_root(), update_token(), refresh=True)
                if info.get("can_apply"):
                    updater.begin(ROOT, install_root(), update_token(), os.getpid(), stop_everything,
                                  restart_args=restart_args)
            except Exception:
                pass  # Network errors remain visible in /update/status and retry next cycle.
        if _stop.wait(interval):
            return


def main():
    attach_console()
    utf8_streams()
    options = parse_argv(sys.argv[1:])

    if options["check_mic"]:
        return microphone_check()
    if options["check_update"]:
        return update_check()

    existing = running_instance(HOST, options["port"])
    if existing:
        print(f"和序图书馆已经在运行：{existing}", flush=True)
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
    print(f"和序图书馆 · {address}", flush=True)
    print(f"  站点根目录 {ROOT}", flush=True)
    ready, info = model_state()
    print(f"  识别模型   {MODEL_DIR}", flush=True)
    print(f"             {'就绪' if ready else '不可用 —— ' + info.get('reason', '')}", flush=True)
    voiced, voice = SPEAKER.state()
    print(f"  语音播报   {voice['model']} · {voice['voice']} · "
          f"{'就绪' if voiced else '不可用（改用浏览器系统语音）—— ' + voice.get('reason', '')}", flush=True)
    key, _, semantic = llm_state()
    print(f"  语义解析   {semantic['model']} · {'已配置' if key else '未配置'}"
          f"（在 {address}settings 里填写）", flush=True)

    # Serving moves to a background thread so the window loop can own the main thread, which is
    # where WinForms needs its message loop.
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=warm_model, daemon=True).start()
    threading.Thread(target=SPEAKER.warm, daemon=True).start()
    restart_args = ("--port", str(server.server_address[1]))
    if not options["browser"]:
        restart_args += ("--no-browser",)
    if options["window"] is True:
        restart_args += ("--window",)
    elif options["browser"] and not window_mode(options):
        restart_args += ("--browser",)
    server.restart_args = restart_args
    threading.Thread(target=automatic_updates, args=(300, restart_args), daemon=True).start()

    if window_mode(options):
        if show_window(address):
            server.shutdown()
            server.server_close()
            return 0
        print("无法显示程序窗口，已改用浏览器打开。", flush=True)
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
