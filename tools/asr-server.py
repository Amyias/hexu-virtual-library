"""Serve the library and transcribe recorded speech, in one process.

Deployment counterpart to tools/serve.mjs. It exists because the browser's own Web Speech API
is unusable on some networks: the API is hard-wired to the browser vendor's cloud service and
its endpoint cannot be pointed elsewhere, so recognition starts and then never returns a
result. Here the page records a segment and posts it, and the transcript comes back from a
local model — no outbound request is made by this server at all.

    HEXU_ASR_MODEL_DIR=/opt/.../sherpa-onnx-sense-voice-... python tools/asr-server.py

Routes:
    GET  /asr/ready   -> {"ready": bool, ...}  the page probes this and only then uses /asr
    POST /asr         -> 16 kHz mono WAV body, returns {"text": ...}
    GET  <anything>   -> static file under the project root

Recogniser usage mirrors a known-good pattern already running on this host; the model files are
referenced read-only and never copied.
"""
import io
import json
import os
import re
import sys
import threading
import time
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

        target = self._static_path(pathname)
        if target is None:
            self.send_error(403, "Forbidden")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self.send_error(404, "Not found")
            return
        try:
            body = target.read_bytes()
        except OSError:
            self.send_error(500, "Read failed")
            return
        self._send(200, body, MIME.get(target.suffix, "application/octet-stream"))

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
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
