"""Search public book-directory metadata; never submit the site's protected search form."""
import itertools
import re
import threading
import time
import unicodedata
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from xml.etree import ElementTree

from pypinyin import Style, lazy_pinyin, pinyin
from builtin_book_sources import BuiltinNovelSource
from source_rules import SourceError

_index_lock = threading.Lock()
_index = (0.0, ())


def normalized(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).lower())


def keys(text):
    def roman(parts):
        return re.sub(r"[^a-z0-9]", "", "".join(parts).lower())
    primary = roman(lazy_pinyin(text))
    variants = {primary}
    # Bound the heteronym product even for a long, deliberately ambiguous query.
    choices = pinyin(text, style=Style.NORMAL, heteronym=True)
    variants.update(roman(parts) for parts in itertools.islice(itertools.product(*choices), 32))
    variants |= {item.replace("v", "u") for item in variants}
    return {item for item in variants if len(item) >= 2}


class WyshuSource(BuiltinNovelSource):
    def __init__(self):
        super().__init__("wyshu")

    def canonical(self, url):
        parts = urlsplit(url)
        return urlunsplit(parts._replace(path=quote(parts.path, safe="/%-_")))

    def check_url(self, url):
        return super().check_url(self.canonical(url))

    def document(self, url):
        return super().document(self.canonical(url))

    def index(self):
        global _index
        with _index_lock:
            if _index[1] and time.monotonic() - _index[0] < 86400:
                return _index[1]
            markup = self.document("https://www.wyshu.com/sitemap/bookname_1.xml")
            if re.search(r"<!DOCTYPE|<!ENTITY", markup, re.I):
                raise SourceError("公开书目索引包含不支持的 XML 声明")
            try:
                root = ElementTree.fromstring(markup)
            except ElementTree.ParseError as error:
                raise SourceError("公开书目索引无效或暂时不可用") from error
            urls, seen = [], set()
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] != "loc" or not node.text:
                    continue
                url = node.text.strip()
                url = self.canonical(url)
                self.check_url(url)
                if re.fullmatch(r"/(?:ys|wx|yq|wl|ds|xy|kh|xd|wg)/[\w%-]+/", urlsplit(url).path) and url not in seen:
                    urls.append(url)
                    seen.add(url)
                if len(urls) > 20000:
                    raise SourceError("公开书目索引超过 20000 项")
            if not urls:
                raise SourceError("公开书目索引为空，不会把验证页当成搜索结果")
            _index = (time.monotonic(), tuple(urls))
            return _index[1]

    def search(self, query):
        query = query.strip()
        if not query or len(query) > 160:
            raise SourceError("请输入 1～160 字的书名")
        variants = keys(query)
        if not variants:
            raise SourceError("请使用完整中文书名或书名拼音检索公开目录")
        candidates = []
        for url in self.index():
            slug = unquote(urlsplit(url).path.strip("/").split("/")[-1]).lower().replace("-", "").replace("_", "")
            if any(key in slug for key in variants):
                candidates.append((slug not in variants, len(slug), url))
        results = []
        for _, _, url in sorted(candidates)[:12]:
            root, engine = self.document(url), self.engine(url)
            title = engine.value(root, self.config["info"]["title"])
            author = engine.value(root, self.config["info"]["author"], "未知作者")
            if not title:
                raise SourceError("书目页面无有效书名或需要浏览器验证")
            # Pinyin only locates candidates; Chinese queries must match actual Chinese metadata.
            if not query.isascii() and normalized(query) not in normalized(title):
                continue
            results.append({"source_id": self.id, "source_key": url, "title": title, "author": author,
                            "source": self.name, "source_url": url, "license": self.config["license"]})
            if len(results) == 8:
                break
        if not results:
            raise SourceError("公开目录检索未命中，请尝试完整书名或拼音；该站全站搜索需要浏览器验证")
        return results
