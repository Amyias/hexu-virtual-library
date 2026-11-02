"""Bibliographic details: what an EPUB says about itself, and what Open Library adds from its
ISBN. The lookup here is a fixed test value; nothing is contacted."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import book_library

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>三体</dc:title><dc:creator>刘慈欣</dc:creator>
    <dc:identifier>uuid:0f1e2d3c</dc:identifier>
    <dc:identifier>urn:isbn:978-7-5366-9293-0</dc:identifier>
    <dc:subject>科幻</dc:subject><dc:subject>中国当代小说</dc:subject>
    <dc:description>&lt;p&gt;文化大革命如火如荼，&lt;b&gt;军方&lt;/b&gt;探寻外星文明的绝秘计划。&lt;/p&gt;</dc:description>
    <dc:publisher>重庆出版社</dc:publisher><dc:date>2008-01-01</dc:date>
  </metadata>
  <manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""


def epub():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        archive.writestr("OEBPS/content.opf", OPF)
        archive.writestr("OEBPS/c1.xhtml", "<html><body><h1>第一章</h1><p>叶文洁看着父亲。</p></body></html>")
    return buffer.getvalue()


class MetadataTests(unittest.TestCase):
    def test_isbns_are_found_and_checked(self):
        self.assertEqual(book_library.isbn_of("urn:isbn:978-7-5366-9293-0"), "9787536692930")
        self.assertEqual(book_library.isbn_of("ISBN 7536692935"), "7536692935")
        self.assertEqual(book_library.isbn_of("0-306-40615-2"), "0306406152")
        for wrong in ["978-7-5366-9293-1", "uuid:1234", "12345678901234567", ""]:
            self.assertEqual(book_library.isbn_of(wrong), "", wrong)

    def test_an_epub_brings_its_isbn_subjects_and_description(self):
        document = book_library.import_document("santi.epub", epub())
        self.assertEqual(document["isbn"], "9787536692930")
        self.assertEqual(document["subjects"], ["科幻", "中国当代小说"])
        self.assertEqual(document["description"], "文化大革命如火如荼， 军方 探寻外星文明的绝秘计划。")
        self.assertEqual((document["publisher"], document["published"]), ("重庆出版社", "2008-01-01"))
        self.assertNotIn("isbn", book_library.import_document("plain.txt", "第一章\n正文。".encode("utf-8")))

    def test_open_library_fills_only_what_is_missing_and_only_once(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"HEXU_METADATA_LOOKUP": "0"}):
            library = book_library.BookLibrary(directory)
            book = library.save(book_library.import_document("santi.epub", epub()))
            self.assertTrue(book["synopsis"].startswith("文化大革命"), "the description is the synopsis")
            calls = []

            def lookup(isbn):
                calls.append(isbn)
                return {"subjects": ["Science fiction"], "publisher": "Chongqing Press", "pages": 302}

            added = library.enrich(book["id"], lookup=lookup)
            self.assertEqual(added, {"pages": 302}, "the file's own subjects and publisher stay")
            stored = library.get(book["id"], False)
            self.assertEqual((stored["subjects"], stored["publisher"], stored["pages"]), (["科幻", "中国当代小说"], "重庆出版社", 302))
            self.assertEqual(library.enrich(book["id"], lookup=lookup), {})
            self.assertEqual(calls, ["9787536692930"], "looked up once")

    def test_an_unreachable_service_adds_nothing(self):
        def offline(*args, **kwargs):
            raise OSError("no network")

        self.assertEqual(book_library.lookup_isbn("9787536692930", opener=offline), {})

    def test_the_lookup_keeps_whole_subject_names_without_machine_tags(self):
        answer = {"ISBN:9787536692930": {"subjects": [{"name": "Hugo Award Winner"}, {"name": "award:hugo_award=2015"},
                                                      {"name": "x" * 60}], "publishers": [{"name": "Chongqing Press"}],
                                         "publish_date": "2008", "number_of_pages": 302}}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        found = book_library.lookup_isbn("9787536692930", opener=lambda *a, **k: Response(json.dumps(answer).encode()))
        self.assertEqual(found, {"subjects": ["Hugo Award Winner"], "publisher": "Chongqing Press",
                                 "published": "2008", "pages": 302})


if __name__ == "__main__":
    unittest.main()
