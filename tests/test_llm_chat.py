import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import llm_chat

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
            self.assertNotIn("response_format", payload)
            self.assertEqual(reply["reply"], "测试回答")
            self.assertNotIn(CONFIG["HEXU_LLM_API_KEY"], json.dumps(reply))

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

if __name__ == "__main__":
    unittest.main()
