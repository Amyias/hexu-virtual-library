"""Public directory lookup and download fixtures; no protected site search or real network."""
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import wyshu_source
from wyshu_source import WyshuSource, keys
from source_rules import SourceError


class WyshuTests(unittest.TestCase):
    base = "https://www.wyshu.com/"
    sitemap = base + "sitemap/bookname_1.xml"
    book = base + "xd/ceshishu/"

    def setUp(self):
        self.cache = patch.object(wyshu_source, "_index", (0.0, ()))
        self.cache.start()
        self.addCleanup(self.cache.stop)

    def pages(self):
        return {
            self.sitemap: '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>' + self.book + '</loc></url></urlset>',
            self.book: '<meta property="og:novel:book_name" content="测试书"><meta property="og:novel:author" content="测试作者"><ol class="list-featured"><li><h3><a href="123.html">第一章</a></h3></li></ol>',
            self.book + '123.html': '<nav>not body</nav><article class="article-post">' + '这是独立编写的正文。' * 20 + '<script>not_body()</script></article>',
        }

    def test_search_checks_actual_title_and_author_and_reuses_public_index(self):
        pages = self.pages()
        with patch.object(WyshuSource, "document", side_effect=lambda url: pages[url]) as request:
            result = WyshuSource().search("测试书")
            self.assertEqual(result[0]["title"], "测试书")
            self.assertEqual(result[0]["author"], "测试作者")
            self.assertEqual(WyshuSource().search("ceshishu")[0]["source_key"], self.book)
        self.assertEqual(sum(c.args[0] == self.sitemap for c in request.call_args_list), 1)
        self.assertTrue(all('/e/search/' not in c.args[0] for c in request.call_args_list))
        pages[self.book] = pages[self.book].replace('content="测试书"', 'content="同音的其他书"')
        with patch.object(WyshuSource, "document", side_effect=lambda url: pages[url]), self.assertRaisesRegex(SourceError, "未命中"):
            WyshuSource().search("测试书")

    def test_directory_template_downloads_actual_body_without_navigation_or_script(self):
        pages = self.pages()
        with patch.object(WyshuSource, "document", side_effect=lambda url: pages[url]):
            book = WyshuSource().download(self.book, lambda *_: None, lambda: False)
        self.assertEqual((book["title"], book["author"]), ("测试书", "测试作者"))
        self.assertEqual(len(book["chapters"]), 1)
        self.assertIn('独立编写', book["chapters"][0]["text"])
        self.assertNotIn('not_body', book["chapters"][0]["text"])
        self.assertNotIn('not body', book["chapters"][0]["text"])

    def test_untrusted_sitemap_challenge_and_foreign_origins_fail_closed(self):
        for markup in ['<!DOCTYPE x><urlset/>', '<html>正在进行安全验证</html>', '<urlset><url><loc>https://evil.example/xd/book/</loc></url></urlset>', '<urlset><url><loc>http://www.wyshu.com/xd/book/</loc></url></urlset>']:
            with self.subTest(markup=markup), patch.object(WyshuSource, "document", return_value=markup), self.assertRaises(SourceError):
                WyshuSource().index()
        for url in [self.base+'e/search/index.php', self.base+'admin', self.book+'../', self.base+'xd/book/?unexpected=1']:
            with self.assertRaises(SourceError):
                WyshuSource().check_url(url)

    def test_mixed_language_urls_are_encoded_and_heteronyms_are_bounded(self):
        url = self.base + 'ds/caomeiSummer　Night/'
        with patch.object(WyshuSource, "document", return_value='<urlset><url><loc>'+url+'</loc></url></urlset>'):
            index = WyshuSource().index()
        self.assertIn('%E3%80%80', index[0])
        self.assertTrue(index[0].isascii())
        self.assertLessEqual(len(keys('重行长乐' * 40)), 66)
        self.assertIn('santi', keys('三体'))


if __name__ == '__main__':
    unittest.main()
