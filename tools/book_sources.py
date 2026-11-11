"""Bounded text providers with CSS, XPath, JSONPath and isolated JavaScript rules."""
import html
import errno
import ipaddress
import json
import re
import socket
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_RESPONSE = 4 * 1024 * 1024
USER_AGENT = "HexuLibrary/2.4 (personal local reading; MediaWiki API)"
# 书源里常见的编码写法都收敛到 Python 能解的名字，认不出的按 UTF-8 处理。
CHARSET_ALIASES = {"utf8": "utf-8", "utf-8": "utf-8", "utf8mb4": "utf-8", "gbk": "gbk", "gb2312": "gb18030",
                   "gb18030": "gb18030", "big5": "big5", "utf-16": "utf-8"}


from legado_host import LegadoHost
from source_rules import SourceError, RuleEngine, plain, tree


class Node:
    def __init__(self, tag="root", attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        if self.tag in {"script", "style", "nav", "noscript", "iframe"}:
            return ""
        if self.attrs.get("id") in {"headerContainer", "footerContainer", "licenseContainer"}:
            return ""
        classes = self.attrs.get("class", "").split()
        if any(c in classes for c in ("mw-editsection", "toc", "noprint", "navbox", "ws-noexport", "licenseContainer")):
            return ""
        result = "".join(child.text() if isinstance(child, Node) else child for child in self.children)
        return result + ("\n" if self.tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"} else "")


class Document(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.current = self.root
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        child = Node(tag, attrs, self.current)
        self.current.children.append(child)
        if tag not in {"br", "hr", "img", "meta", "link", "input", "source", "wbr", "area", "embed"}:
            self.current = child

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        current = self.current
        while current.parent:
            if current.tag == tag:
                self.current = current.parent
                return
            current = current.parent

    def handle_data(self, data):
        self.current.children.append(data)


def clean(text):
    return re.sub(r"\n{3,}", "\n\n", "\n".join(re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines())).strip()


def split_chapters(text):
    chapters, title, body = [], "正文", []
    for line in clean(text).splitlines():
        if re.match(r"^(第[零〇一二三四五六七八九十百千万\d]+[章节節回卷部]|chapter\s+\d+)", line, re.I) and len(line) < 100:
            if clean("\n".join(body)):
                chapters.append({"title": title, "text": clean("\n".join(body))})
            title, body = line, []
        else:
            body.append(line)
    if clean("\n".join(body)):
        chapters.append({"title": title, "text": clean("\n".join(body))})
    return chapters


def _matches(node, selector):
    if selector == "*":
        return True
    if not re.fullmatch(r"[\w*-]*(?:[.#][\w-]+)*", selector):
        raise SourceError("仅支持标签、class、id 和后代 CSS 选择器，不支持此规则：" + selector[:80])
    tag = re.match(r"^[\w*-]*", selector).group()
    if tag and tag != "*" and node.tag != tag:
        return False
    for prefix, value in re.findall(r"([.#])([\w-]+)", selector):
        if prefix == "#" and node.attrs.get("id") != value:
            return False
        if prefix == "." and value not in node.attrs.get("class", "").split():
            return False
    return True


def select(root, rule):
    rule = (rule or "").replace("@css:", "").strip()
    if not rule:
        return [root]
    nodes = [root]
    for part in rule.split():
        found = []
        for node in nodes:
            for candidate in node.walk():
                if candidate is not node and _matches(candidate, part) and candidate not in found:
                    found.append(candidate)
        nodes = found
    return nodes


def field(root, rule, default=""):
    rule = (rule or "").replace("@css:", "")
    selector, separator, attribute = rule.rpartition("@")
    if not separator:
        selector, attribute = rule or "", "text"
    nodes = select(root, selector)
    if not nodes:
        return default
    if attribute == "text":
        return clean("\n".join(node.text() for node in nodes))
    if attribute in {"href", "src", "title"}:
        return nodes[0].attrs.get(attribute, default)
    raise SourceError("不支持书源属性：" + attribute)


#: 本机代理（Clash 一类）的 fake-IP 段：198.18.0.0/15 是保留的基准测试网段，路由不到内网，
#: 只是被拿来当"域名→一个虚拟地址"的占位。默认仍然按保留地址拒绝，用户显式打开才放行这一段。
FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")
_allow_fake_ip = False


def set_fake_ip_allowed(value):
    """书源管理里的开关：允许经本机代理的 fake-IP 段访问书源。"""
    global _allow_fake_ip
    _allow_fake_ip = bool(value)


def fake_ip_allowed():
    return _allow_fake_ip


def validate_url(url, host, public_only=True):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"https", "http"} or parts.hostname != host or parts.username or parts.password or parts.port not in {None, 80, 443}:
        raise SourceError("书源网址必须使用同站点的 HTTP(S) 地址")
    if public_only:
        try:
            addresses = socket.getaddrinfo(host, None)
        except OSError as error:
            raise SourceError("无法解析书源域名") from error
        allowed = []
        for item in addresses:
            try:
                address = ipaddress.ip_address(item[4][0])
            except ValueError:
                continue
            if address.is_global or (_allow_fake_ip and address in FAKE_IP_RANGE):
                allowed.append(address)
        if not allowed:
            raise SourceError("书源不能访问本机、内网或保留地址"
                              "（若使用本机代理，请在书源管理里允许 fake-IP 段）")
    return url


def connection_message(error):
    """Expose a useful failure category, never a raw URL, proxy detail or exception string."""
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, socket.gaierror):
        return "DNS 解析失败，请检查当前网络的域名解析后重试"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "HTTPS 证书校验失败，请检查系统时间或网络代理"
    if isinstance(reason, ssl.SSLError):
        return "HTTPS 握手失败，请检查网络连接后重试"
    if isinstance(reason, TimeoutError):
        return "书源连接超时，请稍后重试或换源"
    code = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
    if isinstance(reason, ConnectionRefusedError) or code in {errno.ECONNREFUSED, 10061}:
        return "连接被拒绝，请检查站点或网络代理是否可用"
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError)) or code in {errno.ECONNRESET, errno.ECONNABORTED, 10054, 10053}:
        return "书源连接中断，请稍后重试"
    if code in {errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065}:
        return "网络无法到达书源，请检查当前网络连接"
    return "书源连接失败，请检查当前网络后重试或换源"


def fetch(url, host, trusted=False, headers=None, method="GET", body=None, charset="utf-8", https_only=False, windows_fallback=False):
    """host 为 None 表示"任意公网域名"：只给 java.ajax 用——有些源的接口在另一个子域，
    但仍必须通过公网地址检查（本机、内网、保留地址一律拒绝）。"""
    def check(target):
        if https_only and urllib.parse.urlsplit(target).scheme != "https":
            raise SourceError("内置书源仅允许 HTTPS，不能降级到不安全连接")
        wanted = host if host is not None else urllib.parse.urlsplit(target).hostname
        return validate_url(target, wanted, not trusted)
    check(url)
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    if method not in {"GET", "POST"}:
        raise SourceError("书源只支持 GET 与 POST 请求")
    charset = CHARSET_ALIASES.get(str(charset or "utf-8").lower(), "utf-8")
    if body is not None and (not isinstance(body, str) or len(body) > 128 * 1024):
        raise SourceError("书源请求体必须为不超过 128 KiB 的字符串")
    payload = body.encode(charset) if body is not None else None
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/html,text/plain", **safe_headers(headers or {})}
    request = urllib.request.Request(url, data=payload, method=method, headers=request_headers)
    try:
        with urllib.request.build_opener(Redirect()).open(request, timeout=18) as response:
            body = response.read(MAX_RESPONSE + 1)
            encoding = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as error:
        raise SourceError("书源返回 HTTP %d，请稍后重试或换源" % error.code) from error
    except (OSError, ValueError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        native = None
        if windows_fallback and trusted and https_only and isinstance(error, OSError) and not isinstance(reason, ssl.SSLCertVerificationError):
            import windows_book_http
            try:
                native = windows_book_http.fetch(url, check, request_headers, method, payload, MAX_RESPONSE)
            except OSError:
                raise SourceError(connection_message(error) + "；系统 HTTPS 重试也未能建立连接") from error
        if native is None:
            raise SourceError(connection_message(error)) from error
        body, encoding = native
    if len(body) > MAX_RESPONSE:
        raise SourceError("书源响应过大")
    try:
        return body.decode(encoding)
    except (UnicodeError, LookupError):
        return body.decode("gb18030", errors="replace")


class Wikisource:
    id = "wikisource"
    name = "维基文库 · 中文"
    host = "zh.wikisource.org"
    license = "维基文库公开文本；原作权利及转录许可见来源页，保留来源与修订号"

    def api(self, **params):
        url = "https://" + self.host + "/w/api.php?" + urllib.parse.urlencode({"format": "json", "formatversion": 2, "variant": "zh-cn", **params})
        result = json.loads(fetch(url, self.host, trusted=True))
        if "error" in result:
            raise SourceError("维基文库未找到该页面正文")
        return result

    def search(self, query):
        exact = self.api(action="query", titles=query, redirects=1, converttitles=1).get("query", {}).get("pages", [])
        found = [] if any("missing" not in page for page in exact) else self.api(action="query", list="search", srsearch="intitle:" + query, srnamespace=0, srlimit=6).get("query", {}).get("search", [])
        titles = list(dict.fromkeys([page["title"] for page in exact if "missing" not in page] + [page["title"] for page in found]))
        exact_titles = {page["title"] for page in exact if "missing" not in page}
        return [{"source_id": self.id, "source_key": title, "title": title, "exact": title in exact_titles, "author": "见来源页", "source": self.name, "source_url": "https://" + self.host + "/wiki/" + urllib.parse.quote(title), "license": self.license} for title in titles if ":" not in title][:6]

    def download(self, key, report, cancelled):
        if not isinstance(key, str) or not key or len(key) > 200 or ":" in key:
            raise SourceError("无效的维基文库书名")
        def page(title):
            return self.api(action="parse", page=title, prop="text|revid", redirects=1, disableeditsection=1)["parse"]
        first = page(key)
        title = first["title"]
        document = Document(first["text"])
        chapter_titles = []
        for node in document.root.walk():
            href = urllib.parse.unquote(node.attrs.get("href", "")).split("#")[0]
            if href.startswith("/wiki/" + title + "/"):
                chapter = href.removeprefix("/wiki/")
                if chapter not in chapter_titles:
                    chapter_titles.append(chapter)
        if len(chapter_titles) > 500:
            raise SourceError("此目录超过 500 章，请选择一个分卷下载")
        chapters = []
        author = next((node.text().strip() for node in document.root.walk() if node.tag == "a" and "/wiki/Author:" in node.attrs.get("href", "")), "维基文库")
        revision = first.get("revid")
        for index, chapter_title in enumerate(chapter_titles or [title]):
            if cancelled():
                raise SourceError("已取消下载")
            report(index, len(chapter_titles) or 1, chapter_title)
            parsed = first if chapter_title == title else page(chapter_title)
            root = Document(parsed["text"]).root
            # Header/navigation tables contain neighbouring-book links rather than正文.
            for node in root.walk():
                if node.tag == "table" and any(c in node.attrs.get("class", "") for c in ("header", "navbox")):
                    node.children = []
            content = clean(root.text())
            if len(content) < 40:
                raise SourceError("章节正文为空，未将目录页当作完整书籍保存")
            chapters.extend(split_chapters(content) if not chapter_titles else [{"title": chapter_title.split("/")[-1], "text": content}])
            if sum(len(item["text"]) for item in chapters) > 10_000_000:
                raise SourceError("书籍正文超过 1000 万字，请分卷下载")
        return {"title": title, "author": author, "source": self.name, "source_id": self.id, "source_key": key, "source_url": "https://" + self.host + "/wiki/" + urllib.parse.quote(title), "license": self.license, "revision": revision, "chapters": chapters}


def normalize_source(data):
    """Normalize declarative Legado rules without requiring every source to offer search."""
    if not isinstance(data, dict):
        raise SourceError("书源必须为 JSON 对象")
    if "bookSourceUrl" in data:
        def group(key):
            value = data.get(key)
            if value in (None, []):
                return {}
            if not isinstance(value, dict):
                raise SourceError(key + " 必须为对象")
            return value
        search, toc, content, info = (group(k) for k in ("ruleSearch", "ruleToc", "ruleContent", "ruleBookInfo"))
        data = {"name": data.get("bookSourceName", "导入书源"), "base_url": data["bookSourceUrl"], "search_url": data.get("searchUrl", ""),
                "search": {"items": search.get("bookList", ""), "title": search.get("name", ""), "url": search.get("bookUrl", ""), "author": search.get("author", "")},
                "info": {"init": info.get("init", ""), "title": info.get("name", ""), "author": info.get("author", ""), "toc_url": info.get("tocUrl", "")},
                "toc": {"items": toc.get("chapterList", ""), "title": toc.get("chapterName", ""), "url": toc.get("chapterUrl", ""), "next": toc.get("nextTocUrl", "")},
                "content": {"body": content.get("content", ""), "next": content.get("nextContentUrl", "")},
                "js_lib": data.get("jsLib", "") or "", "headers": data.get("header", {}) or {},
                "legacy_url": data.get("bookSourceUrl", ""), "source_type": data.get("bookSourceType", 0),
                "license": "导入书源：仅获取站点公开提供的免费正文"}
    # Keep only known fields; comments and Android event hooks are never executable configuration.
    data = {k: v for k, v in data.items() if k in {"name", "base_url", "search_url", "search", "info", "toc", "content", "js_lib", "headers", "license", "legacy_url", "source_type"}}
    if not isinstance(data.get("name"), str) or not data["name"].strip() or not isinstance(data.get("base_url"), str):
        raise SourceError("书源缺少名称或合法网址")
    data.setdefault("search_url", "")
    data.setdefault("search", {})
    data.setdefault("info", {})
    data.setdefault("js_lib", "")
    for key in ("search_url", "js_lib"):
        if not isinstance(data[key], str):
            raise SourceError(key + " 必须为字符串")
    for group in ("search", "info", "toc", "content"):
        if not isinstance(data.get(group), dict) or any(not isinstance(rule, str) for rule in data[group].values()):
            raise SourceError("书源规则必须是对象，选择器必须是字符串")
    for group, required in (("toc", ("items", "title", "url")), ("content", ("body",))):
        if any(not data[group].get(key, "").strip() for key in required):
            raise SourceError("书源缺少必要的目录或正文规则")
    has_search = bool(data["search_url"].strip() and all(data["search"].get(k, "").strip() for k in ("items", "title", "url")))
    if data["search_url"] and not has_search:
        raise SourceError("书源搜索地址已配置，但搜索列表、书名或链接规则不完整")
    encoded = json.dumps(data, ensure_ascii=False)
    # 安卓宿主类接口（Packages.*、设备注册、APP 专属源）无法在本机复现；
    # 其余 java.* 走 legado_host 的有界实现：纯计算、变量表、同站点 ajax、UI 类空实现。
    if re.search(r"\bPackages\s*\.|\b(?:android|javax)\.[A-Za-z]|\bgetAndroidId\b|\bandroidId\b", encoded):
        raise SourceError("此源依赖 Android 设备接口（Packages/设备号/APP 注册），本机运行环境无法复现；请换用网页源")
    if isinstance(data.get("source_type"), int) and data["source_type"] not in (0, 4):
        raise SourceError("此源是 APP 专属源（bookSourceType 非网页类型），本机只能下载网页正文")
    host = urllib.parse.urlsplit(data["base_url"]).hostname
    if not host:
        raise SourceError("书源缺少合法域名")
    # Import is offline validation; DNS/public-address checks happen on every actual request.
    validate_url(data["base_url"], host, public_only=False)
    data["headers"], header_note = parse_headers(data.get("headers", {}))
    engine = RuleEngine(data["js_lib"])
    for group in ("search", "info", "toc", "content"):
        for rule in data[group].values():
            engine.validate(rule)
    if not has_search and not data["info"].get("title"):
        raise SourceError("此源既没有搜索规则，也没有书籍信息中的书名规则")
    engines = ["CSS"]
    if re.search(r"@js:|<js>|\{\{(?!key\}\}|page\}\})", encoded, re.I): engines.append("JS")
    if re.search(r"@xpath:|\"(?://|\.//)", encoded, re.I): engines.append("XPath")
    if re.search(r"@json:|\$[.\[]", encoded, re.I): engines.append("JSONPath")
    capabilities = {"search": has_search, "engines": engines,
                    "java_ajax": bool(re.search(r"java\.(?:ajax|get)\s*\(", encoded)),
                    "needs_browser": bool(re.search(r"startBrowserAwait|getVerificationCode|startBrowser\s*\(", encoded))}
    if header_note:
        capabilities["header_note"] = header_note
    data["capabilities"] = capabilities
    return data


def parse_headers(value):
    """Legado 的 header 既可能是对象、JSON 字符串，也可能是一段 JS；后者的请求头无法离线求值。"""
    if isinstance(value, dict):
        return keep_headers(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}, ""
        if re.match(r"^[<@]|^\s*(?:js|javascript)\b", text, re.I):
            return {}, "此源的请求头由 JS 生成，本机先按空请求头访问"
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return keep_headers(parsed)
        pairs = {}
        for line in text.splitlines():
            if ":" in line:
                key, _, item = line.partition(":")
                pairs[key.strip()] = item.strip()
        if pairs:
            return keep_headers(pairs)
        return {}, "此源的请求头格式无法解析，已按空请求头访问"
    return {}, ""


HEADER_ALLOWED = {"user-agent", "accept", "accept-language", "content-type", "referer", "cookie"}


def keep_headers(headers):
    """只保留我们确实会发送的请求头；其余丢弃并说明，不因一个自定义头就拒整个源。"""
    kept, dropped = {}, []
    for key, value in (headers or {}).items():
        ok = (isinstance(key, str) and isinstance(value, str) and key.lower() in HEADER_ALLOWED
              and len(value) <= 2048 and "\r" not in value and "\n" not in value)
        if ok:
            kept[key] = value
        else:
            dropped.append(str(key)[:24])
    note = ""
    if dropped:
        note = "已忽略本机不发送的请求头：" + "、".join(dropped[:4])
    return kept, note


def parse_options(text):
    """Legado 的请求选项是单引号伪 JSON（{'method':'POST'}），也要能吃。"""
    try:
        value = json.loads(text)
    except ValueError:
        import ast
        prepared = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", text))
        prepared = re.sub(r"\bnull\b", "None", prepared)
        try:
            value = ast.literal_eval(prepared)
        except (ValueError, SyntaxError) as error:
            raise SourceError("书源搜索请求选项不是合法 JSON") from error
    if not isinstance(value, dict):
        raise SourceError("书源搜索请求选项不受支持")
    return value


def safe_headers(headers):
    if not isinstance(headers, dict) or len(headers) > 16:
        raise SourceError("书源请求头必须为对象且不超过 16 项")
    allowed = {"user-agent", "accept", "accept-language", "content-type", "referer", "cookie"}
    result = {}
    for key, value in headers.items():
        if not isinstance(key, str) or key.lower() not in allowed or not isinstance(value, str) or len(value) > 2048 or "\r" in value or "\n" in value:
            raise SourceError("书源请求头不受支持或包含非法字符")
        result[key] = value
    return result


class CssSource:
    """Historical name retained for stored sources; now uses the multi-format rule engine."""
    def __init__(self, identifier, config):
        self.id, self.config = identifier, config
        self.name, self.host = config["name"], urllib.parse.urlsplit(config["base_url"]).hostname
        # java.put / java.get 的作用域是这本源（阅读 App 的行为），跨字段、跨章节保留。
        self.variables = {}

    def engine(self, url, key=""):
        # 页面请求（搜索、目录、正文）仍然只能打本站；只有规则里的 java.ajax 可以跨域，
        # 因为不少源的接口挂在另一个子域上，但它同样要过公网地址检查。
        def ajax(target, **options):
            return fetch(target, None, **options)

        host = LegadoHost(request=ajax, base_url=url, variables=self.variables)
        return RuleEngine(self.config.get("js_lib", ""), {"baseUrl": url, "key": key}, host=host)

    def check_url(self, url):
        return validate_url(url, self.host)

    def request(self, url, **options):
        return fetch(url, self.host, **options)

    def document(self, url):
        headers = self.config.get("headers", {})
        return self.request(url, headers=headers) if headers else self.request(url)

    def search(self, query):
        config = self.config
        if not config.get("search_url"):
            return []
        spec = self.engine(config["base_url"], query).render_url(config["search_url"], query)
        parts = re.split(r",\s*(?=\{)", spec, maxsplit=1)
        url = urllib.parse.urljoin(config["base_url"], parts[0])
        if len(parts) == 2:
            options = parse_options(parts[1])
            if not isinstance(options, dict) or set(options) - {"method", "body", "headers", "charset"}:
                raise SourceError("书源请求选项不受支持")
            root = self.request(url, headers={**config.get("headers", {}), **safe_headers(options.get("headers", {}))},
                         method=str(options.get("method", "GET")).upper(), body=options.get("body"),
                         charset=options.get("charset", "utf-8"))
        else:
            root = self.document(url)
        engine, rule = self.engine(url, query), config["search"]
        results = []
        for node in engine.items(root, rule["items"])[:8]:
            title = engine.value(node, rule["title"])
            link = engine.value(node, rule["url"])
            if not title or not link: continue
            target = urllib.parse.urljoin(url, link)
            self.check_url(target)
            results.append({"source_id": self.id, "source_key": target, "title": title,
                            "author": engine.value(node, rule.get("author", ""), "未知作者") if rule.get("author") else "未知作者",
                            "source": self.name, "source_url": target, "license": config.get("license", "公开免费正文，见来源页")})
        return results

    def download(self, key, report, cancelled):
        self.check_url(key)
        root, engine = self.document(key), self.engine(key)
        info = self.config.get("info", {})
        if info.get("init"):
            root = engine.value(root, info["init"])
        title = engine.value(root, info["title"]) if info.get("title") else ""
        author = engine.value(root, info["author"]) if info.get("author") else ""
        toc_url = engine.value(root, info["toc_url"]) if info.get("toc_url") else ""
        current = urllib.parse.urljoin(key, toc_url) if toc_url else key
        if current != key:
            root = self.document(current)
        toc, visited, entries = self.config["toc"], set(), []
        while True:
            if cancelled(): raise SourceError("已取消下载")
            if current in visited or len(visited) >= 50:
                raise SourceError("目录分页循环或超过 50 页，未保存不完整正文")
            visited.add(current)
            engine = self.engine(current)
            for node in engine.items(root, toc["items"]):
                name, link = engine.value(node, toc["title"]), engine.value(node, toc["url"])
                if name and link:
                    url = urllib.parse.urljoin(current, link)
                    self.check_url(url)
                    if not any(entry[1] == url for entry in entries): entries.append((name, url))
            if len(entries) > 2000: raise SourceError("目录超过 2000 章，请分卷下载")
            next_url = engine.value(root, toc["next"]) if toc.get("next") else ""
            if not next_url: break
            current = urllib.parse.urljoin(current, next_url)
            self.check_url(current)
            root = self.document(current)
        if not entries:
            raise SourceError("目录为空，不会把目录页当作完整书籍保存")
        chapters, total_chars = [], 0
        for index, (name, url) in enumerate(entries):
            if cancelled(): raise SourceError("已取消下载")
            report(index, len(entries), name)
            body_parts, seen = [], set()
            current = url
            while True:
                if cancelled(): raise SourceError("已取消下载")
                if current in seen or len(seen) >= 20: raise SourceError("正文分页循环或超过 20 页，未保存不完整正文")
                seen.add(current)
                content_root = self.document(current)
                engine = self.engine(current)
                content = engine.value(content_root, self.config["content"]["body"])
                # @html is extraction syntax; the local reader stores readable text, never active HTML.
                if re.search(r"<[/!]?[a-zA-Z][^>]*>", content): content = plain(tree(content))
                content = clean(content)
                if not content: raise SourceError("正文为空或被站点拦截，请换源")
                body_parts.append(content)
                total_chars += len(content)
                if total_chars > 10_000_000: raise SourceError("正文过大，请分卷下载")
                next_url = engine.value(content_root, self.config["content"]["next"]) if self.config["content"].get("next") else ""
                if not next_url: break
                current = urllib.parse.urljoin(current, next_url)
                self.check_url(current)
            body = "\n\n".join(body_parts)
            if len(body) < 40: raise SourceError("正文过短或被站点拦截，请换源")
            chapters.append({"title": name, "text": body})
        return {"title": title, "author": author, "source_id": self.id, "source_key": key, "source_url": key,
                "source": self.name, "license": self.config.get("license", "公开免费正文，见来源页"), "chapters": chapters}
