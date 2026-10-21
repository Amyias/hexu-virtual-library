"""Local Taiwan-Mandarin voice for 小和's spoken replies: PrimeTTS v2.1, voice 欣然 (Xinran).

The page's own speechSynthesis only reaches the voices Windows ships, and inside the program's
WebView2 window those are the old concatenative ones. This turns a reply into 16 kHz WAV on this
machine instead: text -> bopomofo phones -> one ONNX model. Nothing leaves the host. Without the
model file /tts/ready answers 503 and the page keeps using speechSynthesis (src/voice/voice.js).

The phone frontend is adapted from PrimeTTS's scripts/frontend_bopomofo.py (Apache-2.0, see
tools/primetts/NOTICE.md): the same 88-symbol table and the same rules, but readings come from
pypinyin rather than g2pW, which would add several hundred megabytes of BERT model to the
download. English is reduced to what the library actually says aloud: single letters (the A / B
shelf faces, HX numbers) and the English digit words text_norm uses when it spells a code.
"""
import io
import re
import threading
import wave
from pathlib import Path

MODEL_FILE_NAME = "primetts_v21_3voice.onnx"
MODEL_SHA256 = "0cf64ad010a9b92201222533900ece31562a0181e7a8e435e5de83b3d72b4bdf"
MODEL_BYTES = 116_947_806
SAMPLE_RATE = 16000
VOICE = {"id": 0, "name": "欣然", "model": "PrimeTTS v2.1"}  # sid 0 = Xinran, female
MAX_CHARS = 400  # one request; the page splits longer replies into sentences
TAIL_SILENCE = 0.12  # seconds, so consecutive sentences do not run together

# Symbol order must match the trained embedding exactly (frontend_bopomofo.SYMBOLS).
SPECIAL = ["_blank", "_pad", "UNK", "SP"]
ZHUYIN = [chr(c) for c in range(0x3105, 0x312A)]
ARPABET = ["AA", "AE", "AH", "AO", "AW", "AY", "B", "CH", "D", "DH", "EH", "ER", "EY", "F", "G",
           "HH", "IH", "IY", "JH", "K", "L", "M", "N", "NG", "OW", "OY", "P", "R", "S", "SH", "T",
           "TH", "UH", "UW", "V", "W", "Y", "Z", "ZH"]
PUNCT = [",", ".", "?", "!", "…", "-", "'"]
SYLLABIC = ["ㄭ"]  # empty-rime vowel of 是/十/日/司, appended after the original 87 symbols
SYMBOLS = SPECIAL + ZHUYIN + ARPABET + PUNCT + SYLLABIC
SYM2ID = {symbol: index for index, symbol in enumerate(SYMBOLS)}
ZH, EN = 0, 1
TONE_MARKS = {"ˊ": 2, "ˇ": 3, "ˋ": 4, "˙": 5}

LETTERS = {
    "A": ["EY1"], "B": ["B", "IY1"], "C": ["S", "IY1"], "D": ["D", "IY1"], "E": ["IY1"],
    "F": ["EH1", "F"], "G": ["JH", "IY1"], "H": ["EY1", "CH"], "I": ["AY1"], "J": ["JH", "EY1"],
    "K": ["K", "EY1"], "L": ["EH1", "L"], "M": ["EH1", "M"], "N": ["EH1", "N"], "O": ["OW1"],
    "P": ["P", "IY1"], "Q": ["K", "Y", "UW1"], "R": ["AA1", "R"], "S": ["EH1", "S"],
    "T": ["T", "IY1"], "U": ["Y", "UW1"], "V": ["V", "IY1"], "W": ["D", "AH1", "B", "AH0", "L", "Y", "UW0"],
    "X": ["EH1", "K", "S"], "Y": ["W", "AY1"], "Z": ["Z", "IY1"],
}
WORDS = {
    "zero": ["Z", "IH1", "R", "OW0"], "one": ["W", "AH1", "N"], "two": ["T", "UW1"],
    "three": ["TH", "R", "IY1"], "four": ["F", "AO1", "R"], "five": ["F", "AY1", "V"],
    "six": ["S", "IH1", "K", "S"], "seven": ["S", "EH1", "V", "AH0", "N"], "eight": ["EY1", "T"],
    "nine": ["N", "AY1", "N"],
}
CHINESE_DIGITS = dict(zip("0123456789", "零一二三四五六七八九"))


def speak_library_codes(text):
    """Read catalogue codes the way a librarian would, before the generic normaliser spells them
    out letter by letter in English: S2-A-L4-P284 is 第二架A面第四层第二百八十四本, and the
    digits of HX-03408 are read one by one in Chinese."""
    import cn2an

    def location(match):
        shelf, side, layer, slot = match.groups()
        return (f"第{cn2an.an2cn(int(shelf))}架{side.upper()}面第{cn2an.an2cn(int(layer))}层"
                f"第{cn2an.an2cn(int(slot))}本")

    text = re.sub(r"\bS(\d)-([AaBb])-L(\d)-P(\d{1,3})\b", location, text)
    return re.sub(r"\bHX-?(\d{1,5})\b",
                  lambda m: "H X " + "".join(CHINESE_DIGITS[d] for d in m.group(1)), text)


def _syllable(reading):
    """pypinyin's 'ㄓㄨㄢˇ' -> (['ㄓ','ㄨ','ㄢ'], 3); first tone carries no mark."""
    tone = 1
    for mark, value in TONE_MARKS.items():
        if mark in reading:
            tone, reading = value, reading.replace(mark, "")
    units = [unit for unit in reading if unit in SYM2ID]
    if len(units) == 1 and units[0] in "ㄓㄔㄕㄖㄗㄘㄙ":
        units.append("ㄭ")
    return units, tone


def _english(word):
    phones = WORDS.get(word.lower())
    if phones is None:  # anything else is spelled; the app never needs whole English words read
        phones = [phone for letter in word.upper() for phone in LETTERS.get(letter, [])]
    for phone in phones:
        stress = int(phone[-1]) if phone[-1].isdigit() else 0
        yield phone.rstrip("012"), stress


def text_to_ids(text):
    """Phone, tone and language ids for one utterance, as the model's encoder expects them."""
    from pypinyin import Style, pinyin

    from primetts import text_norm

    text = text_norm.normalize(speak_library_codes(text))
    readings = pinyin(text, style=Style.BOPOMOFO, errors=lambda run: [None] * len(run))
    phones, tones, langs = [], [], []

    def add(phone, tone, lang):
        phones.append(phone)
        tones.append(min(tone, 5))
        langs.append(lang)

    index = 0
    while index < len(text):
        char = text[index]
        reading = readings[index][0] if index < len(readings) else None
        if reading:
            units, tone = _syllable(reading)
            for unit in units:
                add(unit, tone, ZH)
            index += 1
        elif re.match(r"[A-Za-z]", char):
            end = index
            while end < len(text) and re.match(r"[A-Za-z']", text[end]):
                end += 1
            for phone, stress in _english(text[index:end]):
                add(phone, stress, EN)
            add("SP", 0, EN)
            index = end
        else:
            if char in PUNCT:
                add(char, 0, ZH)
            elif not char.strip() and phones and phones[-1] != "SP":
                add("SP", 0, ZH)
            index += 1
    return {
        "phones": phones,
        "phone_ids": [SYM2ID.get(phone, SYM2ID["UNK"]) for phone in phones],
        "tone_ids": tones,
        "lang_ids": langs,
    }


def wav_bytes(samples, rate=SAMPLE_RATE):
    import numpy as np

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


class Speaker:
    """One loaded model, shared by the server's request threads."""

    def __init__(self, model_dir):
        self.model_dir = Path(model_dir)
        self.model_file = self.model_dir / MODEL_FILE_NAME
        self._session = None
        self._lock = threading.Lock()
        self._failure = None

    def state(self):
        base = {"model_dir": str(self.model_dir), "voice": VOICE["name"], "model": VOICE["model"]}
        if not self.model_file.is_file() or self.model_file.stat().st_size != MODEL_BYTES:
            return False, {"ready": False, **base, "reason": "model file not found"}
        if self._failure is None:
            try:
                import cn2an  # noqa: F401
                import numpy  # noqa: F401
                import onnxruntime  # noqa: F401
                import pypinyin  # noqa: F401
                self._failure = ""
            except ImportError as error:
                self._failure = f"缺少依赖：{error.name}"
        if self._failure:
            return False, {"ready": False, **base, "reason": self._failure}
        return True, {"ready": True, **base, "sample_rate": SAMPLE_RATE, "max_chars": MAX_CHARS}

    def _model(self):
        if self._session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            self._session = ort.InferenceSession(str(self.model_file), options,
                                                 providers=["CPUExecutionProvider"])
        return self._session

    def synthesize(self, text, speed=1.0):
        """WAV bytes for one utterance, or ValueError for text that cannot be spoken."""
        import numpy as np

        text = str(text or "").strip()
        if not text:
            raise ValueError("没有要朗读的文字")
        if len(text) > MAX_CHARS:
            raise ValueError(f"单次朗读不超过 {MAX_CHARS} 字")
        ids = text_to_ids(text)
        if not any(lang == ZH or phone != "SP" for phone, lang in zip(ids["phones"], ids["lang_ids"])):
            raise ValueError("没有可朗读的内容")

        def blank(values):  # the model was trained with add_blank: 0 between and around phones
            return np.array([[0] + [v for x in values for v in (x, 0)]], np.int64)

        with self._lock:
            audio = self._model().run(None, {
                "x": blank(ids["phone_ids"]),
                "tone": blank(ids["tone_ids"]),
                "lang": blank(ids["lang_ids"]),
                "x_lengths": np.array([2 * len(ids["phone_ids"]) + 1], np.int64),
                "sid": np.array([VOICE["id"]], np.int64),
                "noise_scale": np.array([0.667], np.float32),
                "length_scale": np.array([1.0 / max(0.7, min(1.4, speed))], np.float32),
            })[0].reshape(-1)
        peak = float(np.abs(audio).max()) or 1.0
        # The model speaks at about a third of full scale; bring it level with other page audio.
        audio = audio * min(3.0, 0.9 / peak)
        audio = np.concatenate([audio, np.zeros(int(SAMPLE_RATE * TAIL_SILENCE), audio.dtype)])
        return wav_bytes(audio)

    def warm(self):
        ready, _ = self.state()
        if ready:
            try:
                self.synthesize("你好")
            except Exception:
                pass
