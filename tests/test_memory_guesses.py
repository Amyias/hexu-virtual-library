"""小和's own guesses about the reader: notes it may add, rewrite or retire, and the overall
impression, both proposed in the one call that writes a conversation summary. No provider is
contacted: the model's reply is a fixed test value."""
import http.client
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import llm_chat
import reader_memory

DAY = 86400
# Obviously invalid test value; never read user configuration/environment or contact a provider.
CONFIG = {"HEXU_LLM_BASE_URL": "https://compatible.example/v1", "HEXU_LLM_MODEL": "test-model",
          "HEXU_LLM_API_KEY": "invalid-test-credential"}
HISTORY = [{"role": "user", "content": "我最近在读明朝那些事儿"}, {"role": "assistant", "content": "好看吗？"}]


def reply(text):
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": text}}]}).encode())


class Clock:
    now = 1_800_000_000

    def __call__(self):
        return self.now


class NoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.memory = reader_memory.ReaderMemory(self.temp.name, clock=self.clock)

    def test_the_model_may_add_rewrite_and_retire_only_its_own_notes(self):
        fact = self.memory.add_fact("我喜欢科幻")
        self.assertEqual(self.memory.apply_notes([{"op": "add", "text": "最近在看历史书"},
                                                  {"op": "add", "text": "晚上读书多"}]), 2)
        first, second = self.memory.active_notes()
        applied = self.memory.apply_notes([
            {"op": "update", "id": first["id"], "text": "最近在看明朝历史"},
            {"op": "retire", "id": second["id"]},
            {"op": "update", "id": fact["id"] + 999, "text": "改不存在的"},  # unknown id
        ])
        self.assertEqual(applied, 2)
        self.assertEqual([note["text"] for note in self.memory.active_notes()], ["最近在看明朝历史"])
        notes = self.memory.snapshot(lambda _: None)["notes"]
        self.assertEqual(len(notes), 2, "a retired note is kept, marked, not deleted")
        self.assertIsNotNone(notes[-1]["retired_at"])
        self.assertEqual(self.memory.snapshot(lambda _: None)["facts"][0]["text"], "我喜欢科幻", "facts untouched")

    def test_malformed_or_excess_proposals_change_nothing_beyond_the_valid_ones(self):
        self.assertEqual(self.memory.apply_notes("add everything"), 0)
        self.assertEqual(self.memory.apply_notes([None, {"op": "delete_all"}, {"op": "add", "text": "嗯"},
                                                  {"op": "add", "text": "x" * 200}]), 0)
        many = [{"op": "add", "text": f"推测第{i}条内容"} for i in range(6)]
        self.assertEqual(self.memory.apply_notes(many), reader_memory.MAX_NOTE_OPS)
        self.assertEqual(self.memory.apply_notes([{"op": "add", "text": "推测第0条内容"}]), 0, "no duplicates")

    def test_too_many_notes_retire_the_one_touched_longest_ago(self):
        for index in range(reader_memory.MAX_NOTES + 2):
            self.clock.now += 60
            self.memory.apply_notes([{"op": "add", "text": f"第{index}条推测内容"}])
        active = self.memory.active_notes()
        self.assertEqual(len(active), reader_memory.MAX_NOTES)
        self.assertNotIn("第0条推测内容", [note["text"] for note in active])

    def test_guessing_off_stops_notes_and_the_models_profile_but_not_the_readers_own(self):
        self.memory.apply_notes([{"op": "add", "text": "最近在看历史书"}])
        self.assertTrue(self.memory.set_profile("喜欢历史和科幻，常在晚上读书"))
        self.assertIn("历史", self.memory.context(lambda _: None))
        self.assertFalse(self.memory.set_inference(False))
        self.assertEqual(self.memory.apply_notes([{"op": "add", "text": "再添一条推测"}]), 0)
        self.assertFalse(self.memory.set_profile("模型想改的印象"))
        self.assertEqual(self.memory.context(lambda _: None), "", "no guess is sent while guessing is off")
        self.assertTrue(self.memory.set_profile("我自己写的介绍", by_reader=True))
        self.assertEqual(self.memory.profile(), "我自己写的介绍")

    def test_the_context_labels_guesses_and_the_reader_can_clear_them(self):
        self.memory.add_fact("我喜欢科幻")
        self.memory.apply_notes([{"op": "add", "text": "最近在看历史书"}])
        self.memory.set_profile("喜欢历史和科幻")
        lines = self.memory.context(lambda _: None, "推荐历史书").split("\n")
        self.assertTrue(lines[0].startswith("读者让你记住的事："), "the reader's own words come first")
        self.assertTrue(any(line.startswith("你对读者的印象（你的推测）") for line in lines))
        self.assertTrue(any(line.startswith("你留意到的（推测，未经读者确认）") for line in lines))
        note = self.memory.active_notes()[0]
        self.assertTrue(self.memory.delete("note", note["id"]))
        self.assertTrue(self.memory.delete("profile", None))
        self.assertEqual(self.memory.profile(), "")
        self.memory.apply_notes([{"op": "add", "text": "又一条推测"}])
        self.memory.clear()
        self.assertEqual((self.memory.active_notes(), self.memory.profile()), ([], ""))

    def test_an_important_conversation_outranks_a_newer_trivial_one(self):
        self.memory.add_summary("读者说下个月要考研，想找英语阅读材料", 3, importance=9)
        self.clock.now += DAY
        self.memory.add_summary("闲聊了今天的天气和晚饭吃什么", 2, importance=1)
        lines = self.memory.context(lambda _: None).split("\n")
        self.assertIn("考研", lines[0])


class ConsolidationTests(unittest.TestCase):
    RECORD = {"facts": ["我喜欢科幻"], "notes": [{"id": 4, "text": "晚上读书多"}], "profile": ""}

    def ask(self, text, record=RECORD):
        with patch("llm_chat.open_completion", return_value=reply(text)) as call:
            status, result = llm_chat.summarize(HISTORY, CONFIG, lambda _url: None, record=record)
        return status, result, call

    def test_one_call_returns_the_summary_and_the_proposed_changes(self):
        answer = json.dumps({"summary": "读者在读《明朝那些事儿》", "importance": 7,
                             "notes": [{"op": "add", "text": "最近在看历史书"}, {"op": "retire", "id": 4}],
                             "profile": "爱读历史和科幻"}, ensure_ascii=False)
        status, result, call = self.ask("```json\n" + answer + "\n```")
        self.assertEqual(status, 200)
        self.assertEqual(call.call_count, 1, "no extra call for the guesses")
        self.assertEqual((result["summary"], result["importance"], len(result["notes"]), result["profile"]),
                         ("读者在读《明朝那些事儿》", 7, 2, "爱读历史和科幻"))
        sent = json.loads(call.call_args[0][0].data)["messages"]
        self.assertIn("只读", sent[1]["content"], "the reader's facts are offered read-only")
        self.assertIn("4: 晚上读书多", sent[1]["content"])

    def test_a_malformed_answer_keeps_at_most_the_summary(self):
        status, result, _ = self.ask('{"summary": "读者在读历史", "notes": [')
        self.assertEqual((status, result["summary"]), (200, ""), "broken JSON is not guessed at")
        self.assertNotIn("notes", result)
        status, result, _ = self.ask("读者在读《明朝那些事儿》，想多读历史")
        self.assertEqual(result["summary"], "读者在读《明朝那些事儿》，想多读历史")
        self.assertNotIn("notes", result)
        parsed = llm_chat.parse_consolidation('{"summary": "x", "importance": 99, "notes": "all", "profile": 3}')
        self.assertEqual((parsed["importance"], parsed["notes"], parsed["profile"]), (None, [], None))

    def test_without_guessing_the_plain_one_line_prompt_is_used(self):
        status, result, call = self.ask("读者在读《三体》", record=None)
        self.assertEqual(result, {"summary": "读者在读《三体》"})
        self.assertIn("只回答一个字：无", json.loads(call.call_args[0][0].data)["messages"][0]["content"])


spec = importlib.util.spec_from_file_location("guess_server", ROOT / "tools/asr-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.memory = reader_memory.ReaderMemory(self.temp.name)
        for target, module, value in [("instance", reader_memory, lambda: self.memory),
                                      ("describe_book", server, lambda _: None)]:
            patcher = patch.object(module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.restart_args = ()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.port = httpd.server_address[1]

    def call(self, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("POST", path, json.dumps(body).encode(), {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            connection.close()

    def test_a_summary_applies_the_proposals_within_the_rules(self):
        proposal = {"summary": "读者在读《明朝那些事儿》", "importance": 7,
                    "notes": [{"op": "add", "text": "最近在看历史书"}], "profile": "爱读历史"}
        with patch.object(server, "settings_state", lambda: (CONFIG, {})), \
                patch.object(llm_chat, "summarize", lambda *args, **kwargs: (200, proposal)):
            status, answer = self.call("/memory/summarize", {"history": HISTORY})
        self.assertEqual((status, answer), (200, {"summary": "读者在读《明朝那些事儿》", "notes": 1, "profile": True}))
        self.assertEqual(self.memory.profile(), "爱读历史")
        self.assertEqual(self.call("/memory/inference", {"enabled": False})[1]["inference"], False)
        with patch.object(server, "settings_state", lambda: (CONFIG, {})), \
                patch.object(llm_chat, "summarize", lambda *args, **kwargs: (200, proposal)):
            self.assertEqual(self.call("/memory/summarize", {"history": HISTORY})[1]["notes"], 0)

    def test_the_reader_edits_or_clears_the_impression(self):
        self.assertEqual(self.call("/memory/profile", {"text": "我爱读诗"})[1], {"ok": True, "profile": "我爱读诗"})
        self.assertEqual(self.call("/memory/profile", {"text": ""})[1], {"ok": True, "profile": ""})
        self.assertEqual(self.call("/memory/profile", {"text": "x" * 500})[0], 400)


if __name__ == "__main__":
    unittest.main()
