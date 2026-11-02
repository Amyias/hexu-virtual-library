"""The second batch of library actions: fetch-then-act in one turn, searching and downloading
with the reader's consent, locating, font size and bookmarks. Uses a real reading library in a
temporary folder; online sources and the model are fixed test values, nothing is contacted."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import app_actions
import book_library
import llm_chat

# Obviously invalid test value; never read user configuration/environment or contact a provider.
CONFIG = {"HEXU_LLM_BASE_URL": "https://compatible.example/v1", "HEXU_LLM_MODEL": "test-model",
          "HEXU_LLM_API_KEY": "invalid-test-credential"}


def sse_call(name, arguments, call_id="call_1"):
    lines = ["data: " + json.dumps({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}]}}]},
        ensure_ascii=False), "data: [DONE]"]
    return io.BytesIO(("\n\n".join(lines) + "\n\n").encode("utf-8"))


def sse_text(text):
    lines = ["data: " + json.dumps({"choices": [{"delta": {"content": text}}]}, ensure_ascii=False), "data: [DONE]"]
    return io.BytesIO(("\n\n".join(lines) + "\n\n").encode("utf-8"))


def names(actions):
    return [tool["function"]["name"] for tool in actions.tools]


class LibraryToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = book_library.BookLibrary(self.temp.name)
        self.book = self.library.save({"title": "三体", "author": "刘慈欣", "source_id": "local", "source_key": "a",
                                       "chapters": [{"title": f"第{i}章", "text": f"第{i}章的正文。" * 5}
                                                    for i in range(1, 6)]})
        self.catalog = {"HX-03408": self.library.list_books()[0]}

    def idle(self):
        return app_actions.AppActions("IDLE", None, self.catalog, library=self.library)

    def reading(self):
        return app_actions.AppActions("READING", {"title": "三体", "chapter": 1, "chapters": 5}, self.catalog,
                                      reading_id=self.book["id"], library=self.library)

    def test_fetching_a_book_opens_its_chapters_and_music_for_the_same_turn(self):
        actions = self.idle()
        self.assertNotIn("open_chapter", names(actions))
        fetched, result = actions.execute("fetch_book", '{"bookId": "HX-03408"}')
        self.assertEqual(result["chapters"], 5)
        self.assertIn("open_chapter", names(actions))
        self.assertNotIn("fetch_book", names(actions), "one book a turn")
        self.assertIn("error", actions.execute("open_chapter", '{"chapter": 6}')[1], "checked against that book")
        chapter = actions.execute("open_chapter", '{"chapter": 3}')[0]
        self.assertEqual(chapter["args"], {"chapter": 3, "after": "arrival"})
        music = actions.execute("reading_music", '{"action": "play"}')[0]
        self.assertEqual(music["args"], {"action": "play", "after": "arrival"}, "a failed call does not count")
        self.assertIsNone(actions.execute("set_sky", '{"mode": "night"}')[0], "three actions a turn")

    def test_search_answers_here_and_download_needs_the_readers_yes(self):
        actions = self.idle()
        self.assertNotIn("download_book", names(actions), "nothing to download before a search")
        action, local = actions.execute("search_library", '{"query": "刘慈欣"}')
        self.assertIsNone(action, "a search moves nothing on the page")
        self.assertEqual(local["local"], [{"bookId": "HX-03408", "title": "三体", "author": "刘慈欣"}])
        online = {"local": [], "errors": [{"source_id": "x"}], "results": [
            {"title": "球状闪电", "author": "刘慈欣", "source_id": "wyshu", "source_key": "/book/1", "source": "无忧书城",
             "extra": "not passed on"}]}
        with patch.object(self.library, "search", return_value=online) as search:
            found = actions.execute("search_library", '{"query": "球状闪电", "online": true}')[1]
        search.assert_called_once_with("球状闪电")
        self.assertEqual(found["online"], [{"candidate": "C1", "title": "球状闪电", "author": "刘慈欣", "source": "无忧书城"}])
        self.assertEqual(found["failed_sources"], 1)
        self.assertIsNone(actions.execute("download_book", '{"candidate": "C9"}')[0])
        download = actions.execute("download_book", '{"candidate": "C1"}')
        self.assertEqual(download[0]["args"]["candidate"], {"title": "球状闪电", "author": "刘慈欣", "source_id": "wyshu",
                                                            "source_key": "/book/1", "source": "无忧书城"})
        self.assertIn("确认", download[1]["done"])

    def test_locating_and_font_size_are_checked(self):
        actions = self.idle()
        self.assertEqual(actions.execute("locate_book", '{"bookId": "HX-03408"}')[0]["args"]["title"], "三体")
        self.assertIn("error", actions.execute("locate_book", '{"bookId": "HX-00001"}')[1])
        reading = self.reading()
        self.assertEqual(reading.execute("set_font_size", '{"size": "larger"}')[0]["args"], {"size": "larger"})
        self.assertIn("error", reading.execute("set_font_size", '{"size": "huge"}')[1])
        self.assertNotIn("set_font_size", names(self.idle()))

    def test_bookmarks_are_kept_where_the_reader_is_and_can_be_returned_to(self):
        self.library.progress(self.book["id"], 2, 120)
        reading = self.reading()
        added = reading.execute("add_bookmark", '{"note": "叶文洁出场"}')
        self.assertIsNone(added[0])
        self.assertEqual({key: added[1]["bookmark"][key] for key in ("chapter", "chapter_title", "note")},
                         {"chapter": 3, "chapter_title": "第3章", "note": "叶文洁出场"})
        listed = reading.execute("list_bookmarks", "{}")[1]["bookmarks"]
        self.assertEqual(len(listed), 1)
        opened = reading.execute("open_bookmark", json.dumps({"id": listed[0]["id"]}))[0]
        self.assertEqual(opened["args"], {"chapter": 3, "offset": 120})
        self.assertIn("error", self.reading().execute("open_bookmark", '{"id": 999}')[1])
        self.assertEqual(self.library.bookmarks(self.book["id"])[0]["offset"], 120)

    def test_the_chat_offers_the_new_tools_after_a_fetch_in_the_same_turn(self):
        actions = self.idle()
        replies = [sse_call("fetch_book", '{"bookId": "HX-03408"}'),
                   sse_call("open_chapter", '{"chapter": 2}', "call_2"),
                   sse_text("好，我去取《三体》，到手就翻到第二章。")]
        with patch("llm_chat.open_completion", side_effect=replies) as call:
            events = list(llm_chat.chat_stream({"text": "取三体翻到第二章", "phase": "IDLE"}, CONFIG,
                                               lambda _url: None, app=actions))
        offered = [[tool["function"]["name"] for tool in json.loads(request[0][0].data).get("tools", [])]
                   for request in call.call_args_list]
        self.assertNotIn("open_chapter", offered[0])
        self.assertIn("open_chapter", offered[1], "after the fetch the chapter tool is offered")
        steps = [event for event in events if event["type"] == "action"]
        self.assertEqual([(step["name"], step["args"]) for step in steps],
                         [("fetch_book", {"bookId": "HX-03408", "title": "三体"}),
                          ("open_chapter", {"chapter": 2, "after": "arrival"})])


class Keywords:
    """A stand-in sentence-vector model: one dimension per theme word, unit length."""
    THEMES = ["科幻", "宇宙", "历史", "明朝", "乡村", "奋斗"]

    def state(self):
        return True, ""

    def encode(self, texts):
        import numpy as np

        rows = np.array([[float(word in text) for word in self.THEMES] + [0.01] for text in texts], np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)


SHELF = {
    "HX-00001": {"id": "a", "title": "三体", "author": "刘慈欣", "subjects": ["科幻"], "synopsis": "宇宙文明的黑暗森林"},
    "HX-00002": {"id": "b", "title": "球状闪电", "author": "刘慈欣", "subjects": ["科幻"], "synopsis": "宇宙中奇异的闪电"},
    "HX-00003": {"id": "c", "title": "明朝那些事儿", "author": "当年明月", "subjects": ["历史"], "synopsis": "明朝三百年"},
    "HX-00004": {"id": "d", "title": "平凡的世界", "author": "路遥", "subjects": ["当代小说"], "synopsis": "乡村青年的奋斗"},
}


class RecommendTests(unittest.TestCase):
    def actions(self, **kwargs):
        return app_actions.AppActions("IDLE", None, SHELF, embedder=Keywords(), **kwargs)

    def recommend(self, actions, arguments):
        return actions.execute("recommend_books", json.dumps(arguments, ensure_ascii=False))

    def test_like_a_book_recommends_others_from_this_library_with_a_reason(self):
        action, result = self.recommend(self.actions(), {"bookId": "HX-00001"})
        self.assertIsNone(action, "a recommendation moves nothing")
        books = result["books"]
        self.assertEqual(books[0]["bookId"], "HX-00002")
        self.assertEqual(books[0]["why"], "同属科幻")
        self.assertNotIn("HX-00001", [book["bookId"] for book in books], "not the book it is like")
        self.assertLessEqual(len(books), app_actions.RECOMMENDATIONS)
        self.assertTrue(all(book["bookId"] in SHELF for book in books), "only books of this library")

    def test_a_described_taste_or_recent_reading_guides_it(self):
        self.assertEqual(self.recommend(self.actions(), {"like": "想看点讲明朝历史的"})[1]["books"][0]["bookId"],
                         "HX-00003")
        recent = self.recommend(self.actions(recent=["d"]), {})[1]["books"]
        self.assertNotIn("HX-00004", [book["bookId"] for book in recent], "not what was just read")
        self.assertIn("error", self.recommend(self.actions(), {})[1], "no taste and no history: ask the reader")
        self.assertIn("error", self.recommend(self.actions(), {"bookId": "HX-09999"})[1])

    def test_the_book_being_read_is_not_recommended_and_tiny_libraries_are_not_offered_it(self):
        reading = app_actions.AppActions("READING", {"title": "球状闪电", "chapters": 3}, SHELF,
                                         reading_id="b", embedder=Keywords())
        books = self.recommend(reading, {"like": "科幻"})[1]["books"]
        self.assertNotIn("HX-00002", [book["bookId"] for book in books])
        single = app_actions.AppActions("IDLE", None, {"HX-00001": SHELF["HX-00001"]}, embedder=Keywords())
        self.assertNotIn("recommend_books", names(single))

    def test_without_the_vector_model_it_compares_words(self):
        plain = app_actions.AppActions("IDLE", None, SHELF)
        self.assertIsNone(plain.embedder)
        self.assertEqual(self.recommend(plain, {"like": "明朝历史"})[1]["books"][0]["bookId"], "HX-00003")


if __name__ == "__main__":
    unittest.main()
