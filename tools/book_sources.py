"""Bounded text providers. Downloaded rules are data; JavaScript is never executed."""
import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser

MAX_RESPONSE = 4 * 1024 * 1024
USER_AGENT = "HexuLibrary/2.4 (personal local reading; MediaWiki API)"


class SourceError(ValueError):
    pass


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


def validate_url(url, host, public_only=True):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"https", "http"} or parts.hostname != host or parts.username or parts.password or parts.port not in {None, 80, 443}:
        raise SourceError("书源网址必须使用同站点的 HTTP(S) 地址")
    if public_only:
        try:
            addresses = socket.getaddrinfo(host, None)
        except OSError as error:
            raise SourceError("无法解析书源域名") from error
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise SourceError("书源不能访问本机、内网或保留地址")
    return url


def fetch(url, host, trusted=False):
    validate_url(url, host, not trusted)
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            validate_url(newurl, host, not trusted)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html,text/plain"})
    try:
        with urllib.request.build_opener(Redirect()).open(request, timeout=18) as response:
            body = response.read(MAX_RESPONSE + 1)
            encoding = response.headers.get_content_charset() or "utf-8"
    except (OSError, ValueError) as error:
        raise SourceError("书源连接失败，请稍后重试或换一个书源") from error
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
    """Accept our CSS schema and the declarative CSS subset of Legado 3.x."""
    if not isinstance(data, dict):
        raise SourceError("书源必须为 JSON 对象")
    if "bookSourceUrl" in data:
        search, toc, content = data.get("ruleSearch", {}), data.get("ruleToc", {}), data.get("ruleContent", {})
        data = {"name": data.get("bookSourceName", "导入书源"), "base_url": data["bookSourceUrl"], "search_url": data.get("searchUrl", ""),
                "search": {"items": search.get("bookList", ""), "title": search.get("name", ""), "url": search.get("bookUrl", ""), "author": search.get("author", "")},
                "toc": {"items": toc.get("chapterList", ""), "title": toc.get("chapterName", ""), "url": toc.get("chapterUrl", "")},
                "content": {"body": content.get("content", "")}, "license": "导入书源：仅获取站点公开提供的免费正文"}
    if not isinstance(data, dict) or not all(data.get(key) for key in ("name", "base_url", "search_url", "search", "toc", "content")):
        raise SourceError("书源缺少搜索、目录或正文规则")
    encoded = json.dumps(data, ensure_ascii=False)
    if any(marker in encoded for marker in ("@js:", "<js>", "javascript:", "java.", "@XPath:", "$.")):
        raise SourceError("此书源依赖 JS、XPath 或 JSONPath，当前静态 CSS 引擎不支持")
    if re.search(r"\{\{(?!key\}\}|page\}\})", encoded):
        raise SourceError("此书源含动态脚本，不会执行导入代码")
    host = urllib.parse.urlsplit(data["base_url"]).hostname
    if not host:
        raise SourceError("书源缺少合法域名")
    validate_url(data["base_url"], host)
    for group, required in (("search", ("items", "title", "url")), ("toc", ("items", "title", "url")), ("content", ("body",))):
        if not isinstance(data[group], dict) or any(not isinstance(data[group].get(key), str) or not data[group][key].strip() for key in required):
            raise SourceError("书源缺少必要的搜索、目录或正文选择器")
    for group in (data["search"], data["toc"], data["content"]):
        for rule in group.values():
            if not isinstance(rule, str):
                raise SourceError("书源规则必须是字符串")
            selector = rule.rsplit("@", 1)[0] if "@" in rule.replace("@css:", "") else rule
            for part in selector.replace("@css:", "").split():
                _matches(Node(), part)
    return data


class CssSource:
    def __init__(self, identifier, config):
        self.id, self.config = identifier, config
        self.name, self.host = config["name"], urllib.parse.urlsplit(config["base_url"]).hostname

    def document(self, url):
        return Document(fetch(url, self.host)).root

    def search(self, query):
        config = self.config
        url = urllib.parse.urljoin(config["base_url"], config["search_url"].replace("{{key}}", urllib.parse.quote(query)).replace("{query}", urllib.parse.quote(query)).replace("{{page}}", "1"))
        root = self.document(url)
        rule = config["search"]
        return [{"source_id": self.id, "source_key": urllib.parse.urljoin(url, field(node, rule["url"])), "title": field(node, rule["title"]), "author": field(node, rule.get("author", ""), "未知作者") if rule.get("author") else "未知作者", "source": self.name, "source_url": urllib.parse.urljoin(url, field(node, rule["url"])), "license": config.get("license", "公开免费正文，见来源页")} for node in select(root, rule["items"])][:8]

    def download(self, key, report, cancelled):
        validate_url(key, self.host)
        root = self.document(key)
        toc = self.config["toc"]
        entries = [(field(node, toc["title"]), urllib.parse.urljoin(key, field(node, toc["url"]))) for node in select(root, toc["items"])]
        entries = list(dict.fromkeys(entries))
        if not entries or len(entries) > 500:
            raise SourceError("目录为空或超过 500 章，不会把未完成书籍保存为已入库")
        chapters = []
        for index, (title, url) in enumerate(entries):
            if cancelled():
                raise SourceError("已取消下载")
            report(index, len(entries), title)
            content = field(self.document(url), self.config["content"]["body"])
            if len(content) < 40:
                raise SourceError("正文为空或被站点拦截，请换源")
            chapters.append({"title": title, "text": content})
            if sum(len(item["text"]) for item in chapters) > 10_000_000:
                raise SourceError("正文过大，请分卷下载")
        return {"title": "", "author": "", "source_id": self.id, "source_key": key, "source_url": key, "source": self.name, "license": self.config.get("license", "公开免费正文，见来源页"), "chapters": chapters}
