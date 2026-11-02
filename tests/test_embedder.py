"""Sentence vectors in book search (tools/embedder.py, tools/book_text_search.py).

Tests that run the model need it in .cache/models/embed (package-local fetches it) and are
skipped without it; the tokenizer, fusion and the fallback run everywhere. No network."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import book_library
import book_text_search
import embedder

MODEL = embedder.model_dir()
HAVE_MODEL = embedder.Embedder(MODEL).state()[0]
BOOK = json.loads((ROOT / "tests" / "fixtures" / "paraphrase-book.json").read_text(encoding="utf-8"))


def library_with(directory, passages):
    library = book_library.BookLibrary(directory)
    book = library.save({"title": "测试", "author": "测试", "source_id": "local", "source_key": "k",
                         "chapters": [{"title": f"第{i + 1}章", "text": text} for i, text in enumerate(passages)]})
    return library, book["id"]


class TokenizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        vocab = Path(self.temp.name) / "vocab.txt"
        vocab.write_text("\n".join(["[PAD]", "[UNK]", "[CLS]", "[SEP]", "小", "和", "，", "hx", "-",
                                    "034", "##08", "un", "##known"]), encoding="utf-8")
        self.tokenizer = embedder.Tokenizer(vocab)

    def test_bert_basic_tokenising_and_wordpiece(self):
        self.assertEqual(self.tokenizer.words("小和，HX-03408 好\x00"), ["小", "和", "，", "HX", "-", "03408", "好"])
        self.assertEqual(self.tokenizer.wordpiece("03408"), [9, 10])
        self.assertEqual(self.tokenizer.wordpiece("HX"), [1], "case is kept: HX is not hx")
        self.assertEqual(self.tokenizer.wordpiece("unknown"), [11, 12])
        self.assertEqual(self.tokenizer.encode("小和"), [2, 4, 5, 3])
        self.assertEqual(len(self.tokenizer.encode("小" * 1000)), embedder.MAX_TOKENS)

    def test_rankings_fuse_by_reciprocal_rank(self):
        self.assertEqual(book_text_search.fuse([1, 2, 3], [3, 4]), [3, 1, 2, 4], "agreement rises")
        self.assertEqual(book_text_search.fuse([], [7, 8]), [7, 8])
        self.assertEqual(book_text_search.fuse([], []), [])


class FallbackTests(unittest.TestCase):
    def test_without_the_model_search_is_full_text_as_before(self):
        with tempfile.TemporaryDirectory() as directory:
            library, book = library_with(directory, BOOK["passages"])
            missing = embedder.Embedder(Path(directory) / "no-model")
            self.assertFalse(missing.state()[0])
            search = book_text_search.BookTextSearch(library, missing)
            self.assertIsNone(search.embedder)
            self.assertTrue(search.search([book], "叶文洁为什么对人类失望"))
            self.assertEqual(search.search([book], "红烧肉怎么做"), [])


@unittest.skipUnless(HAVE_MODEL, "向量模型不在 .cache/models/embed")
class HybridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.embedder = embedder.Embedder(MODEL)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library, self.book = library_with(self.temp.name, BOOK["passages"])

    def score(self, search):
        answered = sum(any(hit["chapter"] == case["passage"] for hit in search.search([self.book], case["question"]))
                       for case in BOOK["related"])
        noise = sum(bool(search.search([self.book], question)) for question in BOOK["unrelated"])
        return answered, noise

    def test_vectors_find_what_the_words_miss_without_adding_noise(self):
        words = book_text_search.BookTextSearch(self.library)
        both = book_text_search.BookTextSearch(self.library, self.embedder)
        both.ensure(self.book, wait=True)
        (lexical, lexical_noise), (hybrid, hybrid_noise) = self.score(words), self.score(both)
        # Measured: 4/12 and 1/10 with words alone, 7/12 and 1/10 with both.
        self.assertGreaterEqual(hybrid, lexical + 2, (lexical, hybrid))
        self.assertLessEqual(hybrid_noise, lexical_noise, (lexical_noise, hybrid_noise))

    def test_vectors_are_built_in_the_background_and_follow_the_index(self):
        search = book_text_search.BookTextSearch(self.library, self.embedder)
        search.ensure(self.book)  # returns at once; the vectors follow
        for _ in range(200):
            if search._vectors(self.book) is not None:
                break
            time.sleep(0.05)
        ids, chapters, matrix = search._vectors(self.book)
        self.assertEqual(matrix.shape, (len(BOOK["passages"]), 512))
        with self.library.connect() as db:
            db.execute("UPDATE passage_index SET version = 0")
        search.ensure(self.book, wait=True)  # re-indexed: new passage ids, new vectors
        with self.library.connect() as db:
            vectors = db.execute("SELECT COUNT(*) FROM passage_vectors").fetchone()[0]
        self.assertEqual(vectors, len(BOOK["passages"]), "stale vectors are dropped with the old index")

    def test_unread_chapters_stay_out_of_vector_results_too(self):
        search = book_text_search.BookTextSearch(self.library, self.embedder)
        search.ensure(self.book, wait=True)
        hits = search.search([self.book], "老奶奶临走前给了他什么东西", up_to={self.book: 2})
        self.assertTrue(all(hit["chapter"] <= 2 for hit in hits), hits)


if __name__ == "__main__":
    unittest.main()
