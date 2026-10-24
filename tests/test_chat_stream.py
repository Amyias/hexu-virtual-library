import http.client
import importlib.util
import io
import json
import sys
import threading
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import llm_chat

# Obviously invalid test value; never read user configuration/environment or contact a provider.
CONFIG = {"HEXU_LLM_BASE_URL": "https://api.deepseek.com", "HEXU_LLM_MODEL": "test-model",
          "HEXU_LLM_API_KEY": "invalid-test-credential"}
OFFLINE = {**CONFIG, "HEXU_WEB_ENABLED": "0"}


def sse(*chunks, finish="stop"):
    """A provider's streamed reply: one Server-Sent Event per content piece, then [DONE]."""
    lines = [": keep-alive"]
    for text in chunks:
        lines.append("data: " + json.dumps({"choices": [{"delta": {"content": text}}]}, ensure_ascii=False))
    lines.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}))
    lines.append("data: [DONE]")
    return io.BytesIO(("\n\n".join(lines) + "\n\n").encode("utf-8"))


def sse_tool_call(name="web_search", arguments='{"query": "今日新闻"}'):
    half = len(arguments) // 2
    parts = [
        {"index": 0, "id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments[:half]}},
        {"index": 0, "function": {"arguments": arguments[half:]}},
    ]
    lines = ["data: " + json.dumps({"choices": [{"delta": {"tool_calls": [part]}}]}, ensure_ascii=False) for part in parts]
    lines.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}))
    lines.append("data: [DONE]")
    return io.BytesIO(("\n\n".join(lines) + "\n\n").encode("utf-8"))


def run(body, config=OFFLINE, **kwargs):
    return list(llm_chat.chat_stream(body, config, lambda _url: None, **kwargs))


class StreamTests(unittest.TestCase):
    def test_pieces_arrive_in_order_and_the_last_event_carries_the_reply(self):
        with patch("llm_chat.open_completion", return_value=sse("你好呀，", "我是小和。", "想聊点什么？")) as call:
            events = run({"text": "你好"})
        payload = json.loads(call.call_args.args[0].data)
        self.assertTrue(payload["stream"])
        self.assertIn("小和", payload["messages"][0]["content"])
        self.assertIn("不要用 Markdown", payload["messages"][0]["content"])
        deltas = [e["text"] for e in events if e["type"] == "delta"]
        self.assertEqual("".join(deltas), "你好呀，我是小和。想聊点什么？")
        self.assertGreater(len(deltas), 1, "the reply must not arrive as a single block")
        done = events[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["reply"], "你好呀，我是小和。想聊点什么？")
        self.assertEqual(done["model"], "test-model")
        self.assertFalse(done["truncated"])

    def test_a_key_split_across_two_pieces_never_leaves_the_server(self):
        key = CONFIG["HEXU_LLM_API_KEY"]
        with patch("llm_chat.open_completion", return_value=sse("前文 " + key[:7], key[7:] + " 后文")):
            events = run({"text": "x"})
        streamed = "".join(e["text"] for e in events if e["type"] == "delta")
        self.assertNotIn(key[:7], streamed)
        self.assertNotIn(key, json.dumps(events, ensure_ascii=False))
        self.assertEqual(streamed, events[-1]["reply"])
        self.assertIn("[已隐去]", streamed)
        # Ordinary text is never held back; only a tail that could start a key is.
        self.assertEqual(llm_chat.unsafe_tail("你好 inval", [key]), 5)
        self.assertEqual(llm_chat.unsafe_tail("你好呀。", [key]), 0)

    def test_a_streamed_tool_call_runs_then_the_answer_streams(self):
        responses = [sse_tool_call(), sse("据查询，", "今天天气晴[1]。")]
        outcome = {"results": [{"source_id": 1, "title": "天气", "url": "https://example.com/a"}]}
        with patch("llm_chat.open_completion", side_effect=responses) as call, \
                patch("web_tools.WebTools.execute", return_value=outcome) as execute:
            events = run({"text": "今天天气"}, config=CONFIG)
        execute.assert_called_once_with("web_search", '{"query": "今日新闻"}')
        second = json.loads(call.call_args_list[1].args[0].data)["messages"]
        self.assertEqual(second[-2]["tool_calls"][0]["function"]["name"], "web_search")
        self.assertEqual(second[-1]["role"], "tool")
        self.assertEqual(events[-1]["reply"], "据查询，今天天气晴[1]。")

    def test_failures_end_with_one_error_and_no_upstream_detail(self):
        error = urllib.error.HTTPError("https://x", 401, "secret upstream body", {}, None)
        with patch("llm_chat.open_completion", side_effect=error):
            events = run({"text": "x"})
        self.assertEqual([e["type"] for e in events], ["error"])
        self.assertIn("401", events[0]["error"])
        self.assertNotIn("secret", events[0]["error"])
        with patch("llm_chat.open_completion", return_value=io.BytesIO(b"data: {not json}\n\n")):
            self.assertEqual(run({"text": "x"})[-1]["error"], llm_chat.STREAM_INCOMPATIBLE)
        with patch("llm_chat.open_completion", return_value=sse()):
            self.assertIn("空回答", run({"text": "x"})[-1]["error"])
        invalid = run({"text": ""})
        self.assertEqual((invalid[0]["type"], invalid[0]["status"]), ("error", 400))
        missing = run({"text": "x"}, config={**OFFLINE, "HEXU_LLM_API_KEY": ""})
        self.assertEqual(missing[0]["status"], 503)


spec = importlib.util.spec_from_file_location("stream_server", ROOT / "tools/asr-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class RouteTests(unittest.TestCase):
    def serve(self, events):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.restart_args = ()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        for target, value in [("chat_stream", lambda *a, **k: (event for event in events)),
                              ("load_catalog", lambda: ({}, [])),
                              ("memory_context", lambda: ""),
                              ("book_passages", lambda *_: ""),
                              ("settings_state", lambda: (OFFLINE, {}))]:
            module = llm_chat if target == "chat_stream" else server
            patcher = patch.object(module, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return httpd.server_address[1]

    def post(self, port, body, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("POST", "/chat/stream", json.dumps(body).encode(),
                               {"Content-Type": "application/json", **(headers or {})})
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read().decode("utf-8")
        finally:
            connection.close()

    def test_events_are_sent_as_one_json_object_per_line(self):
        events = [{"type": "delta", "text": "你好，"}, {"type": "delta", "text": "我是小和。"},
                  {"type": "done", "reply": "你好，我是小和。"}]
        port = self.serve(events)
        status, kind, body = self.post(port, {"text": "你好"})
        self.assertEqual(status, 200)
        self.assertTrue(kind.startswith("application/x-ndjson"))
        self.assertEqual([json.loads(line) for line in body.strip().split("\n")], events)

    def test_invalid_requests_get_a_plain_status_and_other_sites_are_refused(self):
        port = self.serve([{"type": "error", "status": 400, "error": "问题需为 1～4000 个字符"}])
        status, kind, body = self.post(port, {"text": ""})
        self.assertEqual((status, json.loads(body)), (400, {"error": "问题需为 1～4000 个字符"}))
        foreign = {"Origin": "https://example.com", "Sec-Fetch-Site": "cross-site"}
        self.assertEqual(self.post(port, {"text": "x"}, foreign)[0], 403)


if __name__ == "__main__":
    unittest.main()
