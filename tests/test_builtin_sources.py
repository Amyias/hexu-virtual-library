"""Self-authored site-shaped fixtures; tests never contact a remote book site."""
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
from book_library import BookLibrary, import_document
from book_sources import CssSource, SourceError, fetch
from builtin_book_sources import BuiltinNovelSource


class BuiltinSourceTests(unittest.TestCase):
    def test_default_sources_replace_wiki_but_existing_books_stay_local(self):
        with tempfile.TemporaryDirectory() as directory:
            library = BookLibrary(directory)
            self.assertEqual([s["id"] for s in library.list_sources()], ["tianya", "shubao"])
            with patch.object(BuiltinNovelSource, "search", return_value=[]) as search:
                library.search("Fixture")
                self.assertEqual(search.call_count, 2)
            document = import_document("old.txt", b"Previously downloaded real body. " * 8, "Old book")
            document.update(source_id="wikisource", source_key="Old book")
            book = library.save(document)
            with patch.object(library, "provider", side_effect=AssertionError("local match must stay offline")):
                self.assertEqual(library.search("Old book")["local"][0]["id"], book["id"])
            self.assertIn("Previously downloaded", library.get(book["id"])["chapters"][0]["body"])

    def test_tianya_post_and_shubao_path_search_use_site_result_cards(self):
        pages = [
            '<article class="themebetter-ent-loop-item"><h2><a href="/cn/123/">Fixture</a></h2></article>',
            '<div class="novel-list"><div class="novel-item"><h2 class="novel-title"><a href="/novel/abc/">Fixture</a></h2><div class="novel-meta"><div class="meta-item"><span class="meta-value">Writer</span></div></div></div></div>',
        ]
        with patch("builtin_book_sources.fetch", side_effect=pages) as request, patch("builtin_book_sources.time.sleep"):
            tianya = BuiltinNovelSource("tianya").search("A & B")[0]
            shubao = BuiltinNovelSource("shubao").search("A & B")[0]
        first, second = request.call_args_list
        self.assertEqual(first.kwargs["method"], "POST")
        self.assertIn("keyboard=A%20%26%20B", first.kwargs["body"])
        self.assertEqual(second.args[0], "https://cn.shubaoc.com/search/A%20%26%20B/")
        self.assertEqual(tianya["source_key"], "https://tianyashuku.net/cn/123/")
        self.assertEqual(shubao["author"], "Writer")
        self.assertTrue(first.kwargs["https_only"])

    def test_paginated_catalogue_downloads_all_chapters_once_then_persists(self):
        base = "https://cn.shubaoc.com/novel/abc/"
        pages = {
            base: '<h1>《Fixture》</h1><li class="novel-meta-item"><a title="Writer作品集">Writer</a></li><ul id="chapterList"><li><a href="/novel/abc/a.html">One</a></li></ul><div class="pagination-controls"><a href="/novel/abc/1/">下一页</a></div>',
            base + "1/": '<ul id="chapterList"><li><a href="/novel/abc/a.html">One</a></li><li><a href="/novel/abc/b.html">Two</a></li></ul>',
            base + "a.html": '<nav>Not body</nav><div class="chapter-content"><p>' + "First real paragraph. " * 8 + '</p><script>not_body()</script></div><a href="/novel/abc/b.html">下一章</a>',
            base + "b.html": '<div class="chapter-content"><p>' + "Second real paragraph. " * 8 + '</p></div>',
        }
        with tempfile.TemporaryDirectory() as directory, patch("builtin_book_sources.fetch", side_effect=lambda url, *_a, **_k: pages[url]) as request, patch("builtin_book_sources.time.sleep"):
            library = BookLibrary(directory)
            job = library.start_download({"source_id": "shubao", "source_key": base, "title": "Fixture"})
            for _ in range(200):
                job = library.job(job["id"])
                if job["state"] not in {"queued", "downloading"}:
                    break
                threading.Event().wait(0.01)
            self.assertEqual(job["state"], "completed", job)
            saved = BookLibrary(directory).get(job["book"]["id"])
            self.assertEqual(saved["title"], "Fixture")
            self.assertEqual(saved["author"], "Writer")
            self.assertEqual([c["title"] for c in saved["chapters"]], ["One", "Two"])
            self.assertNotIn("not_body", saved["chapters"][0]["body"])
            self.assertNotIn("Not body", saved["chapters"][0]["body"])
            self.assertEqual([c.args[0] for c in request.call_args_list], list(pages))

    def test_tianya_info_catalogue_and_body_exclude_recommendations(self):
        base = "https://tianyashuku.net/cn/123/"
        pages = {
            base: '<meta property="og:novel:book_name" content="Fixture"><meta property="og:novel:author" content="Writer"><div id="list"><dl><dd><a href="/cn/123/1.html">First</a></dd></dl></div><aside><a href="/cn/999/">Recommended</a></aside>',
            base + "1.html": '<h1>Heading</h1><div class="m-article-text">' + "Body paragraph. " * 8 + '</div><nav>Next chapter</nav>',
        }
        with patch("builtin_book_sources.fetch", side_effect=lambda url, *_a, **_k: pages[url]), patch("builtin_book_sources.time.sleep"):
            result = BuiltinNovelSource("tianya").download(base, lambda *_: None, lambda: False)
        self.assertEqual((result["title"], result["author"]), ("Fixture", "Writer"))
        self.assertEqual(len(result["chapters"]), 1)
        self.assertNotIn("Next chapter", result["chapters"][0]["text"])

    def test_catalogue_loop_missing_body_and_cancel_never_save_partial_book(self):
        base = "https://cn.shubaoc.com/novel/abc/"
        initial = '<h1>Fixture</h1><ul id="chapterList"><a href="/novel/abc/a.html">One</a></ul>'
        for pages, cancelled in [
            ({base: initial + '<div class="pagination-controls"><a href="/novel/abc/">下一页</a></div>'}, False),
            ({base: initial, base + "a.html": '<h1>Access error</h1>'}, False),
            ({base: initial}, True),
        ]:
            with self.subTest(cancelled=cancelled), tempfile.TemporaryDirectory() as directory, patch("builtin_book_sources.fetch", side_effect=lambda url, *_a, **_k: pages[url]), patch("builtin_book_sources.time.sleep"):
                library = BookLibrary(directory)
                with self.assertRaises(SourceError):
                    result = library.provider("shubao").download(base, lambda *_: None, lambda: cancelled)
                    library.save(result)
                self.assertEqual(library.list_books(), [])

    def test_fixed_https_origin_cannot_be_replaced_by_client_urls_or_json(self):
        source = BuiltinNovelSource("shubao")
        for url in ["http://cn.shubaoc.com/novel/abc/", "https://127.0.0.1/novel/abc/", "https://cn.shubaoc.com.evil.example/novel/abc/", "https://cn.shubaoc.com:80/novel/abc/", "https://cn.shubaoc.com/admin", "https://user:pass@cn.shubaoc.com/novel/abc/"]:
            with self.subTest(url=url), self.assertRaises(SourceError):
                source.check_url(url)
        with patch("book_sources.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
            with self.assertRaises(SourceError):
                CssSource("custom", {"name": "Custom", "base_url": "https://cn.shubaoc.com", "trusted": True}).document("https://cn.shubaoc.com/novel/abc/")
        with self.assertRaises(SourceError):
            fetch("http://cn.shubaoc.com/novel/abc/", source.host, trusted=True, https_only=True)

    def test_search_rate_warning_is_not_mistaken_for_no_results(self):
        with patch("builtin_book_sources.fetch", return_value="<title>信息提示</title><p>两次搜索间隔</p>"), patch("builtin_book_sources.time.sleep"):
            with self.assertRaisesRegex(SourceError, "稍后重试"):
                BuiltinNovelSource("tianya").search("Fixture")


if __name__ == "__main__":
    unittest.main()
