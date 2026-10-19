"""Real source-rule and import regressions; no remote site or user library required."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
from book_sources import CssSource, SourceError, normalize_source


def config():
    return {"bookSourceName": "Mixed fixture", "bookSourceUrl": "https://example.com",
            "searchUrl": "/search?q={{key}}", "ruleSearch": {
                "bookList": "@js:JSON.parse(result).books.map(x => JSON.stringify(x))",
                "name": "$.name", "bookUrl": "$.url", "author": "$.author"},
            "ruleBookInfo": {"name": "//h1/text()", "author": "#author@text", "tocUrl": "#toc@href"},
            "ruleToc": {"chapterList": "@XPath://ul[@id='chapters']/li/a", "chapterName": "ownText", "chapterUrl": "href", "nextTocUrl": "text.下一页@href"},
            "ruleContent": {"content": ".body@html"}}

class SourceCompatibilityTests(unittest.TestCase):
    def test_mixed_js_jsonpath_xpath_download_and_paginated_toc(self):
        pages = {"https://example.com/search?q=Novel": json.dumps({"books": [{"name": "Novel", "url": "/book", "author": "Writer"}]}),
                 "https://example.com/book": '<h1>Novel</h1><span id="author">Writer</span><a id="toc" href="/toc">Contents</a>',
                 "https://example.com/toc": '<ul id="chapters"><li><a href="/one">One<span>badge</span></a></li></ul><a href="/toc2">下一页</a>',
                 "https://example.com/toc2": '<ul id="chapters"><li><a href="/two">Two</a></li></ul>',
                 "https://example.com/one": '<div class="body"><p>' + 'First paragraph. ' * 10 + '</p><script>do_not_read()</script></div>',
                 "https://example.com/two": '<div class="body">' + 'Second paragraph. ' * 10 + '</div>'}
        with patch("book_sources.validate_url"), patch("book_sources.fetch", side_effect=lambda url, *_a, **_k: pages[url]):
            provider = CssSource("fixture", normalize_source(config()))
            found = provider.search("Novel")
            self.assertEqual(found[0]["title"], "Novel")
            result = provider.download(found[0]["source_key"], lambda *_: None, lambda: False)
            self.assertEqual(result["author"], "Writer")
            self.assertEqual([c["title"] for c in result["chapters"]], ["One", "Two"])
            self.assertNotIn("do_not_read", result["chapters"][0]["text"])

    def test_source_with_empty_search_array_imports_without_attribute_error(self):
        from book_library import BookLibrary
        source = config(); source.pop("searchUrl"); source["ruleSearch"] = []
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"):
            library = BookLibrary(temp)
            result = library.add_sources([source])
            self.assertEqual(len(result["accepted"]), 1, result)
            imported = next(iter(library.sources().values()))
            self.assertFalse(imported["capabilities"]["search"])

    def test_pure_javascript_source_is_accepted_but_android_bridge_is_specific(self):
        with patch("book_sources.validate_url"):
            self.assertTrue(normalize_source(config())["capabilities"]["search"])
            source = config(); source["jsLib"] = "var digest=Packages.java.security.MessageDigest;"
            with self.assertRaisesRegex(SourceError, "Android|Java"):
                normalize_source(source)

    def test_rule_runtime_limits_and_no_host_access(self):
        from source_rules import RuleEngine
        engine = RuleEngine()
        self.assertEqual(engine.value('{"a":[{"name":"ok"}]}', '$.a[*].name'), "ok")
        self.assertEqual(engine.value('<div><b>ok</b></div>', '@XPath://b/text()'), "ok")
        self.assertEqual(engine.value('{"n":3}', '@js:JSON.parse(result).n*2'), "6")
        self.assertEqual(engine.value('', '@js:true'), "true")
        self.assertEqual(engine.value('', '@js:[typeof process,typeof require,typeof Packages].join(",")'), "undefined,undefined,undefined")
        with self.assertRaises(SourceError): engine.value('', '@js:while(true){}')
        with self.assertRaises(SourceError): engine.value('', '@js:new Array(100000000).fill("x")')
        with self.assertRaises(SourceError): engine.value('', '@js:throw new Error("rule failed")')

    def test_jsonpath_filter_and_js_chaining(self):
        from source_rules import RuleEngine
        engine = RuleEngine()
        self.assertEqual(engine.value('{"books":[{"n":1,"t":"yes"},{"n":0,"t":"no"}]}', '$.books[?(@.n == 1)].t'), 'yes')
        self.assertEqual(engine.value('{"n":"name"}', '$.n@js:result.toUpperCase()'), 'NAME')
        self.assertEqual(engine.value('<div><p>A</p><p>B</p></div>', 'p@text##A##Z'), 'Z\nB')

    def test_invalid_rules_rejected_before_enable_and_import_needs_no_network(self):
        with patch("book_sources.socket.getaddrinfo", side_effect=AssertionError("import must be offline")):
            self.assertTrue(normalize_source(config())["capabilities"]["search"])
        for rule in ['@XPath://[', '$.[', '@js:var = ;']:
            source = config(); source["ruleContent"]["content"] = rule
            with self.assertRaises(SourceError): normalize_source(source)

    def test_js_url_expression_and_post_search(self):
        from source_rules import RuleEngine
        engine = RuleEngine()
        self.assertEqual(engine.render_url('/search?q={{encodeURIComponent(key)}}&p={{page+1}}', 'A B', 1), '/search?q=A%20B&p=2')
        source = config(); source["searchUrl"] = '/search,{"method":"POST","body":"q={{key}}","headers":{"Content-Type":"application/x-www-form-urlencoded"}}'
        with patch("book_sources.fetch", return_value=json.dumps({"books": [{"name": "Novel", "url": "/book", "author": "Writer"}]})) as fetcher, patch("book_sources.validate_url"):
            provider = CssSource("fixture", normalize_source(source))
            self.assertEqual(provider.search("Novel")[0]["title"], "Novel")
            self.assertEqual(fetcher.call_args.kwargs["method"], "POST")
            self.assertEqual(fetcher.call_args.kwargs["body"], "q=Novel")

    def test_enabled_state_persists_and_controls_search_provider(self):
        from book_library import BookLibrary
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"):
            library = BookLibrary(temp)
            result = library.add_sources([config()])
            identifier = result["accepted"][0]["id"]
            self.assertIsInstance(library.provider(identifier), CssSource)
            library.set_source_enabled(identifier, False)
            restarted = BookLibrary(temp)
            self.assertFalse(restarted.sources()[identifier]["enabled"])
            with self.assertRaises(SourceError): restarted.provider(identifier)
            restarted.set_source_enabled(identifier, True)
            self.assertTrue(BookLibrary(temp).sources()[identifier]["enabled"])
            self.assertIsInstance(BookLibrary(temp).provider(identifier), CssSource)

    def test_javascript_cannot_fetch_network_or_read_host_files(self):
        from source_rules import RuleEngine
        engine = RuleEngine()
        for code in ['fetch("http://127.0.0.1")', 'require("fs").readFileSync("x")', 'java.ajax("http://127.0.0.1")']:
            with self.assertRaises(SourceError): engine.value('', '@js:' + code)
        from book_sources import validate_url, safe_headers
        with self.assertRaises(SourceError): validate_url('https://other.example/book', 'example.com')
        with self.assertRaises(SourceError): safe_headers({'Host': 'localhost'})
        with self.assertRaises(SourceError): safe_headers({'User-Agent': 'test\r\nInjected: true'})

    def test_pagination_loop_cannot_save_partial_book(self):
        source = config(); source["ruleBookInfo"] = {}
        pages = {"https://example.com/book": '<ul id="chapters"><li><a href="/one">One</a></li></ul><a href="/book">下一页</a>'}
        with patch("book_sources.validate_url"), patch("book_sources.fetch", side_effect=lambda url, *_a, **_k: pages[url]):
            provider = CssSource("fixture", normalize_source(source))
            with self.assertRaises(SourceError): provider.download("https://example.com/book", lambda *_: None, lambda: False)

if __name__ == "__main__": unittest.main()
