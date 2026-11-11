"""Legado 兼容层、书源体检与聚合检索的回归测试；不联网，也不碰真实书库。"""
import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from aggregate_search import SearchJobs, group_candidates
from book_library import BookLibrary
from book_sources import SourceError, normalize_source
from legado_host import LegadoHost
from source_rules import RuleEngine


class LegadoRuleTests(unittest.TestCase):
    def setUp(self):
        self.engine = RuleEngine()

    def test_class_tag_chain_with_indexes(self):
        markup = '<div class="newbox"><ul><li><a href="/1">A</a></li><li><a href="/2">B</a></li></ul></div>'
        self.assertEqual(self.engine.value(markup, "class.newbox.0@tag.ul.0@tag.li.1@tag.a@text"), "B")
        self.assertEqual(self.engine.value(markup, "class.newbox@tag.ul@tag.li[0:1]@tag.a.0@href"), "/1")
        self.assertEqual(self.engine.value(markup, "class.newbox@tag.ul@tag.li!0@tag.a@text"), "B")
        self.assertEqual(self.engine.value(markup, "class.newbox@tag.ul@tag.li.-1@tag.a@text"), "B")

    def test_plain_css_and_tail_index(self):
        markup = ('<div class="face-info"><span>作者：张三</span><span>分类：科幻</span></div>'
                  '<div id="pages"><a class="gr" href="/p2">下一页</a><a class="gr" href="#">#</a></div>')
        self.assertEqual(self.engine.value(markup, ".face-info span.0@text##.*："), "张三")
        self.assertEqual(self.engine.value(markup, "#pages .gr:not([href='#'])@href"), "/p2")

    def test_text_selector_and_children(self):
        markup = '<div class="full"><span>skip</span><ul><li><a href="/1">One</a></li></ul></div>'
        self.assertEqual(self.engine.value(markup, "text.下一页@href"), "")
        self.assertEqual(self.engine.value('<a href="/n">下一页</a>', "text.下一页@href"), "/n")
        self.assertEqual(self.engine.value(markup, "class.full@children[1]@tag.a@text"), "One")

    def test_brace_expansion_and_nested_rule(self):
        data = json.dumps({"book_id": 42, "channel": "科幻", "data": ["d1", "d2"]})
        self.assertEqual(self.engine.value(data, "{{$.book_id}}"), "42")
        self.assertEqual(self.engine.value(data, "/novels/api/book/{{$.book_id}}"), "/novels/api/book/42")
        self.assertEqual(self.engine.value(data, "{{@@$.channel}}"), "科幻")
        self.assertEqual(self.engine.value(data, "{{$.channel}}/{{$.book_id}}"), "科幻/42")
        self.assertEqual(self.engine.value(data, "data[1]"), "d2")

    def test_regex_rule_with_groups(self):
        raw = ':"sS":1,"cN":"第一章","id":9}'
        rule = ':"sS":(\d),.*?"cN":"(.*?)","id":(\d+)'
        matches = self.engine.items(raw, rule)
        self.assertEqual(len(matches), 1)
        self.assertEqual(self.engine.value(matches, "$2"), "第一章")

    def test_java_helpers_and_variables(self):
        self.assertEqual(self.engine.value("abc", "@js:java.base64Encode(result)"), "YWJj")
        self.assertEqual(self.engine.value("YWJj", "@js:java.base64Decode(result)"), "abc")
        self.assertEqual(self.engine.value("5b", "@js:java.hexDecodeToString(result)"), "[")
        self.assertEqual(self.engine.value("", "@js:java.put('k','v') + java.get('k')"), "v")

    def test_host_requests_are_bounded_and_same_origin(self):
        seen = []

        def request(url, **options):
            seen.append(url)
            return "<html>ok</html>"

        engine = RuleEngine(host=LegadoHost(request=request, base_url="https://example.com"))
        self.assertEqual(engine.value("", "@js:java.ajax('/page')"), "<html>ok</html>")
        self.assertEqual(seen, ["https://example.com/page"])
        with self.assertRaises(SourceError):
            engine.value("", "@js:java.ajax('/a');java.ajax('/b');java.ajax('/c');java.ajax('/d');java.ajax('/e')")

    def test_without_a_request_callback_ajax_is_refused(self):
        with self.assertRaises(SourceError):
            self.engine.value("", "@js:java.ajax('/page')")
        self.assertEqual(self.engine.value("", "@js:typeof java.put"), "function")
        with self.assertRaises(SourceError):
            self.engine.value("", "@js:typeof process.length ? 'leak' : java.ajax('/x')")


def legado_source(**overrides):
    source = {"bookSourceName": "Legado fixture", "bookSourceUrl": "https://example.com",
              "searchUrl": "/search?q={{key}}",
              "ruleSearch": {"bookList": "class.item.0", "name": "tag.a.0@text",
                             "bookUrl": "tag.a.0@href", "author": "class.author.0@text##作者："},
              "ruleBookInfo": {"name": "h1@text", "tocUrl": "#toc@href"},
              "ruleToc": {"chapterList": "id.list@tag.a", "chapterName": "ownText",
                          "chapterUrl": "href", "nextTocUrl": "text.下一页@href"},
              "ruleContent": {"content": ".body@text"}}
    source.update(overrides)
    return source


class SourceImportTests(unittest.TestCase):
    def test_legado_source_using_java_ajax_is_accepted_and_marked(self):
        source = legado_source()
        source["ruleContent"]["content"] = ".body@text@js:java.ajax(baseUrl + '/api/' + result)"
        with patch("book_sources.validate_url"):
            config = normalize_source(source)
        self.assertTrue(config["capabilities"]["search"])
        self.assertTrue(config["capabilities"]["java_ajax"])

    def test_header_string_and_unknown_headers_are_tolerated(self):
        source = legado_source()
        source["header"] = json.dumps({"User-Agent": "HexuTest", "Host": "example.com"})
        with patch("book_sources.validate_url"):
            config = normalize_source(source)
        self.assertEqual(config["headers"], {"User-Agent": "HexuTest"})
        self.assertIn("Host", config["capabilities"].get("header_note", ""))

    def test_android_only_source_is_still_rejected_with_a_reason(self):
        source = legado_source()
        source["ruleContent"]["content"] = "<js>Packages.java.lang.System.currentTimeMillis()</js>"
        with patch("book_sources.validate_url"), self.assertRaisesRegex(SourceError, "Android"):
            normalize_source(source)

    def test_import_from_url_reads_public_json(self):
        payload = json.dumps([legado_source()])
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"), \
                patch("book_library.validate_url"), patch("book_library.fetch", return_value=payload):
            library = BookLibrary(temp)
            result = library.import_sources_from_url("https://example.com/sources.json")
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["name"], "Legado fixture")


class FakeProvider:
    def __init__(self, identifier, items=None, error=None, delay=0.0, document=None):
        self.id, self.name = identifier, identifier
        self.items, self.error, self.delay, self.document = items or [], error, delay, document
        self.host = "example.com"

    def search(self, query):
        time.sleep(self.delay)
        if self.error:
            raise SourceError(self.error)
        return self.items

    def download(self, key, report, cancelled):
        if self.error:
            raise SourceError(self.error)
        report(0, 1, "章节")
        return dict(self.document or {})


class AggregateSearchTests(unittest.TestCase):
    def test_same_book_from_several_sources_merges_and_ranks_first(self):
        candidates = [
            {"title": "三体全集", "author": "刘慈欣", "source_id": "slow", "source": "慢源", "source_key": "a"},
            {"title": "三体", "author": "刘慈欣", "source_id": "fast", "source": "快源", "source_key": "b", "exact": True},
            {"title": "三体", "author": "刘慈欣", "source_id": "good", "source": "好源", "source_key": "c"},
            {"title": "九转霸体", "author": "别人", "source_id": "good", "source": "好源", "source_key": "d"},
        ]
        health = {"slow": {"ok": 0, "fail": 3, "consecutive_fail": 3}}
        groups = group_candidates(candidates, "三体", health)
        self.assertEqual(groups[0]["title"], "三体")
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(groups[0]["best"]["source_id"], "fast")
        self.assertEqual(groups[-1]["title"], "九转霸体")

    def test_run_search_keeps_source_order_and_records_health(self):
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            first = FakeProvider("first", items=[{"title": "A", "source_id": "first", "source_key": "1"}])
            second = FakeProvider("second", error="书源返回 HTTP 503，请稍后重试或换源")
            results, errors = library.run_search("A", [first, second], timeout=5)
            health = library.health_map()
        self.assertEqual([item["title"] for item in results], ["A"])
        self.assertEqual(errors[0]["source_id"], "second")
        self.assertEqual(health["first"]["ok"], 1)
        self.assertEqual(health["second"]["consecutive_fail"], 1)

    def test_slow_source_times_out_without_blocking_the_rest(self):
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            fast = FakeProvider("fast", items=[{"title": "A", "source_id": "fast", "source_key": "1"}])
            slow = FakeProvider("slow", items=[{"title": "B", "source_id": "slow", "source_key": "2"}], delay=3)
            started = time.monotonic()
            results, errors = library.run_search("A", [fast, slow], timeout=1)
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.5)
        self.assertEqual([item["title"] for item in results], ["A"])
        self.assertIn("超时", errors[0]["message"])

    def test_search_job_carries_every_provider_and_finishes(self):
        """任务接口必须把 search_providers 的 (列表, 错误) 拆开，否则 total 变成 2、停在 searching。"""
        providers = [FakeProvider("fast", items=[{"title": "三体", "author": "刘慈欣", "source_id": "fast", "source_key": "1"}]),
                     FakeProvider("broken", error="书源返回 HTTP 503，请稍后重试或换源")]

        class Stub:
            def __init__(self):
                self.health = {}

            def search_providers(self, source_id="all"):
                return providers, [{"source_id": "gone", "message": "书源不存在或已被移除"}]

            def record_health(self, identifier, ok, latency_ms=0, message=""):
                self.health[identifier] = (ok, message)

            def health_map(self):
                return {}

        jobs = SearchJobs(Stub())
        job = jobs.start("三体")
        self.assertEqual(job["total"], 2, job)
        self.assertEqual([item["source_id"] for item in job["errors"]], ["gone"])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = jobs.get(job["id"])
            if job["state"] != "searching":
                break
            time.sleep(0.05)
        self.assertEqual(job["state"], "completed", job)
        self.assertEqual(job["done"], 2)
        self.assertEqual(job["groups"][0]["title"], "三体")
        self.assertIn("broken", [error["source_id"] for error in job["errors"]])

    def test_probe_reports_latency_and_keeps_health(self):
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            library.provider = lambda identifier: FakeProvider(identifier, items=[{"title": "三体", "source_id": "x", "source_key": "1"}])
            result = library.probe_source("x")
            health = library.health_map()
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(health["x"]["ok"], 1)

    def test_download_fails_over_to_the_next_source(self):
        document = {"title": "三体", "author": "刘慈欣", "chapters": [{"title": "第一章", "text": "正文" * 30}],
                    "source_id": "backup", "source_key": "https://example.com/2", "source": "备份源", "source_url": "", "license": "公开"}
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            first = FakeProvider("primary", error="目录为空，不会把目录页当作完整书籍保存")
            second = FakeProvider("backup", document=document)
            library.provider = lambda identifier: {"primary": first, "backup": second}[identifier]
            job = library.start_download({"source_id": "primary", "source_key": "https://example.com/1",
                                          "title": "三体", "author": "刘慈欣",
                                          "alternates": [{"source_id": "backup", "source_key": "https://example.com/2"}]})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                job = library.job(job["id"])
                if job["state"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            health = library.health_map()
            books = library.list_books()
        self.assertEqual(job["state"], "completed", job)
        self.assertEqual(job["source_id"], "backup")
        self.assertEqual([book["title"] for book in books], ["三体"])
        self.assertEqual(health["primary"]["fail"], 1)


if __name__ == "__main__":
    unittest.main()
