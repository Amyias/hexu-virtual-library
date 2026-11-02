import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import book_library
import book_text_search as search_module
import llm_chat

# Obviously invalid test value; never read user configuration/environment or contact a provider.
CONFIG = {"HEXU_LLM_BASE_URL": "https://compatible.example/v1", "HEXU_LLM_MODEL": "test-model",
          "HEXU_LLM_API_KEY": "invalid-test-credential"}
CHAPTERS = [
    {"title": "第一章 疯狂年代", "text": "叶文洁看着父亲在批斗会上倒下，她的眼神从此冷了下来。" * 8},
    {"title": "红岸之一", "text": "叶文洁被带到红岸基地，那里有一座巨大的天线，指向天空。" * 8
     + "史强是一名警察，粗中有细，总能看穿别人的心思。" * 4},
    {"title": "科学边界", "text": "汪淼发现倒计时出现在他拍的每一张照片上，数字一天天减少。" * 10},
]


class TextSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = book_library.BookLibrary(self.temp.name)
        self.book = self.library.save({"title": "三体", "author": "刘慈欣", "source_id": "local",
                                       "source_key": "a", "chapters": CHAPTERS})
        self.search = search_module.BookTextSearch(self.library)

    def test_chinese_is_indexed_as_character_pairs_and_questions_lose_filler(self):
        self.assertEqual(search_module.grams("叶文洁 Hello"), "叶文 文洁 hello")
        self.assertEqual(search_module.grams("史强是谁？", query=True), "史强 强是")
        self.assertEqual(search_module.grams("是什么", query=True), "", "filler alone matches nothing")
        pieces = list(search_module.chunks("一句话说完。" * 120))
        self.assertTrue(all(piece.startswith("一句话") for piece in pieces), "passages start a sentence")
        self.assertTrue(all(len(piece) <= search_module.PASSAGE for piece in pieces))
        self.assertTrue(all(piece.endswith("。") for piece in pieces[:-1]), "passages end at a sentence end")
        self.assertGreater(len("".join(pieces)), len("一句话说完。" * 120), "neighbours overlap a little")

    def test_the_relevant_chapter_comes_first(self):
        for question, chapter in [("叶文洁在红岸基地做了什么？", 1), ("汪淼的照片怎么了", 2), ("史强是谁", 1)]:
            hits = self.search.search([self.book["id"]], question)
            self.assertTrue(hits, question)
            self.assertEqual(hits[0]["chapter"], chapter, question)
        self.assertEqual(self.search.search([self.book["id"]], "完全无关的问题"), [])
        self.assertEqual(self.search.search([], "叶文洁"), [])

    def test_results_stay_within_the_budget_and_do_not_repeat_a_stretch(self):
        hits = self.search.search([self.book["id"]], "叶文洁红岸基地天线", budget=700)
        self.assertLessEqual(sum(len(hit["text"]) for hit in hits), 700)
        self.assertLessEqual(len(hits), search_module.MAX_PASSAGES)
        starts = [hit["text"][:40] for hit in hits]
        self.assertEqual(len(starts), len(set(starts)))
        self.assertEqual(hits[0]["chapter_title"], "红岸之一")

    def test_a_book_is_indexed_once_and_again_when_the_format_changes(self):
        first = self.search.ensure(self.book["id"])
        self.assertGreater(first, 0)
        with self.library.connect() as db:
            db.execute("UPDATE passage_index SET version = 0")
        self.assertEqual(self.search.ensure(self.book["id"]), first)
        with self.library.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM passages WHERE book_id=?", (self.book["id"],)).fetchone()[0]
        self.assertEqual(count, first, "re-indexing replaces, never duplicates")

    def test_the_prompt_uses_passages_with_chapters_and_without_inventing(self):
        system = llm_chat.prepare({"text": "史强是谁"}, CONFIG, selected={"title": "三体", "author": "刘慈欣"},
                                  passages="【《三体》红岸之一】史强是一名警察")["messages"][0]["content"]
        self.assertIn("史强是一名警察", system)
        self.assertIn("标出章节", system)
        self.assertIn("不要编造", system)
        self.assertNotIn("正文未提供", system)
        bare = llm_chat.prepare({"text": "x"}, CONFIG, selected={"title": "三体"})["messages"][0]["content"]
        self.assertIn("正文未提供", bare)


class FurthestChapterTests(unittest.TestCase):
    def test_a_library_from_before_the_furthest_column_keeps_its_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            import sqlite3
            with sqlite3.connect(Path(directory) / "library.sqlite") as db:
                db.execute("CREATE TABLE progress(book_id TEXT PRIMARY KEY, chapter INTEGER, offset INTEGER)")
                db.execute("INSERT INTO progress VALUES('old', 5, 0)")
            db.close()
            library = book_library.BookLibrary(directory)
            self.assertEqual(library.read_up_to(["old", "never"]), {"old": 5}, "the current chapter counts as read")
            book = library.save({"title": "三体", "author": "刘慈欣", "source_id": "local", "source_key": "a",
                                 "chapters": CHAPTERS})
            library.progress(book["id"], 2, 0)
            library.progress(book["id"], 1, 0)
            self.assertEqual(library.read_up_to([book["id"]]), {book["id"]: 2}, "turning back keeps the furthest")
            self.assertEqual(library.get(book["id"], False)["progress"]["chapter"], 1)


spec = importlib.util.spec_from_file_location("passage_server", ROOT / "tools/asr-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ServerPassageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        library = book_library.BookLibrary(self.temp.name)
        self.book = library.save({"title": "三体", "author": "刘慈欣", "source_id": "local", "source_key": "a",
                                  "chapters": CHAPTERS})
        library.progress(self.book["id"], 1, 0)
        search = search_module.BookTextSearch(library)
        for target, value in [("instance", lambda: library)]:
            patcher = patch.object(book_library, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(server, "text_search", lambda: search)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_book_being_read_and_named_books_are_searched_and_labelled(self):
        reading = server.book_passages({"text": "史强是谁"}, {"id": self.book["id"], "title": "三体"})
        self.assertTrue(reading.startswith("【《三体》第2章 红岸之一】"), reading)
        self.assertIn("读者读到《三体》第 2 章", reading)
        self.assertEqual(server.book_passages({"text": "今天天气怎么样"}, None), "", "no book, no passages")
        first = server.book_passages({"text": "叶文洁的父亲"}, {"id": self.book["id"]})
        self.assertIn("【《三体》第一章 疯狂年代】", first, "a title that already says 第…章 is not doubled")

    def test_chapters_past_the_furthest_one_read_never_reach_the_model(self):
        # Read up to chapter 2 of 3: 汪淼's photographs are in chapter 3.
        ahead = server.book_passages({"text": "汪淼的照片怎么了"}, {"id": self.book["id"], "title": "三体"})
        self.assertNotIn("倒计时", ahead, "a passage from an unread chapter")
        self.assertIn("读者读到《三体》第 2 章", ahead, "the note alone still guards against spoilers")
        named = server.book_passages({"text": "三体里汪淼的照片怎么了"}, None)
        self.assertNotIn("倒计时", named, "a book named in the question is protected too")
        # Turning back to reread chapter 1 keeps chapter 2 open: it was already read.
        book_library.instance().progress(self.book["id"], 0, 0)
        back = server.book_passages({"text": "史强是谁"}, {"id": self.book["id"]})
        self.assertIn("史强是一名警察", back)
        self.assertIn("第 2 章", back)

    def test_the_reader_can_ask_for_what_comes_later(self):
        for text in ["不怕剧透，汪淼的照片后来怎么了", "汪淼的照片结局是什么", "剧透也没关系，汪淼的照片怎么了"]:
            told = server.book_passages({"text": text}, {"id": self.book["id"]})
            self.assertIn("倒计时", told, text)
            self.assertIn("先提醒一句会剧透", told, text)
        for text in ["别剧透，汪淼的照片怎么了", "不要告诉我结局，汪淼的照片怎么了", "汪淼的照片怎么了"]:
            self.assertFalse(server.wants_spoilers(text), text)
            self.assertNotIn("倒计时", server.book_passages({"text": text}, {"id": self.book["id"]}), text)

    def test_a_follow_up_is_searched_with_the_question_before_it(self):
        history = [{"role": "user", "content": "三体里叶文洁在红岸基地做了什么"},
                   {"role": "assistant", "content": "她在红岸基地工作。"}]
        alone = server.book_passages({"text": "她后来怎么样了"}, None)
        self.assertEqual(alone, "", "without the earlier question there is no book and no name")
        followed = server.book_passages({"text": "她后来怎么样了", "history": history}, None)
        self.assertIn("【《三体》第2章 红岸之一】", followed, "the book and 叶文洁 carry over")
        self.assertIn("叶文洁", followed)
        unrelated = server.book_passages(
            {"text": "请帮我写一段明天去公园散步的计划安排", "history": history}, None)
        self.assertEqual(unrelated, "", "a new, unrelated request does not inherit the book")
        self.assertEqual(server.previous_question({"history": "nonsense"}), "")

    def test_a_book_never_opened_has_nothing_to_protect(self):
        other = book_library.instance().save({"title": "球状闪电", "author": "刘慈欣", "source_id": "local",
                                              "source_key": "b", "chapters": CHAPTERS})
        named = server.book_passages({"text": "球状闪电里汪淼的照片怎么了"}, None)
        self.assertIn("倒计时", named)
        self.assertNotIn("读者读到《球状闪电》", named)
        self.assertEqual(book_library.instance().read_up_to([other["id"]]), {})


if __name__ == "__main__":
    unittest.main()
