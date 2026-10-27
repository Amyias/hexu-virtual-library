"""Replay the memory and spoiler scenes of tests/dialogue-eval.json (the routing and choice scenes
run in tests/dialogue-eval.test.mjs). Offline: no model is called."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import reader_memory

SCENES = json.loads((ROOT / "tests" / "dialogue-eval.json").read_text(encoding="utf-8"))
DAY = 86400
NOW = 1_800_000_000

spec = importlib.util.spec_from_file_location("dialogue_eval_server", ROOT / "tools/asr-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class Clock:
    now = NOW

    def __call__(self):
        return self.now


class DialogueEvalTests(unittest.TestCase):
    def test_memory_scenes_recall_what_bears_on_the_question(self):
        for scene in SCENES["memory"]:
            with self.subTest(scene["about"]), tempfile.TemporaryDirectory() as directory:
                clock = Clock()
                memory = reader_memory.ReaderMemory(directory, clock=clock)
                # Oldest first, each entry stamped its own number of days ago.
                for text, days in sorted(scene.get("facts", []), key=lambda item: -item[1]):
                    clock.now = NOW - days * DAY
                    memory.add_fact(text)
                for text, days in sorted(scene.get("summaries", []), key=lambda item: -item[1]):
                    clock.now = NOW - days * DAY
                    memory.add_summary(text, 2)
                clock.now = NOW
                context = memory.context(lambda _: None, scene["question"])
                if "first" in scene:
                    self.assertTrue(context.startswith("读者让你记住的事：" + scene["first"]), context)
                if "summary" in scene:
                    self.assertIn(scene["summary"], context)

    def test_spoiler_scenes(self):
        for scene in SCENES["spoilers"]:
            with self.subTest(scene["text"]):
                self.assertEqual(server.wants_spoilers(scene["text"]), scene["wants"])


if __name__ == "__main__":
    unittest.main()
