"""Continuous listening for the server recogniser: the page streams raw audio here, and this
answers two questions as the audio arrives.

    Was 「小和」 just said?   A keyword spotter (a 3.3M-parameter streaming zipformer that only
                             decodes the given words) hears the name the moment it is spoken,
                             instead of at the end of the sentence the way a transcript would.
    Is an utterance over?    Silero VAD, a small neural voice detector, cuts speech from silence.
                             Unlike the loudness threshold it replaces, a cough, a click or a fan
                             is not speech, and a pause to think does not end the sentence early.

Each finished utterance is handed to the recogniser (SenseVoice, tools/asr-server.py) and comes
back as an event. The page polls with the next chunk of audio, so nothing is pushed and no audio
is dropped while a sentence is being transcribed.

Models live in their own small folder (about 6 MB, see tools/package-local.mjs): beside the site in
a packaged build, .cache/models/listen/ in a checkout, or HEXU_LISTEN_MODEL_DIR. Without them the
server reports streaming as unavailable and the page keeps uploading whole segments as before.

The wake word is matched by sound, as initials and finals with tones: 小何, 小河, 小禾 and 晓和
are all 「x iǎo h é」. The other entries cover the tones a recogniser most often mishears
(小鹤 / 小贺, 肖和 / 萧何, 小喝). 「小河边」 therefore wakes 小和 too: it sounds the same.
"""
import os
import re
import threading
import time
from pathlib import Path

RATE = 16000
FILES = {
    "vad": "silero_vad.onnx",
    "encoder": "kws-encoder.int8.onnx",
    "decoder": "kws-decoder.int8.onnx",
    "joiner": "kws-joiner.int8.onnx",
    "tokens": "kws-tokens.txt",
}
# The wake words, one source: copied beside the models when packaging, read from here otherwise.
KEYWORDS_FILE = Path(__file__).resolve().parent / "listen-keywords.txt"
# Lower hears 小和 more readily and wakes more often by mistake. Measured on the synthetic
# evaluation clips (docs/VOICE_EVAL.md): 0.25 missed 5 of 61, 0.2 missed 3, 0.15 missed 2, with
# the same two false wakes (小河边, 小何) at every setting. Tune on real recordings.
WAKE_THRESHOLD = float(os.environ.get("HEXU_WAKE_THRESHOLD", "0.2"))
MIN_SILENCE = 0.5  # seconds of quiet that end an utterance (the loudness rule waited 0.7)
MAX_SPEECH = 15.0
MAX_CHUNK_SECONDS = 4.0  # one request's audio; the page sends about a quarter of a second
SESSION_IDLE = 30.0  # a page that stopped sending is forgotten after this long
MAX_SESSIONS = 4
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
WAKE_SLACK = 0.3  # a wake heard this soon after an utterance ended still belongs to it


def keywords():
    """The keyword lines of the keywords file, without its comments."""
    return [line.strip() for line in KEYWORDS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


CJK = re.compile(r"[一-鿿]")


def request_after_name(text):
    """The request in an utterance the spotter heard 小和 in, without the name.

    The recogniser often writes the name as something else (笑河, 萧何, 教和, 小亨, even 可以),
    and then the leftover would be taken for a request: 「笑河读正文」 has no 「小和」 to strip.
    The spotter says the name was there but not exactly when, so it is found by sound instead:
    two characters near the start read xiao/jiao…-h… (or -e). An utterance of two or so
    characters with no such pair was the name alone, misheard."""
    from pypinyin import lazy_pinyin

    marks = [(index, char) for index, char in enumerate(text) if CJK.match(char)]
    sounds = lazy_pinyin([char for _, char in marks])
    for k in range(min(3, len(marks) - 1)):
        first, second = sounds[k], sounds[k + 1]
        if first.endswith("iao") and (second.startswith("h") or second in ("e", "ge", "ke")):
            return text[marks[k + 1][0] + 1:].lstrip(" ，,。.、！!？?：:")
    if len(marks) <= 2:
        return ""
    if sounds[0] == "he":  # only the end of the name survived: 「和下一页」
        return text[marks[0][0] + 1:].lstrip(" ，,。.、！!？?：:")
    return text


def model_dir(site_root=None, frozen=False):
    override = os.environ.get("HEXU_LISTEN_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if frozen and site_root:
        return Path(site_root) / "listen-models"
    return Path(__file__).resolve().parents[1] / ".cache" / "models" / "listen"


class Session:
    """One page's microphone: its own detector state, fed in order."""

    def __init__(self, listener):
        import sherpa_onnx

        self.listener = listener
        self.vad = sherpa_onnx.VoiceActivityDetector(listener.vad_config, buffer_size_in_seconds=30)
        self.stream = listener.spotter.create_stream()
        self.received = 0  # samples so far, the clock every event is measured on
        self.wakes = []  # seconds at which the wake word was heard, kept until its utterance ends
        self.used = time.monotonic()
        self.lock = threading.Lock()

    def feed(self, samples, recognize):
        """Events for one chunk of 16 kHz float samples:
        {"type": "wake", "at"} as soon as 小和 is heard, and {"type": "text", "text", "start",
        "end", "seconds", "woke"} for each finished utterance (woke: the wake word was heard
        inside it, so the page has answered it already)."""
        events = []
        with self.lock:
            self.used = time.monotonic()
            self.received += len(samples)
            now = self.received / RATE
            with self.listener.spotter_lock:
                self.stream.accept_waveform(RATE, samples)
                while self.listener.spotter.is_ready(self.stream):
                    self.listener.spotter.decode_stream(self.stream)
                    if self.listener.spotter.get_result(self.stream):
                        self.listener.spotter.reset_stream(self.stream)
                        self.wakes.append(now)
                        events.append({"type": "wake", "at": round(now, 2)})
            self.vad.accept_waveform(samples)
            while not self.vad.empty():
                segment = self.vad.front
                start = segment.start / RATE
                end = start + len(segment.samples) / RATE
                audio = segment.samples
                self.vad.pop()
                woke = any(start <= at <= end + WAKE_SLACK for at in self.wakes)
                self.wakes = [at for at in self.wakes if at > end + WAKE_SLACK]
                started = time.perf_counter()
                text = recognize(audio)
                event = {"type": "text", "text": text, "start": round(start, 2), "end": round(end, 2),
                         "at": round(now, 2), "seconds": round(time.perf_counter() - started, 3),
                         "woke": woke}
                if woke:
                    event["request"] = request_after_name(text)
                events.append(event)
            # A wake with no utterance around it (a breath of 「小和」 the detector let through) must
            # not mark the next sentence, said much later, as already answered.
            self.wakes = [at for at in self.wakes if now - at < MAX_SPEECH]
            speaking = self.vad.is_speech_detected()
        return events, speaking


class Listener:
    """The loaded models and the open sessions. state() says whether it can run at all."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.spotter = None
        self.vad_config = None
        self.failure = None
        self.sessions = {}
        self.lock = threading.Lock()
        self.spotter_lock = threading.Lock()  # the spotter's decoder is shared between sessions

    def state(self):
        missing = [name for name in FILES.values() if not (self.directory / name).is_file()]
        if not self.keywords_file().is_file():
            missing.append(KEYWORDS_FILE.name)
        if missing:
            return False, "缺少连续收听模型：" + "、".join(missing)
        if self.failure is None:
            try:
                self._load()
                self.failure = ""
            except Exception as error:  # an unloadable model must not take recognition down
                self.failure = f"连续收听模型无法加载：{error}"
        return (not self.failure), self.failure

    def _load(self):
        import sherpa_onnx

        path = lambda key: str(self.directory / FILES[key])  # noqa: E731
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=path("tokens"), encoder=path("encoder"), decoder=path("decoder"),
            joiner=path("joiner"), keywords_file=str(self.keywords_file()), num_threads=1,
            keywords_threshold=WAKE_THRESHOLD, keywords_score=1.0, max_active_paths=4,
            num_trailing_blanks=1)
        self.vad_config = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=path("vad"), threshold=0.5, min_silence_duration=MIN_SILENCE,
                min_speech_duration=0.25, window_size=512, max_speech_duration=MAX_SPEECH),
            sample_rate=RATE, num_threads=1)

    def keywords_file(self):
        packaged = self.directory / KEYWORDS_FILE.name
        return packaged if packaged.is_file() else KEYWORDS_FILE

    def session(self, identifier):
        """The session for a page's id, opened on first use; ValueError for a malformed id."""
        if not isinstance(identifier, str) or not SESSION_ID.match(identifier):
            raise ValueError("会话标识无效")
        now = time.monotonic()
        with self.lock:
            for key in [key for key, value in self.sessions.items() if now - value.used > SESSION_IDLE]:
                del self.sessions[key]
            found = self.sessions.get(identifier)
            if found is None:
                if len(self.sessions) >= MAX_SESSIONS:
                    oldest = min(self.sessions, key=lambda key: self.sessions[key].used)
                    del self.sessions[oldest]
                found = self.sessions[identifier] = Session(self)
            return found

    def close(self, identifier):
        with self.lock:
            self.sessions.pop(identifier, None)


def samples_from_pcm(raw):
    """16-bit little-endian mono PCM → float samples; ValueError for anything else."""
    import numpy as np

    if not raw or len(raw) % 2 or len(raw) > MAX_CHUNK_SECONDS * RATE * 2:
        raise ValueError("音频块无效")
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
