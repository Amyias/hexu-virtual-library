import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import app_actions
import llm_chat

# Obviously invalid test value; never read user configuration/environment or contact a provider.
CONFIG = {"HEXU_LLM_BASE_URL": "https://compatible.example/v1", "HEXU_LLM_MODEL": "test-model",
          "HEXU_LLM_API_KEY": "invalid-test-credential"}
CATALOG = {"HX-03408": {"id": "local-1", "title": "三体", "author": "刘慈欣"}}
READING = {"title": "三体", "chapter": 3, "chapters": 40}


def names(actions):
    return [tool["function"]["name"] for tool in actions.tools]


def sse_call(name, arguments):
    lines = ["data: " + json.dumps({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}]}}]},
        ensure_ascii=False), "data: [DONE]"]
    return io.BytesIO(("\n\n".join(lines) + "\n\n").encode("utf-8"))


def sse_text(text):
    lines = ["data: " + json.dumps({"choices": [{"delta": {"content": text}}]}, ensure_ascii=False), "data: [DONE]"]
    return io.BytesIO(("\n\n".join(lines) + "\n\n").encode("utf-8"))


class AppActionTests(unittest.TestCase):
    def test_only_actions_that_make_sense_now_are_offered(self):
        self.assertEqual(names(app_actions.AppActions("IDLE", None, CATALOG)), ["set_sky", "fetch_book", "locate_book"])
        self.assertEqual(names(app_actions.AppActions("IDLE", None, {})), ["set_sky"], "no books, nothing to fetch")
        self.assertEqual(names(app_actions.AppActions("READING", READING, CATALOG)),
                         ["set_sky", "reading_music", "open_chapter", "set_font_size"])
        self.assertEqual(names(app_actions.AppActions("NAVIGATING", None, CATALOG)), ["set_sky"])
        prompt = app_actions.AppActions("IDLE", None, CATALOG).prompt()
        self.assertIn("HX-03408 | 三体 | 刘慈欣", prompt)
        self.assertIn("只在读者明确提出要求时调用", prompt)
        self.assertNotIn("HX-03408", app_actions.AppActions("READING", READING, CATALOG).prompt())

    def test_every_argument_is_checked_before_the_page_is_told(self):
        reading = app_actions.AppActions("READING", READING, CATALOG)
        self.assertEqual(reading.execute("open_chapter", '{"chapter": 5}')[0],
                         {"type": "action", "name": "open_chapter", "args": {"chapter": 5}})
        for bad in ['{"chapter": 0}', '{"chapter": 41}', '{"chapter": "5"}', '{"chapter": true}', "not json", "[]"]:
            action, result = reading.execute("open_chapter", bad)
            self.assertIsNone(action, bad)
            self.assertIn("error", result)
        self.assertEqual(reading.execute("reading_music", '{"action": "pause"}')[0]["args"], {"action": "pause"})
        self.assertIsNone(reading.execute("fetch_book", '{"bookId": "HX-03408"}')[0], "not while reading")
        idle = app_actions.AppActions("IDLE", None, CATALOG)
        self.assertEqual(idle.execute("fetch_book", '{"bookId": "HX-03408"}')[0]["args"],
                         {"bookId": "HX-03408", "title": "三体"})
        self.assertIsNone(idle.execute("fetch_book", '{"bookId": "HX-00001"}')[0], "an empty slot is not a book")
        self.assertIsNone(idle.execute("set_sky", '{"mode": "dusk"}')[0])
        self.assertIsNone(idle.execute("delete_everything", "{}")[0])

    def test_at_most_three_actions_a_turn(self):
        actions = app_actions.AppActions("IDLE", None, CATALOG)
        done = [actions.execute("set_sky", '{"mode": "night"}')[0] for _ in range(5)]
        self.assertEqual(sum(1 for action in done if action), app_actions.MAX_ACTIONS)

    def test_a_requested_action_streams_to_the_page_and_the_model_says_what_it_did(self):
        actions = app_actions.AppActions("IDLE", None, CATALOG)
        responses = [sse_call("set_sky", '{"mode": "night"}'), sse_text("好，已经帮你换成夜晚啦。")]
        with patch("llm_chat.open_completion", side_effect=responses) as call:
            events = list(llm_chat.chat_stream({"text": "把天变成晚上"}, {**CONFIG, "HEXU_WEB_ENABLED": "0"},
                                               lambda _url: None, app=actions))
        first = json.loads(call.call_args_list[0].args[0].data)
        self.assertEqual([tool["function"]["name"] for tool in first["tools"]], ["set_sky", "fetch_book", "locate_book"])
        self.assertIn("界面工具", first["messages"][0]["content"])
        self.assertEqual(events[0], {"type": "action", "name": "set_sky", "args": {"mode": "night"}})
        second = json.loads(call.call_args_list[1].args[0].data)["messages"]
        self.assertEqual(json.loads(second[-1]["content"]), {"ok": True, "done": "界面会立即执行"})
        self.assertEqual(events[-1]["reply"], "好，已经帮你换成夜晚啦。")
        self.assertEqual(events[-1]["actions"], [events[0]])


if __name__ == "__main__":
    unittest.main()
