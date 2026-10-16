"""Provider-neutral conversation transport. No credentials or conversation are persisted here."""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_TEXT = 4000
MAX_HISTORY = 12  # six completed turns, kept only in the page's memory
MAX_HISTORY_CHARS = 24000
MAX_REPLY = 16000


def configuration(resolved):
    address = resolved["HEXU_LLM_BASE_URL"].rstrip("/")
    model = resolved["HEXU_LLM_MODEL"]
    return hashlib.sha256((address + "\n" + model).encode()).hexdigest()[:20]


def history_messages(history):
    if not isinstance(history, list) or len(history) > MAX_HISTORY:
        raise ValueError("对话历史超出限制，请开启新对话")
    result = []
    total = 0
    if len(history) % 2:
        raise ValueError("对话历史必须是完整轮次")
    for index, entry in enumerate(history):
        role = "user" if index % 2 == 0 else "assistant"
        if not isinstance(entry, dict) or entry.get("role") != role:
            raise ValueError("对话历史格式不正确")
        content = entry.get("content")
        limit = MAX_TEXT if role == "user" else MAX_REPLY
        if not isinstance(content, str) or not content.strip() or len(content) > limit:
            raise ValueError("对话内容超出限制")
        total += len(content)
        if total > MAX_HISTORY_CHARS:
            raise ValueError("对话历史过长，请开启新对话")
        result.append({"role": role, "content": content})
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward Authorization to a different endpoint after a redirect.


def open_completion(request, timeout):
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


def completion(resolved, messages, validate_endpoint, *, timeout=60, intent=False):
    """Only this call consumes the resolved key; errors never echo upstream bodies or URLs."""
    base = resolved["HEXU_LLM_BASE_URL"].rstrip("/")
    try:
        validate_endpoint(base)
    except ValueError as error:
        return 503, {"error": str(error)}
    payload = {"model": resolved["HEXU_LLM_MODEL"], "messages": messages,
               "max_tokens": 300 if intent else 4096, "stream": False}
    # DeepSeek's extension is not sent to other OpenAI-compatible providers.
    if urllib.parse.urlsplit(base).hostname == "api.deepseek.com":
        payload["thinking"] = {"type": "disabled"}
    if intent:
        payload.update(temperature=0, response_format={"type": "json_object"})
    request = urllib.request.Request(base + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + resolved["HEXU_LLM_API_KEY"]})
    try:
        started = time.perf_counter()
        with open_completion(request, timeout=timeout) as response:
            # Bound even a broken/malicious provider's reply; no logging of request/response text.
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                return 502, {"error": "模型响应体积超出限制"}
            body = json.loads(raw.decode("utf-8"))
        choice = body["choices"][0]
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            return 502, {"error": "模型返回了空回答，请检查模型名称与接口兼容性"}
        return 200, {"reply": content.strip().replace(resolved["HEXU_LLM_API_KEY"], "[已隐去]")[:MAX_REPLY],
                     "truncated": len(content.strip()) > MAX_REPLY or choice.get("finish_reason") == "length",
                     "seconds": round(time.perf_counter() - started, 3)}
    except urllib.error.HTTPError as error:
        # Never forward provider error bodies: some gateways echo authorization/request headers.
        code = error.code
        hint = "请检查密钥或权限" if code in (401, 403) else "请检查模型名称、额度或服务状态"
        return 502, {"error": f"模型服务返回 {code}，{hint}"}
    except (TimeoutError, OSError):
        return 502, {"error": "模型连接失败或超时，请检查网络与接入地址"}
    except (ValueError, KeyError, IndexError, TypeError):
        return 502, {"error": "模型响应格式不兼容，请使用 Chat Completions 兼容接口"}


def chat(body, resolved, validate_endpoint, *, timeout=60, selected=None):
    if not isinstance(body, dict):
        return 400, {"error": "请求必须是 JSON 对象"}
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        return 400, {"error": "问题需为 1～4000 个字符"}
    try:
        history = history_messages(body.get("history", []))
    except ValueError as error:
        return 400, {"error": str(error)}
    if not resolved["HEXU_LLM_API_KEY"]:
        return 503, {"error": "尚未配置大模型，请打开本机设置填写 API 密钥、接入地址和模型名称"}
    identity = configuration(resolved)
    reset = bool(history and body.get("configuration") != identity)
    if reset:
        history = []
    prompt = ("你是和序图书馆的助手小和，使用中文自然对话，也可按用户要求使用其他语言。"
              "你可以回答知识、学习、编程、写作和日常问题，结合本轮对话历史承接追问。"
              "回答清楚、诚实；不确定时说明，不要声称可以回答一切或编造事实。"
              "你没有联网搜索、文件访问或下载执行工具，不要声称已经搜索网络、下载或操作书架。"
              "书架操作由程序单独执行，你在此仅回答问题，不输出动作 JSON。"
              "当前界面状态为：" + ("正在阅读。" if body.get("phase") == "READING" else "图书馆待命。"))
    if selected:
        prompt += ("当前阅读书籍的已验证元数据如下，仅作上下文，正文未提供，不得假装读过本地正文："
                   + json.dumps({"title": selected.get("title", ""), "author": selected.get("author", "")}, ensure_ascii=False))
    status, result = completion(resolved, [{"role": "system", "content": prompt}, *history,
                                         {"role": "user", "content": text.strip()}],
                                validate_endpoint, timeout=timeout)
    if status == 200:
        result.update(model=resolved["HEXU_LLM_MODEL"], configuration=identity, reset=reset)
    return status, result
