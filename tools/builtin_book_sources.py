"""Two fixed HTTPS novel sites, sharing the bounded source download pipeline."""
import copy
import re
import threading
import time
from urllib.parse import urlsplit

from book_sources import CssSource, SourceError, fetch, validate_url


BUILTIN_SOURCES = {
    "tianya": {
        "name": "天涯书库",
        "base_url": "https://tianyashuku.net/",
        "search_url": '/e/search/index.php,{"method":"POST","body":"tbname=bookname&show=title%2Cwriter&tempid=1&keyboard={{key}}","headers":{"Content-Type":"application/x-www-form-urlencoded"}}',
        "search": {"items": "article.themebetter-ent-loop-item", "title": "h2 a@text", "url": "h2 a@href"},
        "info": {"title": 'meta[property="og:novel:book_name"]@content',
                 "author": 'meta[property="og:novel:author"]@content'},
        "toc": {"items": "#list dd a", "title": "@text", "url": "@href"},
        "content": {"body": ".m-article-text@text"},
        "license": "天涯书库公开阅读页面；作品权利与使用说明见来源站点",
    },
    "shubao": {
        "name": "书包网 · 简体",
        "base_url": "https://cn.shubaoc.com/",
        "search_url": "/search/{{key}}/",
        "search": {"items": ".novel-list .novel-item", "title": ".novel-title a@text",
                   "url": ".novel-title a@href", "author": ".meta-item:first-child .meta-value@text"},
        "info": {"title": "h1@text##^[《\\s]+|[》\\s]+$##",
                 "author": '.novel-meta-item a[title$="作品集"]@text'},
        "toc": {"items": "#chapterList a", "title": "@text", "url": "@href",
                "next": "//div[contains(@class,'pagination-controls')]/a[contains(.,'下一页')]/@href"},
        "content": {"body": ".chapter-content@text"},
        "license": "书包网公开阅读页面；作品权利与使用说明见来源站点",
    },
}

_locks = {key: threading.Lock() for key in BUILTIN_SOURCES}
_last_request = {key: 0.0 for key in BUILTIN_SOURCES}


class BuiltinNovelSource(CssSource):
    def __init__(self, identifier):
        if identifier not in BUILTIN_SOURCES:
            raise SourceError("内置书源不存在")
        super().__init__(identifier, copy.deepcopy(BUILTIN_SOURCES[identifier]))

    def check_url(self, url):
        # Only these compiled-in HTTPS origins use the system resolver/proxy. TLS still checks
        # the real site's hostname. Imported JSON cannot opt out of public-address checks.
        validate_url(url, self.host, public_only=False)
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.port not in {None, 443} or parts.fragment:
            raise SourceError("内置书源仅接受本站 HTTPS 书籍地址")
        pattern = (r"/(?:[a-z0-9_-]+/\d+/(?:\d+\.html)?|e/search/index\.php|e/search/result/)"
                   if self.id == "tianya" else r"/(?:search/[^/]+/|novel/[a-z0-9]+/(?:[a-z0-9]+\.html|\d+/)?)")
        if not re.fullmatch(pattern, parts.path):
            raise SourceError("此地址不是内置书源的搜索、书籍或章节页面")
        return url

    def request(self, url, **options):
        self.check_url(url)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; HexuLibrary/2.5; personal reading)",
                   "Referer": self.config["base_url"], **options.pop("headers", {})}
        # Pace requests across all instances/jobs of this source, without executing site JS.
        with _locks[self.id]:
            delay = 0.35 - (time.monotonic() - _last_request[self.id])
            if delay > 0:
                time.sleep(delay)
            _last_request[self.id] = time.monotonic()
        markup = fetch(url, self.host, trusted=True, https_only=True, windows_fallback=True, headers=headers, **options)
        if self.id == "tianya" and "/e/search/" in url and "<title>信息提示" in markup:
            if "没有搜索到相关" not in markup:
                raise SourceError("天涯书库暂未返回搜索结果，可能请求过于频繁；请稍后重试或选择书包网")
        return markup
