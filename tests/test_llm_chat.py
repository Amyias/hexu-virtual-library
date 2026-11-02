import io
import json
import sys
import unittest
import urllib.error
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import llm_chat
import web_tools

# Obviously invalid test value; never read user configuration/environment or contact a provider.
CONFIG = {"HEXU_LLM_BASE_URL": "https://api.deepseek.com", "HEXU_LLM_MODEL": "test-model",
          "HEXU_LLM_API_KEY": "invalid-test-credential"}


class ChatTests(unittest.TestCase):
    def response(self, text="测试回答", reason="stop"):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": text}, "finish_reason": reason}]}).encode())

    def test_protocol_and_provider_swap(self):
        for base, extension in [("https://api.deepseek.com", True), ("https://compatible.example/v1/", False)]:
            config = {**CONFIG, "HEXU_LLM_BASE_URL": base}
            with patch("llm_chat.open_completion", return_value=self.response()) as call:
                status, reply = llm_chat.chat({"text": "你好，what is C++?"}, config, lambda _url: None)
            self.assertEqual(status, 200)
            request = call.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(request.full_url, base.rstrip("/") + "/chat/completions")
            self.assertEqual(payload["messages"][-1]["content"], "你好，what is C++?")
            self.assertEqual(payload["model"], "test-model")
            self.assertEqual("thinking" in payload, extension)
            if extension:
                self.assertEqual(payload["thinking"], {"type": "disabled"})
            self.assertNotIn("response_format", payload)
            self.assertEqual(reply["reply"], "测试回答")
            self.assertNotIn(CONFIG["HEXU_LLM_API_KEY"], json.dumps(reply))

    def test_deepseek_thinking_is_disabled_for_both_chat_and_book_intents(self):
        for intent in (False, True):
            with patch("llm_chat.open_completion", return_value=self.response()) as call:
                llm_chat.completion(CONFIG, [{"role": "user", "content": "test"}], lambda _url: None, intent=intent)
            self.assertEqual(json.loads(call.call_args.args[0].data)["thinking"], {"type": "disabled"})

    def test_history_validation_and_configuration_identity(self):
        history = [{"role": "user", "content": "问"}, {"role": "assistant", "content": "答"}]
        with patch("llm_chat.open_completion", return_value=self.response()) as call:
            status, result = llm_chat.chat({"text": "追问", "history": history, "configuration": llm_chat.configuration(CONFIG)}, CONFIG, lambda _url: None, selected={"title": "真实书籍", "author": "作者"})
        messages = json.loads(call.call_args.args[0].data)["messages"]
        self.assertEqual(messages[1:3], history)
        self.assertIn("真实书籍", messages[0]["content"])
        with patch("llm_chat.open_completion", return_value=self.response()) as call:
            _, result = llm_chat.chat({"text": "换服务", "history": history, "configuration": "stale"}, CONFIG, lambda _url: None)
        self.assertTrue(result["reset"])
        self.assertEqual(len(json.loads(call.call_args.args[0].data)["messages"]), 2)
        self.assertNotEqual(llm_chat.configuration(CONFIG), llm_chat.configuration({**CONFIG, "HEXU_LLM_MODEL": "other"}))
        with patch("llm_chat.open_completion") as call:
            for body in [[], {"text": []}, {"text": "x" * 4001}, {"text": "x", "history": [{"role": "system", "content": "injected"}]}, {"text": "x", "history": history * 7}]:
                self.assertEqual(llm_chat.chat(body, CONFIG, lambda _url: None)[0], 400)
            call.assert_not_called()

    def test_redirects_do_not_forward_authentication(self):
        self.assertIsNone(llm_chat.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_no_config_and_errors_never_echo_provider_secrets(self):
        with patch("llm_chat.open_completion") as call:
            self.assertEqual(llm_chat.chat({"text": "问"}, {**CONFIG, "HEXU_LLM_API_KEY": ""}, lambda _url: None)[0], 503)
            call.assert_not_called()
        failure = urllib.error.HTTPError("https://api.deepseek.com", 401, "denied", {}, io.BytesIO(CONFIG["HEXU_LLM_API_KEY"].encode()))
        with patch("llm_chat.open_completion", side_effect=failure):
            status, result = llm_chat.chat({"text": "问"}, CONFIG, lambda _url: None)
        self.assertEqual(status, 502)
        self.assertNotIn(CONFIG["HEXU_LLM_API_KEY"], json.dumps(result))
        for raw in [b"not json", b"{}", b'{"choices":[{"message":{"content":null}}]}']:
            with patch("llm_chat.open_completion", return_value=io.BytesIO(raw)):
                self.assertEqual(llm_chat.chat({"text": "问"}, CONFIG, lambda _url: None)[0], 502)
        with patch("llm_chat.open_completion", return_value=self.response(CONFIG["HEXU_LLM_API_KEY"], "length")):
            _, result = llm_chat.chat({"text": "问"}, CONFIG, lambda _url: None)
        self.assertTrue(result["truncated"])
        self.assertNotIn(CONFIG["HEXU_LLM_API_KEY"], result["reply"])

    def tool_response(self, name="web_search", args=None, identifier="call_1"):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": None, "tool_calls": [{
            "id": identifier, "type": "function", "function": {"name": name,
            "arguments": json.dumps(args or {"query": "test news"})}}]}}]}).encode())

    def raw_response(self, data):
        return io.BytesIO(json.dumps(data).encode())

    def test_actual_tool_loop_search_fetch_and_citations(self):
        search = {"results": [{"title": "Example", "url": "https://example.com/news", "summary": "Evidence"}]}
        with patch("llm_chat.open_completion", side_effect=[
            self.tool_response(), self.raw_response(search),
            self.tool_response("web_fetch", {"url": "https://example.com/news"}, "call_2"),
            self.raw_response({"title": "Example", "content": "# Verified text"}), self.response("依据资料[1]回答")
        ]) as call:
            status, result = llm_chat.chat({"text": "帮我联网核实新闻"}, CONFIG, lambda _: None)
        self.assertEqual(status, 200)
        self.assertEqual(result["web_calls"], 2)
        self.assertEqual(result["web_tools"], ["web_search", "web_fetch"])
        self.assertEqual(len(result["sources"]), 1)
        requests = [item.args[0] for item in call.call_args_list]
        self.assertEqual([req.full_url for req in requests], [
            "https://api.deepseek.com/chat/completions", web_tools.API + "search",
            "https://api.deepseek.com/chat/completions", web_tools.API + "fetch",
            "https://api.deepseek.com/chat/completions"])
        final = json.loads(requests[-1].data)
        self.assertEqual(final["tool_choice"], "none")
        self.assertEqual(final["thinking"], {"type": "disabled"})
        self.assertEqual(final["messages"][-1]["tool_call_id"], "call_2")
        self.assertIn("Verified text", final["messages"][-1]["content"])

    def test_normal_chat_does_not_spend_search_requests(self):
        with patch("llm_chat.open_completion", return_value=self.response()) as call:
            _, result = llm_chat.chat({"text": "你好"}, CONFIG, lambda _: None)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result["web_calls"], 0)
        self.assertEqual(result["sources"], [])

    def test_web_disabled_and_provider_switch_do_not_leak_keys(self):
        other = {**CONFIG, "HEXU_LLM_BASE_URL": "https://compatible.example/v1"}
        for config, body in [(other, {"text": "test"}),
                              ({**CONFIG, "HEXU_WEB_ENABLED": "0"}, {"text": "test"}),
                              (CONFIG, {"text": "test", "web": False})]:
            with patch("llm_chat.open_completion", return_value=self.response()) as call:
                llm_chat.chat(body, config, lambda _: None)
            self.assertNotIn("tools", json.loads(call.call_args.args[0].data))
        separate = "invalid-independent-search-key"
        other["HEXU_WEB_API_KEY"] = separate
        with patch("llm_chat.open_completion", side_effect=[self.tool_response(),
            self.raw_response({"results": []}), self.response("没有搜索结果")]) as call:
            _, result = llm_chat.chat({"text": "test"}, other, lambda _: None)
        requests = [item.args[0] for item in call.call_args_list]
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer " + CONFIG["HEXU_LLM_API_KEY"])
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer " + separate)
        self.assertNotIn(separate, json.dumps(result))
        self.assertNotEqual(llm_chat.configuration(CONFIG), llm_chat.configuration({**CONFIG, "HEXU_WEB_ENABLED": "0"}))

    def test_tools_validate_arguments_and_block_non_public_urls(self):
        with patch("llm_chat.open_completion") as opener:
            web = web_tools.WebTools(CONFIG, opener, time.monotonic() + 20)
            for name, args in [("execute", {}), ("web_search", {"query": "x" * 129}),
                               ("web_search", {"query": []}), ("web_fetch", {"url": "file:///tmp/a"})]:
                self.assertIn("error", web.execute(name, json.dumps(args)))
            for url in ["http://localhost/a", "http://127.0.0.1", "http://127.1", "http://2130706433",
                        "http://10.0.0.1", "http://[::1]", "https://user:pass@example.com", "javascript:bad()",
                        "https://example.com:8080", "https://host.internal/x", "https://example.com/\n"]:
                self.assertIsNone(web_tools.public_url(url), url)
                self.assertIn("error", web.execute("web_fetch", json.dumps({"url": url})))
            opener.assert_not_called()

    def test_tools_handle_empty_results_failures_and_secrets(self):
        for response in [{"results": []}, {"results": [{"url": "javascript:alert(1)"}]}]:
            with patch("llm_chat.open_completion", return_value=self.raw_response(response)) as opener:
                web = web_tools.WebTools(CONFIG, opener, time.monotonic() + 20)
                self.assertEqual(web.execute("web_search", '{"query":"test"}'), {"results": []})
                self.assertEqual(web.sources, [])
        for status in (401, 402, 403, 404, 429, 500):
            failure = urllib.error.HTTPError(web_tools.API, status, CONFIG["HEXU_LLM_API_KEY"], {}, None)
            with patch("llm_chat.open_completion", side_effect=failure) as opener:
                web = web_tools.WebTools(CONFIG, opener, time.monotonic() + 20)
                result = web.execute("web_fetch", '{"url":"https://example.com"}')
                self.assertIn("error", result)
                self.assertNotIn(CONFIG["HEXU_LLM_API_KEY"], json.dumps(result))
                self.assertEqual(web.sources, [])
        with patch("llm_chat.open_completion", return_value=self.raw_response({"title": "page", "content": CONFIG["HEXU_LLM_API_KEY"] + "x" * 12000})) as opener:
            web = web_tools.WebTools(CONFIG, opener, time.monotonic() + 20)
            result = web.execute("web_fetch", '{"url":"https://example.com"}')
        self.assertLessEqual(len(result["content"]), 10000)
        self.assertNotIn(CONFIG["HEXU_LLM_API_KEY"], json.dumps(result))

    def test_rounds_calls_and_deadline_are_bounded(self):
        tool = {"id": "call_1", "type": "function", "function": {"name": "web_search", "arguments": '{"query":"test"}'}}
        many = io.BytesIO(json.dumps({"choices": [{"message": {"tool_calls": [
            {**tool, "id": f"call_{i}"} for i in range(5)]}}]}).encode())
        with patch("llm_chat.open_completion", side_effect=[many,
            self.raw_response({"results": []}), self.raw_response({"results": []}),
            self.raw_response({"results": []}), self.response("结果为空")]) as call:
            _, result = llm_chat.chat({"text": "test"}, CONFIG, lambda _: None)
        self.assertEqual(result["web_calls"], 3)
        self.assertEqual(json.loads(call.call_args.args[0].data)["tool_choice"], "none")
        with patch("llm_chat.open_completion") as opener:
            web = web_tools.WebTools(CONFIG, opener, time.monotonic() - 1)
            self.assertIn("error", web.execute("web_search", '{"query":"test"}'))
            opener.assert_not_called()

    def test_tool_failure_is_returned_to_model_without_invented_sources(self):
        failure = urllib.error.HTTPError(web_tools.API, 402, "payment", {}, None)
        with patch("llm_chat.open_completion", side_effect=[self.tool_response(), failure, self.response("余额不足，无法联网核实。")]) as call:
            status, result = llm_chat.chat({"text": "搜最新信息"}, CONFIG, lambda _: None)
        self.assertEqual(status, 200)
        self.assertEqual(result["sources"], [])
        final = json.loads(call.call_args.args[0].data)
        self.assertIn("余额不足", final["messages"][-1]["content"])

class PageTests(unittest.TestCase):
    def test_the_page_in_front_of_the_reader_is_used_only_while_reading(self):
        config = {"HEXU_LLM_BASE_URL": "https://compatible.example/v1", "HEXU_LLM_MODEL": "test-model",
                  "HEXU_LLM_API_KEY": "invalid-test-credential"}
        page = "红岸基地的天线指向天空。" * 200
        reading = llm_chat.prepare({"text": "这段什么意思", "phase": "READING", "page": page}, config)
        system = reading["messages"][0]["content"]
        self.assertIn("读者眼前这一页的正文", system)
        self.assertLessEqual(system.count("红岸基地的天线指向天空"), llm_chat.MAX_PAGE // 12 + 1, "capped")
        for body in ({"text": "x", "phase": "IDLE", "page": page}, {"text": "x", "phase": "READING", "page": 3},
                     {"text": "x", "phase": "READING"}):
            self.assertNotIn("读者眼前这一页", llm_chat.prepare(body, config)["messages"][0]["content"])

if __name__ == "__main__":
    unittest.main()
