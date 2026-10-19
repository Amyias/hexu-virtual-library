"""Bounded DeepSeek Search/Fetch tools. Credentials only go to the official API."""
import ipaddress
import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.deepseek.com/v1/tools/"
MAX_CALLS = 3
MAX_ROUNDS = 2
TOOLS = [
    {"type": "function", "function": {
        "name": "web_search", "description": "搜索实时网页。用于最新信息、事实核查或用户要求联网检索；普通闲聊不调用。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词，不超过128字"}},
            "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "web_fetch", "description": "读取用户提供或搜索结果中的公开网页，获取正文再回答；不能下载书籍入库。",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
            "required": ["url"], "additionalProperties": False}}},
]


def key_for(config):
    if str(config.get("HEXU_WEB_ENABLED", "1")).lower() in ("0", "false", "off"):
        return ""
    independent = config.get("HEXU_WEB_API_KEY", "")
    if independent:
        return independent
    if urllib.parse.urlsplit(config.get("HEXU_LLM_BASE_URL", "")).hostname == "api.deepseek.com":
        return config.get("HEXU_LLM_API_KEY", "")
    return ""


def summary(config):
    enabled = str(config.get("HEXU_WEB_ENABLED", "1")).lower() not in ("0", "false", "off")
    return {"web_enabled": enabled, "web_ready": bool(key_for(config)),
            "web_key_set": bool(config.get("HEXU_WEB_API_KEY")),
            "web_key_reused": bool(key_for(config)) and not bool(config.get("HEXU_WEB_API_KEY"))}


def redact(text, config):
    text = str(text)
    for name in ("HEXU_LLM_API_KEY", "HEXU_WEB_API_KEY"):
        if config.get(name):
            text = text.replace(config[name], "[已隐去]")
    return text


def public_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 33 for c in value):
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        if (parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password
                or parsed.port not in (None, 80, 443) or "%" in host
                or host == "localhost" or host.endswith((".local", ".internal", ".localhost"))):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            # Refuse numeric/abbreviated addresses (127.1, integer and octal IP forms).
            if "." not in host or all(part.isdigit() for part in host.split(".")) or host.startswith("0x"):
                return None
        return value
    except ValueError:
        return None


class WebTools:
    def __init__(self, config, opener, deadline):
        self.config, self.opener, self.deadline = config, opener, deadline
        self.calls = 0
        self.actions = []
        self.sources = []

    def source(self, title, url):
        url = public_url(url)
        if not url:
            return None
        for item in self.sources:
            if item["url"] == url:
                return item["id"]
        if len(self.sources) >= 8:
            return None
        item = {"id": len(self.sources) + 1, "title": redact(title, self.config)[:180] or url,
                "url": redact(url, self.config)}
        self.sources.append(item)
        return item["id"]

    def execute(self, name, arguments):
        if self.calls >= MAX_CALLS:
            return {"error": "本轮联网次数已达上限，请根据现有资料回答。"}
        try:
            if not isinstance(arguments, str) or len(arguments) > 12000:
                raise ValueError()
            args = json.loads(arguments)
            if not isinstance(args, dict):
                raise ValueError()
            if name == "web_search":
                query = args.get("query")
                if not isinstance(query, str) or not query.strip() or len(query) > 128:
                    raise ValueError()
                payload = {"query": query.strip(), "count": 4, "need_content": False}
                endpoint = "search"
            elif name == "web_fetch":
                url = public_url(args.get("url"))
                if not url:
                    raise ValueError()
                payload, endpoint = {"url": url}, "fetch"
            else:
                raise ValueError()
        except (ValueError, TypeError):
            return {"error": "不支持的工具或无效参数。只可搜索关键词或读取公开 HTTP/HTTPS 网页。"}
        key = key_for(self.config)
        if not key:
            return {"error": "联网未启用或未配置 DeepSeek 搜索密钥。"}
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return {"error": "联网查询已超时。"}
        self.calls += 1
        self.actions.append(name)
        request = urllib.request.Request(API + endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        try:
            with self.opener(request, timeout=min(12, remaining)) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError()
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError()
            if endpoint == "fetch":
                content = data.get("content")
                if not isinstance(content, str) or not content.strip():
                    return {"error": "该网页没有可读取的正文。"}
                title = data.get("title") if isinstance(data.get("title"), str) else url
                return {"source_id": self.source(title, url), "title": redact(title, self.config)[:180],
                        "url": url, "content": redact(content, self.config)[:10000]}
            if not isinstance(data.get("results"), list):
                raise ValueError()
            results = []
            for row in data["results"][:4]:
                if not isinstance(row, dict) or not public_url(row.get("url")):
                    continue
                title = str(row.get("title") or row["url"])[:180]
                results.append({"source_id": self.source(title, row["url"]),
                                "title": redact(title, self.config), "url": row["url"],
                                "summary": redact(row.get("summary") or row.get("snippet") or "", self.config)[:1800],
                                "date": str(row.get("date") or "")[:40]})
            return {"results": results}
        except urllib.error.HTTPError as error:
            hints = {401: "DeepSeek 搜索密钥无效", 402: "DeepSeek 余额不足", 403: "网页访问被拒绝",
                     404: "无法读取该网页", 429: "联网服务繁忙，请稍后重试"}
            return {"error": hints.get(error.code, "联网服务暂时不可用"), "status": error.code}
        except (OSError, TimeoutError):
            return {"error": "联网服务连接失败或超时。"}
        except (ValueError, TypeError, KeyError):
            return {"error": "联网服务响应格式不正确。"}
