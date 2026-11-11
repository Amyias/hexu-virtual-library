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


class AutoDisableTests(unittest.TestCase):
    def test_repeated_failures_disable_and_reenable_clears_the_streak(self):
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"):
            library = BookLibrary(temp)
            library.set_setting("auto_disable_after", "3")
            library.add_sources([legado_source()])
            source_id = next(iter(library.sources()))
            for _ in range(2):
                library.record_health(source_id, False, 50, "书源返回 HTTP 503，请稍后重试或换源")
            self.assertTrue(library.sources()[source_id]["enabled"])
            library.record_health(source_id, False, 50, "书源返回 HTTP 503，请稍后重试或换源")
            config = library.sources()[source_id]
            self.assertFalse(config["enabled"])
            self.assertTrue(config["auto_disabled"])
            self.assertIn("503", config["auto_disabled_reason"])
            listed = next(item for item in library.list_sources() if item["id"] == source_id)
            self.assertTrue(listed["auto_disabled"])
            library.set_source_enabled(source_id, True)
            self.assertTrue(library.sources()[source_id]["enabled"])
            self.assertFalse(library.sources()[source_id].get("auto_disabled"))
            self.assertEqual(library.health_map()[source_id]["consecutive_fail"], 0)

    def test_policy_errors_are_not_counted_and_no_builtin_source_remains(self):
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"):
            library = BookLibrary(temp)
            library.set_setting("auto_disable_after", "2")
            library.add_sources([legado_source()])
            source_id = next(iter(library.sources()))
            for _ in range(6):
                library.record_health(source_id, False, 1, "书源不能访问本机、内网或保留地址")
            self.assertTrue(library.sources()[source_id]["enabled"])
            # 旧的内置小说站已经下线，列表里不该再有 builtin 项。
            self.assertEqual([item for item in library.list_sources() if item.get("builtin")], [])

    def test_threshold_zero_turns_the_feature_off(self):
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"):
            library = BookLibrary(temp)
            library.set_setting("auto_disable_after", "0")
            library.add_sources([legado_source()])
            source_id = next(iter(library.sources()))
            for _ in range(9):
                library.record_health(source_id, False, 1, "书源返回 HTTP 503")
            self.assertTrue(library.sources()[source_id]["enabled"])


class OnlineSearchTests(unittest.TestCase):
    def test_manual_search_does_not_stop_at_an_exact_local_hit(self):
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"):
            library = BookLibrary(temp)
            library.save({"title": "三体", "author": "刘慈欣", "source_id": "local", "source_key": "k1",
                          "source": "本地导入", "source_url": "", "license": "x",
                          "chapters": [{"title": "第一章", "text": "正文" * 40}]})
            provider = FakeProvider("src", items=[{"title": "三体（全集）", "author": "刘慈欣",
                                                   "source_id": "src", "source_source": "src", "source_key": "u1"}])
            library.search_providers = lambda source_id="all": ([provider], [])
            # 语音自动找书：本地精确命中就返回，不联网
            offline = library.search("三体")
            self.assertEqual(len(offline["local"]), 1)
            self.assertEqual(offline["results"], [])
            # 手打搜索：仍然要去搜书源
            online = library.search("三体", online=True)
            self.assertEqual(len(online["local"]), 1)
            self.assertEqual(len(online["results"]), 1)
            self.assertEqual(online["groups"][0]["title"], "三体（全集）")


class DefaultSourceTests(unittest.TestCase):
    def test_first_run_seeds_bundled_sources_and_a_default_subscription(self):
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"), \
                patch("book_library.validate_url"):
            library = BookLibrary(temp)
            self.assertEqual(library.sources(), {})
            seeded = library.ensure_default_sources()
            self.assertGreaterEqual(seeded, 15, seeded)
            self.assertEqual(len(library.sources()), seeded)
            self.assertTrue(all(config["enabled"] for config in library.sources().values()))
            self.assertEqual(library.setting("allow_fake_ip"), "1")
            subscriptions = library.subscriptions()
            self.assertEqual(len(subscriptions), 1)
            self.assertIn("jsdelivr", subscriptions[0]["url"])
            # 第二次启动不再重复灌
            self.assertEqual(library.ensure_default_sources(), 0)
            self.assertEqual(len(library.sources()), seeded)

    def test_a_library_that_already_has_sources_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"):
            library = BookLibrary(temp)
            library.add_sources([legado_source()])
            self.assertEqual(library.ensure_default_sources(), 0)
            self.assertEqual(len(library.sources()), 1)


class SubscriptionTests(unittest.TestCase):
    def payload(self, *sources):
        return json.dumps(list(sources), ensure_ascii=False)

    def test_subscription_syncs_adds_and_removes_only_its_own_sources(self):
        first = legado_source()
        second = legado_source(bookSourceUrl="https://second.example.org", bookSourceName="Second")
        manual = legado_source(bookSourceUrl="https://manual.example.net", bookSourceName="Manual")
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            with patch("book_sources.validate_url"), patch("book_library.validate_url"),                     patch("book_library.fetch", return_value=self.payload(first, second)):
                library.add_sources([manual])
                subscription = library.add_subscription("https://example.com/list.json", "测试订阅")
            self.assertEqual(subscription["status"], "ok")
            self.assertEqual(subscription["imported"], 2)
            self.assertEqual(len(library.sources()), 3)
            self.assertEqual(library.subscriptions()[0]["sources"], 2)

            with patch("book_sources.validate_url"), patch("book_library.validate_url"),                     patch("book_library.fetch", return_value=self.payload(first)):
                result = library.sync_subscription(subscription["id"])
            self.assertEqual(result["imported"], 1)
            self.assertEqual(result["removed"], 1)
            self.assertIn("Second", result["removed_names"])
            names = sorted(item["name"] for item in library.sources().values())
            self.assertEqual(names, ["Legado fixture", "Manual"])

            with patch("book_sources.validate_url"), patch("book_library.validate_url"),                     patch("book_library.fetch", return_value=self.payload(second)):
                library.update_subscription(subscription["id"], enabled=False)
                self.assertFalse(library.subscriptions()[0]["enabled"])
                library.update_subscription(subscription["id"], sync=True)
                self.assertEqual(len(library.sources()), 2)
                removed = library.update_subscription(subscription["id"], delete=True)
            self.assertTrue(removed["deleted"])
            self.assertEqual(removed["removed"], 1)
            self.assertEqual([item["name"] for item in library.sources().values()], ["Manual"])

    def test_failed_sync_keeps_existing_sources_and_records_the_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            with patch("book_sources.validate_url"), patch("book_library.validate_url"),                     patch("book_library.fetch", return_value=self.payload(legado_source())):
                subscription = library.add_subscription("https://example.com/list.json")
            with patch("book_sources.validate_url"), patch("book_library.validate_url"),                     patch("book_library.fetch", side_effect=SourceError("书源返回 HTTP 503，请稍后重试或换源")):
                result = library.sync_subscription(subscription["id"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(library.sources()), 1)
            record = library.subscriptions()[0]
            self.assertEqual(record["last_status"], "failed")
            self.assertIn("503", record["last_message"])


class FakeIpTests(unittest.TestCase):
    def setUp(self):
        from book_sources import set_fake_ip_allowed
        set_fake_ip_allowed(False)
        self.addCleanup(set_fake_ip_allowed, False)

    def test_fake_ip_exception_is_narrow_and_opt_in(self):
        from book_sources import set_fake_ip_allowed, validate_url
        proxy = [(2, 1, 6, "", ("198.18.0.154", 0))]
        with patch("book_sources.socket.getaddrinfo", return_value=proxy):
            with self.assertRaises(SourceError):
                validate_url("https://example.com/x", "example.com")
            set_fake_ip_allowed(True)
            self.assertEqual(validate_url("https://example.com/x", "example.com"), "https://example.com/x")
        private = [(2, 1, 6, "", ("192.168.1.9", 0))]
        with patch("book_sources.socket.getaddrinfo", return_value=private):
            set_fake_ip_allowed(True)
            with self.assertRaises(SourceError):
                validate_url("https://example.com/x", "example.com")

    def test_fake_ip_setting_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            self.assertFalse(library.allow_fake_ip())
            library.set_setting("allow_fake_ip", "1")
            self.assertTrue(library.allow_fake_ip())
            self.assertTrue(BookLibrary(temp).allow_fake_ip())


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
