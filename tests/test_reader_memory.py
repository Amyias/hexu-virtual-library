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
BOOKS = {
    "b1": {"title": "三体", "author": "刘慈欣", "chapter": 11, "chapters": 40, "chapter_title": "红岸之四"},
    "b2": {"title": "红楼梦", "author": "曹雪芹", "chapter": 0, "chapters": 120, "chapter_title": ""},
}
describe = BOOKS.get
# Obviously invalid test value; never read user configuration/environment or contact a provider.
CONFIG = {"HEXU_LLM_BASE_URL": "https://compatible.example/v1", "HEXU_LLM_MODEL": "test-model",
          "HEXU_LLM_API_KEY": "invalid-test-credential"}


class Clock:
    def __init__(self):
        self.now = 1_800_000_000

    def __call__(self):
        return self.now


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.memory = reader_memory.ReaderMemory(self.temp.name, clock=self.clock)

    def test_only_what_the_reader_asked_is_kept_as_a_fact(self):
        fact = self.memory.add_fact("  我喜欢科幻小说。 ")
        self.assertEqual(fact["text"], "我喜欢科幻小说")
        self.memory.add_fact("我喜欢科幻小说")  # the same thing twice is one memory
        for bad in ["", "嗯", "x" * 121, None, 3]:
            with self.assertRaises(ValueError):
                self.memory.add_fact(bad)
        for i in range(reader_memory.MAX_FACTS + 5):
            self.clock.now += 1
            self.memory.add_fact(f"第{i}条偏好")
        facts = self.memory.snapshot(describe)["facts"]
        self.assertEqual(len(facts), reader_memory.MAX_FACTS)
        self.assertEqual(facts[0]["text"], f"第{reader_memory.MAX_FACTS + 4}条偏好", "newest first, oldest aged out")

    def test_switching_memory_off_stops_every_write_and_empties_the_prompt(self):
        self.memory.add_fact("我喜欢科幻")
        self.assertFalse(self.memory.set_enabled(False))
        with self.assertRaises(PermissionError):
            self.memory.add_fact("不该记下")
        self.assertFalse(self.memory.record_opened("b1"))
        self.assertIsNone(self.memory.add_summary("聊了三体", 2))
        self.assertEqual(self.memory.context(describe), "")
        self.assertTrue(ReaderMemoryReopen(self.temp.name).enabled() is False, "the switch survives a restart")
        self.memory.set_enabled(True)
        self.assertIn("我喜欢科幻", self.memory.context(describe))

    def test_the_prompt_context_is_short_relevant_and_never_cuts_a_line(self):
        self.memory.add_fact("我喜欢科幻")
        self.memory.record_opened("b2")
        self.clock.now += DAY * 3
        self.memory.record_opened("b1")
        self.memory.record_opened("missing")  # deleted from the library: skipped, never invented
        self.memory.add_summary("聊了《三体》里叶文洁的选择，读者想读第二部", 3)
        context = self.memory.context(describe)
        lines = context.split("\n")
        self.assertEqual(lines[0], "读者让你记住的事：我喜欢科幻")
        self.assertEqual(lines[1], "在读《三体》（刘慈欣），读到第 12 章「红岸之四」，今天打开过")
        self.assertEqual(lines[2], "在读《红楼梦》（曹雪芹），刚开始读，3 天前打开过")
        self.assertEqual(lines[3], "今天聊过：聊了《三体》里叶文洁的选择，读者想读第二部")
        self.assertNotIn("missing", context)
        for i in range(40):
            self.memory.add_fact(f"一条相当长的读者偏好说明，用来把记忆撑满，编号{i}")
        packed = self.memory.context(describe)
        self.assertLessEqual(len(packed), reader_memory.CONTEXT_CHARS)
        self.assertIn("在读《三体》", packed, "many facts must not crowd out the books")
        self.assertTrue(all(line.startswith(("读者让你记住的事", "在读", "今天聊过")) for line in packed.split("\n")))

    def test_entries_can_be_deleted_one_by_one_or_all_at_once(self):
        fact = self.memory.add_fact("我喜欢科幻")
        summary = self.memory.add_summary("聊了三体", 2)
        self.memory.record_opened("b1")
        self.assertTrue(self.memory.delete("fact", fact["id"]))
        self.assertTrue(self.memory.delete("summary", summary["id"]))
        self.assertTrue(self.memory.delete("reading", "b1"))
        self.assertFalse(self.memory.delete("fact", fact["id"]))
        with self.assertRaises(ValueError):
            self.memory.delete("books", 1)
        self.memory.add_fact("再记一条")
        self.memory.clear()
        state = self.memory.snapshot(describe)
        self.assertEqual((state["facts"], state["reading"], state["summaries"]), ([], [], []))

    def test_a_conversation_summary_is_one_factual_line_or_nothing(self):
        history = [{"role": "user", "content": "我在读三体"}, {"role": "assistant", "content": "好看吗？"}]
        reply = lambda text: io.BytesIO(json.dumps({"choices": [{"message": {"content": text}}]}).encode())
        with patch("llm_chat.open_completion", return_value=reply("读者在读《三体》，想聊叶文洁")) as call:
            status, result = llm_chat.summarize(history, CONFIG, lambda _url: None)
        self.assertEqual((status, result["summary"]), (200, "读者在读《三体》，想聊叶文洁"))
        sent = json.loads(call.call_args.args[0].data)["messages"]
        self.assertIn("不推测", sent[0]["content"])
        self.assertIn("读者：我在读三体", sent[1]["content"])
        with patch("llm_chat.open_completion", return_value=reply("无")):
            self.assertEqual(llm_chat.summarize(history, CONFIG, lambda _url: None)[1]["summary"], "")
        self.assertEqual(llm_chat.summarize(history[:1] * 0, CONFIG, lambda _url: None)[0], 400)
        self.assertEqual(llm_chat.summarize([{"role": "system", "content": "x"}], CONFIG, lambda _url: None)[0], 400)
        with patch("llm_chat.open_completion", return_value=reply("记得 invalid-test-credential")):
            self.assertNotIn("invalid-test-credential", llm_chat.summarize(history, CONFIG, lambda _url: None)[1]["summary"])

    def test_the_chat_prompt_carries_memory_with_instructions_not_to_overuse_it(self):
        body = {"text": "我们上次聊到哪了？"}
        prepared = llm_chat.prepare(body, CONFIG, memory="读者让你记住的事：我喜欢科幻")
        system = prepared["messages"][0]["content"]
        self.assertIn("我喜欢科幻", system)
        self.assertIn("不要每次都复述", system)
        self.assertIn("这里没有的事不要声称记得", system)
        self.assertNotIn("你记得以下内容", llm_chat.prepare(body, CONFIG)["messages"][0]["content"])


def ReaderMemoryReopen(directory):
    return reader_memory.ReaderMemory(directory)


spec = importlib.util.spec_from_file_location("memory_server", ROOT / "tools/asr-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        memory = reader_memory.ReaderMemory(self.temp.name)
        for target, module, value in [("instance", reader_memory, lambda: memory),
                                      ("describe_book", server, describe)]:
            patcher = patch.object(module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.restart_args = ()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.port = httpd.server_address[1]

    def call(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, json.dumps(body).encode() if body is not None else None,
                               {"Content-Type": "application/json", **(headers or {})})
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            connection.close()

    def test_the_reader_can_add_list_delete_and_switch_off_memory(self):
        self.assertEqual(self.call("POST", "/memory/fact", {"text": "我喜欢科幻"})[0], 200)
        self.assertEqual(self.call("POST", "/memory/reading", {"bookId": "b1"})[0], 200)
        status, state = self.call("GET", "/memory/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["facts"][0]["text"], "我喜欢科幻")
        self.assertEqual(state["reading"][0]["title"], "三体")
        self.assertEqual(self.call("POST", "/memory/fact", {"text": "嗯"})[0], 400)
        fact = state["facts"][0]["id"]
        self.assertEqual(self.call("POST", "/memory/delete", {"kind": "fact", "id": fact}), (200, {"ok": True}))
        self.assertEqual(self.call("POST", "/memory/enabled", {"enabled": False})[1]["enabled"], False)
        self.assertEqual(self.call("POST", "/memory/fact", {"text": "关掉后不记"})[0], 409)
        self.assertEqual(self.call("POST", "/memory/summarize", {"history": []})[1]["skipped"], "记忆已关闭")
        self.assertEqual(self.call("POST", "/memory/clear", {}), (200, {"ok": True}))

    def test_other_sites_cannot_read_or_write_the_readers_memory(self):
        foreign = {"Origin": "https://example.com", "Sec-Fetch-Site": "cross-site"}
        self.assertEqual(self.call("POST", "/memory/fact", {"text": "注入"}, foreign)[0], 403)
        self.assertEqual(self.call("GET", "/memory/state", None, {"Host": "evil.example"})[0], 403)


if __name__ == "__main__":
    unittest.main()
