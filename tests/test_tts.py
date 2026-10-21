import http.client
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import tts

spec = importlib.util.spec_from_file_location("tts_server", ROOT / "tools/asr-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
MODEL = server.tts_model_dir() / tts.MODEL_FILE_NAME
HAS_MODEL = MODEL.is_file()
try:
    import onnxruntime  # noqa: F401
    import cn2an  # noqa: F401
    HAS_RUNTIME = True
except ImportError:
    HAS_RUNTIME = False


class FrontendTests(unittest.TestCase):
    def test_symbol_table_matches_the_trained_embedding(self):
        # 4 specials + 37 zhuyin + 39 arpabet + 7 punctuation, then the appended syllabic vowel.
        self.assertEqual(len(tts.SYMBOLS), 88)
        self.assertEqual(tts.SYM2ID["ㄅ"], 4)
        self.assertEqual(tts.SYM2ID["AA"], 41)
        self.assertEqual(tts.SYM2ID[","], 80)
        self.assertEqual(tts.SYM2ID["ㄭ"], 87)

    @unittest.skipUnless(HAS_RUNTIME, "install cn2an to test the text frontend")
    def test_catalogue_codes_are_read_in_chinese(self):
        self.assertEqual(tts.speak_library_codes("位置 S2-A-L4-P284"), "位置 第二架A面第四层第二百八十四本")
        self.assertEqual(tts.speak_library_codes("编号 HX-03408"), "编号 H X 零三四零八")

    @unittest.skipUnless(HAS_RUNTIME, "install cn2an to test the text frontend")
    def test_phones_tones_and_languages(self):
        ids = tts.text_to_ids("是A面。")
        self.assertEqual(ids["phones"], ["ㄕ", "ㄭ", "EY", "SP", "ㄇ", "ㄧ", "ㄢ", "."])
        self.assertEqual(ids["tone_ids"], [4, 4, 1, 0, 4, 4, 4, 0])
        self.assertEqual(ids["lang_ids"], [0, 0, 1, 1, 0, 0, 0, 0])
        neutral = tts.text_to_ids("我的")  # 的 is neutral tone
        self.assertEqual(neutral["tone_ids"][-2:], [5, 5])

    def test_a_missing_model_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as temp:
            ready, payload = tts.Speaker(temp).state()
        self.assertFalse(ready)
        self.assertEqual(payload["reason"], "model file not found")
        self.assertEqual(payload["voice"], "欣然")

    @unittest.skipUnless(HAS_MODEL and HAS_RUNTIME, "PrimeTTS model not downloaded")
    def test_xinran_speaks_a_reply_as_16k_wav(self):
        speaker = tts.Speaker(MODEL.parent)
        self.assertTrue(speaker.state()[0])
        data = speaker.synthesize("你好，我是小和。")
        with wave.open(io.BytesIO(data)) as clip:
            self.assertEqual((clip.getframerate(), clip.getnchannels(), clip.getsampwidth()), (16000, 1, 2))
            self.assertGreater(clip.getnframes() / clip.getframerate(), 1.0)
        for bad in ["", "   ", "字" * (tts.MAX_CHARS + 1)]:
            with self.assertRaises(ValueError):
                speaker.synthesize(bad)


class FakeSpeaker:
    def __init__(self, ready):
        self.ready = ready
        self.spoken = []

    def state(self):
        return self.ready, {"ready": self.ready, "voice": "欣然"}

    def synthesize(self, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("没有要朗读的文字")
        self.spoken.append(text)
        return b"RIFF-fake-wav"


class RouteTests(unittest.TestCase):
    def serve(self, speaker):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.restart_args = ()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        patcher = patch.object(server, "SPEAKER", speaker)
        patcher.start()
        self.addCleanup(patcher.stop)
        return httpd.server_address[1]

    def request(self, port, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        payload = json.dumps(body).encode() if body is not None else None
        connection.request(method, path, payload, {"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        try:
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    def test_without_the_model_the_page_is_told_to_fall_back(self):
        port = self.serve(FakeSpeaker(False))
        self.assertEqual(self.request(port, "GET", "/tts/ready")[0], 503)
        self.assertEqual(self.request(port, "POST", "/tts", {"text": "你好"})[0], 503)

    def test_speech_is_wav_and_bad_or_foreign_requests_are_refused(self):
        speaker = FakeSpeaker(True)
        port = self.serve(speaker)
        status, kind, body = self.request(port, "GET", "/tts/ready")
        self.assertEqual((status, json.loads(body)["voice"]), (200, "欣然"))
        status, kind, body = self.request(port, "POST", "/tts", {"text": "你好"})
        self.assertEqual((status, kind, body), (200, "audio/wav", b"RIFF-fake-wav"))
        self.assertEqual(self.request(port, "POST", "/tts", {"text": ""})[0], 400)
        self.assertEqual(self.request(port, "POST", "/tts", ["not", "an", "object"])[0], 400)
        foreign = {"Origin": "https://example.com", "Sec-Fetch-Site": "cross-site"}
        self.assertEqual(self.request(port, "POST", "/tts", {"text": "你好"}, foreign)[0], 403)
        self.assertEqual(speaker.spoken, ["你好"])


if __name__ == "__main__":
    unittest.main()
