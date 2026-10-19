import io
import base64
import http.client
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
from book_library import BookLibrary, handle_request, import_document
from book_sources import CssSource, Document, SourceError, Wikisource, field, normalize_source, select, validate_url


class LocalLibraryTests(unittest.TestCase):
    def test_persistent_import_content_progress_and_stable_shelf_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            raw = ("第一章 相遇\n" + "第一章内容。" * 80 + "\n第二章 归途\n" + "第二章内容。" * 80).encode()
            document = import_document("story.txt", raw, "A local novel", "Author")
            saved = library.save(document)
            self.assertEqual(saved["chapter_count"], 2)
            library.progress(saved["id"], 1, 25)
            restarted = BookLibrary(temp)
            restored = restarted.get(saved["id"])
            self.assertEqual(restored["progress"], {"chapter": 1, "offset": 25})
            self.assertEqual(restored["chapters"][1]["body"], document["chapters"][1]["text"])
            self.assertEqual(restarted.save(document)["slot"], saved["slot"])
            self.assertEqual(len(restarted.list_books()), 1)
            self.assertTrue((pathlib.Path(temp) / (saved["id"] + ".txt")).is_file())
            with self.assertRaises(SourceError):
                restarted.progress(saved["id"], 200, 0)

    def test_empty_or_incomplete_books_do_not_enter_the_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            for chapters in [[], [{"title": "chapter", "text": ""}]]:
                with self.assertRaises(SourceError):
                    library.save({"title": "invalid", "source_id": "test", "source_key": "key", "chapters": chapters})
            self.assertEqual(library.list_books(), [])

    def test_epub_spine_order_and_untrusted_markup_are_plain_text(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("META-INF/container.xml", '<container><rootfile full-path="OEBPS/content.opf"/></container>')
            archive.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><metadata><title>Test EPUB</title><creator>Writer</creator></metadata><manifest><item id="a" href="a.xhtml"/><item id="b" href="b.xhtml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
            archive.writestr("OEBPS/a.xhtml", '<h1>Second</h1><p>safe A</p><script>stolen()</script>')
            archive.writestr("OEBPS/b.xhtml", '<h1>First</h1><p>safe B</p>')
        book = import_document("sample.epub", data.getvalue())
        self.assertEqual([chapter["title"] for chapter in book["chapters"]], ["First", "Second"])
        self.assertNotIn("stolen", book["chapters"][1]["text"])

    def test_css_source_rules_are_data_and_cannot_fetch_private_addresses(self):
        root = Document('<div class="result"><a href="/book">Novel</a></div><script>bad()</script>').root
        result = select(root, "div.result")[0]
        self.assertEqual(field(result, "a@href"), "/book")
        self.assertEqual(field(result, "a@text"), "Novel")
        self.assertEqual(field(result, "@css:a"), "Novel")
        with self.assertRaises(SourceError):
            select(root, "a:has(script)")
        with patch("book_sources.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
            with self.assertRaises(SourceError):
                validate_url("https://example.com", "example.com")
        with self.assertRaises(SourceError):
            normalize_source({"name": "script", "base_url": "https://example.com", "search_url": "@js:steal()", "search": {"items": "a"}, "toc": {"items": "a"}, "content": {"body": "p"}})

    def test_static_source_downloads_complete_chapters_before_saving(self):
        config = {"name": "Fixture", "base_url": "https://example.com", "search_url": "/search?q={{key}}", "search": {"items": ".book", "title": "a@text", "url": "a@href"}, "toc": {"items": ".toc a", "title": "@text", "url": "@href"}, "content": {"body": "#content@text"}}
        pages = {"https://example.com/search?q=Novel": '<div class="book"><a href="/novel">Novel</a></div>',
                 "https://example.com/novel": '<div class="toc"><a href="/one">First</a><a href="/two">Second</a></div>',
                 "https://example.com/one": '<div id="content">' + "First chapter text. " * 100 + '<script>bad()</script></div>',
                 "https://example.com/two": '<div id="content">' + "Second chapter text. " * 100 + '</div>'}
        with tempfile.TemporaryDirectory() as temp, patch("book_sources.validate_url"), patch("book_sources.fetch", side_effect=lambda url, *_args, **_kwargs: pages[url]):
            provider = CssSource("fixture", normalize_source(config))
            candidate = provider.search("Novel")[0]
            library = BookLibrary(temp)
            with patch.object(library, "provider", return_value=provider):
                job = library.start_download(candidate)
                for _ in range(100):
                    status = library.job(job["id"])
                    if status["state"] in {"completed", "failed"}:
                        break
                    time.sleep(.01)
                self.assertEqual(status["state"], "completed", status)
                book = library.get(status["book"]["id"])
                self.assertEqual([item["title"] for item in book["chapters"]], ["First", "Second"])
                self.assertNotIn("bad()", book["chapters"][0]["body"])

    def test_cancellation_and_failed_downloads_never_publish_partial_books(self):
        entered, release = threading.Event(), threading.Event()
        class Provider:
            id = "fixture"
            def download(self, key, report, cancelled):
                entered.set(); release.wait(3)
                if cancelled():
                    raise SourceError("cancelled")
                raise SourceError("chapter two failed")
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            with patch.object(library, "provider", return_value=Provider()):
                candidate = {"source_id": "fixture", "source_key": "one"}
                first = library.start_download(candidate); self.assertTrue(entered.wait(2))
                self.assertEqual(library.start_download(candidate)["id"], first["id"])
                library.job(first["id"], True); release.set()
                for _ in range(100):
                    if library.job(first["id"])["state"] == "cancelled":
                        break
                    time.sleep(.01)
                self.assertEqual(library.job(first["id"])["state"], "cancelled")
                second = library.start_download({**candidate, "source_key": "two"})
                for _ in range(100):
                    if library.job(second["id"])["state"] == "failed":
                        break
                    time.sleep(.01)
                self.assertEqual(library.job(second["id"])["state"], "failed")
            self.assertEqual(library.list_books(), [])
            self.assertEqual(list(pathlib.Path(temp).glob("*.txt")), [])

    def test_cached_alias_search_works_without_any_network_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            doc = import_document("story.txt", b"Local body", "Traditional title", "Author")
            doc["aliases"] = ["spoken title"]
            library.save(doc)
            with patch.object(library, "provider", side_effect=AssertionError("must not access network")):
                result = library.search("spoken title")
            self.assertEqual(len(result["local"]), 1)
            self.assertEqual(result["results"], [])

    def test_single_page_novel_splits_chapter_headings_and_removes_site_header(self):
        markup = '<div id="headerContainer">Next book navigation</div><h2>第一章 相遇</h2><p>' + 'Chapter one content. ' * 20 + '</p><h2>第二章 归途</h2><p>' + 'Chapter two content. ' * 20 + '</p>'
        with patch.object(Wikisource, "api", return_value={"parse": {"title": "Novel", "text": markup, "revid": 42}}):
            book = Wikisource().download("Novel", lambda *_: None, lambda: False)
        self.assertEqual(len(book["chapters"]), 2)
        self.assertNotIn("navigation", str(book["chapters"]))

    def test_http_import_read_progress_and_cross_origin_rejection(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                handle_request(self)
            do_POST = do_GET
            def log_message(self, *_):
                pass
        with tempfile.TemporaryDirectory() as temp:
            library = BookLibrary(temp)
            with patch("book_library._instance", library):
                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                def call(path, body=None, origin=None):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    headers = {"Content-Type": "application/json"}
                    if origin:
                        headers["Origin"] = origin
                    connection.request("GET" if body is None else "POST", "/library/" + path, None if body is None else json.dumps(body).encode(), headers)
                    response = connection.getresponse(); status = response.status; data = json.loads(response.read()); connection.close()
                    return status, data
                try:
                    self.assertEqual(call("ready")[0], 200)
                    self.assertEqual(call("url", {"url": "https://example.com/book"})[0], 404)
                    payload = {"filename": "story.txt", "title": "HTTP Novel", "data": base64.b64encode(b"Real text " * 100).decode()}
                    self.assertEqual(call("import", payload, "https://another-site.example")[0], 403)
                    self.assertEqual(library.list_books(), [])
                    status, saved = call("import", payload); self.assertEqual(status, 200)
                    self.assertEqual(call("books")[1]["books"][0]["id"], saved["id"])
                    self.assertEqual(call("progress/" + saved["id"], {"chapter": 0, "offset": 40})[0], 200)
                    restored = call("books/" + saved["id"])[1]
                    self.assertEqual(restored["progress"]["offset"], 40)
                    self.assertEqual(restored["chapters"][0]["body"], "Real text " * 99 + "Real text")
                finally:
                    server.shutdown(); server.server_close(); thread.join(2)


if __name__ == "__main__":
    unittest.main()
