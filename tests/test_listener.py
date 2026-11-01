"""Continuous listening (tools/listener.py and POST /asr/stream).

The detector tests need the small listening models in .cache/models/listen (package-local fetches
them) and speak through the local PrimeTTS voice; without either they are skipped. No network."""
import http.client
import importlib.util
import io
import json
import sys
import threading
import unittest
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import listener

spec = importlib.util.spec_from_file_location("listen_server", ROOT / "tools/asr-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

MODELS = listener.model_dir()
HAVE_MODELS = all((MODELS / name).is_file() for name in listener.FILES.values())
HAVE_VOICE = server.SPEAKER.state()[0]
CHUNK = 4000  # a quarter of a second, as the page sends


def spoken(*parts, gap=1.2):
    """16 kHz float samples of the parts said by the local voice, with quiet around them."""
    import numpy as np

    pieces = [np.zeros(int(0.8 * listener.RATE), np.float32)]
    for index, part in enumerate(parts):
        if index:
            pieces.append(np.zeros(int(gap * listener.RATE), np.float32))
        with wave.open(io.BytesIO(server.SPEAKER.synthesize(part)), "rb") as clip:
            pieces.append(np.frombuffer(clip.readframes(clip.getnframes()), "<i2").astype(np.float32) / 32768)
    pieces.append(np.zeros(int(1.0 * listener.RATE), np.float32))
    return np.concatenate(pieces)


def listen(session, audio):
    """Feed audio chunk by chunk; every event with the chunk index it arrived on."""
    heard = []
    for index in range(0, len(audio), CHUNK):
        events, _ = session.feed(audio[index:index + CHUNK], lambda samples: f"{len(samples)} samples")
        heard += [(index // CHUNK, event) for event in events]
    return heard


class NameBySoundTests(unittest.TestCase):
    def test_the_request_is_what_follows_the_name_however_it_was_written(self):
        cases = {
            "小和，帮我找三体": "帮我找三体",
            "笑河读正文。": "读正文。",
            "萧何下一页。": "下一页。",
            "教和读正文。": "读正文。",
            "嘿，小和，三体讲了什么": "三体讲了什么",
            "和下一页。": "下一页。",  # only the end of the name survived
            "可以。": "",  # the name alone, misheard
            "小河。": "",
            "帮我找三体，谢谢你": "帮我找三体，谢谢你",  # no name to strip: the text stands
        }
        for heard, request in cases.items():
            self.assertEqual(listener.request_after_name(heard), request, heard)


class KeywordFileTests(unittest.TestCase):
    def test_every_wake_word_is_spelt_in_units_the_model_knows(self):
        words = listener.keywords()
        self.assertIn("x iǎo h é @小和", words)
        if not HAVE_MODELS:
            self.skipTest("连续收听模型不在 .cache/models/listen")
        known = {line.split()[0] for line in (MODELS / "kws-tokens.txt").read_text(encoding="utf-8").splitlines()}
        for word in words:
            units = word.split("@")[0].split()
            self.assertTrue(units and all(unit in known for unit in units), word)


@unittest.skipUnless(HAVE_MODELS and HAVE_VOICE, "需要连续收听模型与本机语音模型")
class SessionTests(unittest.TestCase):
    def setUp(self):
        self.listener = listener.Listener(MODELS)
        self.assertEqual(self.listener.state(), (True, ""))

    def test_the_name_is_heard_before_the_sentence_ends(self):
        heard = listen(self.listener.session("test-wake-1"), spoken("小和，帮我找三体"))
        kinds = [event["type"] for _, event in heard]
        self.assertEqual(kinds, ["wake", "text"], heard)
        (woke_at, _), (text_at, text) = heard
        self.assertLess(woke_at, text_at, "the wake word arrives before the transcript")
        self.assertTrue(text["woke"], "the page already answered this utterance's wake word")
        self.assertLess(text["start"], text["end"])

    def test_other_speech_does_not_wake(self):
        for sentence in ["今天晚上吃什么", "这本书挺好看的"]:
            heard = listen(self.listener.session("test-quiet-1"), spoken(sentence))
            self.assertEqual([event["type"] for _, event in heard], ["text"], sentence)
            self.assertFalse(heard[0][1]["woke"])

    def test_a_pause_separates_the_name_from_the_request(self):
        heard = listen(self.listener.session("test-step-1"), spoken("小和", "帮我找三体"))
        texts = [event for _, event in heard if event["type"] == "text"]
        self.assertEqual(len(texts), 2, heard)
        self.assertTrue(texts[0]["woke"])
        self.assertFalse(texts[1]["woke"], "the request after the pause is not answered twice")

    def test_quiet_and_a_click_are_not_speech(self):
        import numpy as np

        audio = np.zeros(listener.RATE * 2, np.float32)
        audio[16000:16800] = 0.3  # 50 ms of a click
        self.assertEqual(listen(self.listener.session("test-click-1"), audio), [])

    def test_sessions_are_named_capped_and_forgotten(self):
        for bad in ["", "short", "has space here", "x" * 65, None]:
            with self.assertRaises(ValueError):
                self.listener.session(bad)
        first = self.listener.session("session-a")
        self.assertIs(self.listener.session("session-a"), first)
        for index in range(listener.MAX_SESSIONS):
            self.listener.session(f"session-{index:02d}")
        self.assertLessEqual(len(self.listener.sessions), listener.MAX_SESSIONS)
        self.assertNotIn("session-a", self.listener.sessions, "the least recently used goes first")
        self.listener.close("session-00")
        self.assertNotIn("session-00", self.listener.sessions)

    def test_pcm_chunks_are_checked(self):
        self.assertEqual(len(listener.samples_from_pcm(b"\x00\x01" * 10)), 10)
        for bad in [b"", b"\x00", b"\x00" * int(listener.MAX_CHUNK_SECONDS * listener.RATE * 2 + 2)]:
            with self.assertRaises(ValueError):
                listener.samples_from_pcm(bad)


class StreamRouteTests(unittest.TestCase):
    def setUp(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.restart_args = ()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.port = httpd.server_address[1]

    def call(self, method, path, body=b"", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request(method, path, body, {"Content-Type": "application/octet-stream", **(headers or {})})
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            connection.close()

    def test_other_sites_cannot_stream_audio(self):
        foreign = {"Origin": "https://example.com", "Sec-Fetch-Site": "cross-site"}
        self.assertEqual(self.call("POST", "/asr/stream?session=abcdefgh", b"\x00\x00" * 100, foreign)[0], 403)

    @unittest.skipUnless(HAVE_MODELS and server.model_state()[0], "需要识别模型与连续收听模型")
    def test_ready_reports_streaming_and_chunks_are_answered(self):
        status, ready = self.call("GET", "/asr/ready")
        self.assertEqual((status, ready["streaming"]), (200, True))
        self.assertEqual(self.call("POST", "/asr/stream?session=bad%20id", b"\x00\x00" * 100)[0], 400)
        self.assertEqual(self.call("POST", "/asr/stream?session=route-test-1", b"")[0], 400)
        status, answer = self.call("POST", "/asr/stream?session=route-test-1", b"\x00\x00" * 4000)
        self.assertEqual((status, answer), (200, {"events": [], "speaking": False}))
        self.assertEqual(self.call("POST", "/asr/stream?session=route-test-1&end=1")[0], 200)


if __name__ == "__main__":
    unittest.main()
