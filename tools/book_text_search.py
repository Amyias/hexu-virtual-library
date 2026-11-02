"""Find the passages of local books that bear on a question: the retrieval half of 小和's reading
companion (retrieval-augmented generation, without a vector database).

Every chapter is cut into passages of about PASSAGE characters, overlapping a little so a sentence
is never only half in one. They go into an SQLite FTS5 table inside the reading library's own
database. FTS5's tokenisers do not segment Chinese, so the text is indexed as overlapping
character pairs ("二字一组": 叶文洁 -> 叶文 文洁), and a question is matched the same way; bm25
ranks the passages. English words are indexed whole, lower-cased.

A book is indexed the first time it is asked about, so importing stays fast; indexing about 1.3
million characters takes around half a second and a query a few tens of milliseconds. Only passages are ever returned, within BUDGET characters: that is what
the chat may send to the configured model, never a whole book.

Character pairs find names and rare words but miss the same thing said differently: 「主角的妈妈」
shares nothing with 「他的母亲」. With the sentence-vector model (tools/embedder.py) each passage
also gets a vector, and the two rankings are fused by reciprocal rank (RRF, k = 60): a passage near
the top of either rises, one both agree on rises most. Vectors below a floor are left out
(a higher one when the words found nothing), so a question unrelated to the book mostly finds
nothing rather than its least bad passage.
"""
import re
import threading

PASSAGE = 300
OVERLAP = 60
MAX_PASSAGES = 4
BUDGET = 1600
VERSION = 1  # bump when chunking or tokenising changes; books are then re-indexed on demand
RRF_K = 60
VECTOR_BATCH = 64  # passages encoded per step while a book's vectors are computed
CACHED_BOOKS = 3  # books whose vectors stay in memory (about 9 MB for a long novel)
# Cosine floors. Measured on paraphrased questions against unrelated ones (docs/VOICE_EVAL.md has
# the numbers): the two overlap, so one floor cannot separate them. Vectors may add passages to
# what the words found at the lower floor, but bring passages on their own only above the higher.
SIMILARITY_FLOOR = 0.62
ALONE_FLOOR = 0.66

SCHEMA = """
    CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
        grams, book_id UNINDEXED, chapter UNINDEXED, text UNINDEXED, tokenize = 'unicode61');
    CREATE TABLE IF NOT EXISTS passage_index(book_id TEXT PRIMARY KEY, version INTEGER, passages INTEGER);
    CREATE TABLE IF NOT EXISTS passage_vectors(rowid INTEGER PRIMARY KEY, book_id TEXT, vector BLOB);
    CREATE INDEX IF NOT EXISTS passage_vectors_book ON passage_vectors(book_id);
    CREATE TABLE IF NOT EXISTS vector_index(book_id TEXT PRIMARY KEY, version INTEGER, passages INTEGER);
"""

CJK = r"㐀-䶿一-鿿豈-﫿"
TOKEN = re.compile(rf"[{CJK}]+|[A-Za-z0-9]+")
# Pairs that carry no subject matter in a question about a book. Dropping them keeps bm25 from
# ranking passages by how often they say 什么 or 这个.
STOP = set()
for phrase in ("什么", "怎么", "怎样", "为什么", "为何", "是谁", "谁是", "哪里", "哪个", "哪些", "这个", "那个",
               "这本", "本书", "书里", "里面", "一下", "告诉", "请问", "小和", "我们", "你们", "他们", "她们",
               "一个", "没有", "可以", "知道", "觉得", "这章", "章节", "第几", "讲了", "讲的", "内容", "情节",
               "故事", "主要", "关于", "还是", "后来", "最后", "结局", "如何", "是不", "不是", "有没", "有什",
               "么样", "了什", "做了", "发生", "的人", "的是", "了吗", "是什", "么人"):
    STOP.update(phrase[i:i + 2] for i in range(len(phrase) - 1))


def grams(text, *, query=False):
    """Space-separated index terms: overlapping CJK pairs (a lone character stays itself) and
    lower-cased ASCII words. For a query, terms that carry no subject matter are dropped."""
    terms = []
    for run in TOKEN.findall(text or ""):
        if re.match(rf"[{CJK}]", run):
            pairs = [run[i:i + 2] for i in range(len(run) - 1)] or [run]
            terms.extend(pair for pair in pairs if not (query and pair in STOP))
        elif not query or len(run) > 1:
            terms.append(run.lower())
    if query:
        terms = list(dict.fromkeys(terms))  # each term once; order kept for readability in tests
    return " ".join(terms)


def chunks(body, size=PASSAGE, overlap=OVERLAP):
    """Passages of about `size` characters, ending at a sentence end where one is close."""
    text = re.sub(r"\s+", " ", body or "").strip()
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = max(text.rfind(mark, start + size // 2, end) for mark in "。！？!?；…")
            if cut > 0:
                end = cut + 1
        yield text[start:end].strip()
        if end >= len(text):
            break
        # The next passage repeats the tail, but from a sentence start where there is one: a
        # passage opening mid-sentence reads badly to the model.
        start = max(end - overlap, start + 1)
        boundary = min((i for i in (text.find(mark, start, end) for mark in "。！？!?；") if i >= 0), default=-1)
        if 0 <= boundary < end - 1:
            start = boundary + 1


def fuse(*rankings, k=RRF_K):
    """Reciprocal rank fusion: one list of ids from several best-first lists, each id scored
    Σ 1 / (k + rank). An id near the top of either list rises; agreement rises further."""
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda key: -scores[key])


class BookTextSearch:
    """Full-text search, and when an embedder is given, sentence vectors fused with it.

    Vectors for a book are computed in the background the first time it is searched (a long
    novel takes some seconds), so that first answer uses the full-text index alone and later
    ones use both. They live in the library's own database beside the index."""

    def __init__(self, library, embedder=None):
        self.library = library
        self.embedder = embedder if embedder is not None and embedder.state()[0] else None
        self.lock = threading.Lock()
        self.working = set()  # books whose vectors are being computed
        self.cache = {}  # book id -> (passage ids, chapters, matrix), the few books in use
        with library.connect() as db:
            db.executescript(SCHEMA)

    def ensure(self, book_id, *, wait=False):
        """Index one book if it is not indexed at the current VERSION, and start its vectors.
        wait: compute the vectors now rather than in the background (tests). Returns passage count."""
        with self.lock, self.library.connect() as db:
            row = db.execute("SELECT version, passages FROM passage_index WHERE book_id=?", (book_id,)).fetchone()
            if row and row["version"] == VERSION:
                count = row["passages"]
            else:
                count = self._index(db, book_id)
        if self.embedder:
            self._vectorise(book_id, wait)
        return count

    def _index(self, db, book_id):
        # Re-indexing renumbers the passages, so their vectors go with them.
        db.execute("DELETE FROM passage_vectors WHERE book_id=?", (book_id,))
        db.execute("DELETE FROM vector_index WHERE book_id=?", (book_id,))
        self.cache.pop(book_id, None)
        db.execute("DELETE FROM passages WHERE book_id=?", (book_id,))
        count = 0
        for chapter in db.execute("SELECT number, title, body FROM chapters WHERE book_id=? ORDER BY number",
                                  (book_id,)).fetchall():
            rows = [(grams(piece), book_id, chapter["number"], piece) for piece in chunks(chapter["body"])]
            db.executemany("INSERT INTO passages(grams, book_id, chapter, text) VALUES(?,?,?,?)", rows)
            count += len(rows)
        db.execute("INSERT OR REPLACE INTO passage_index VALUES(?,?,?)", (book_id, VERSION, count))
        return count

    # --- vectors -------------------------------------------------------------
    def _vectorise(self, book_id, wait):
        with self.lock, self.library.connect() as db:
            done = db.execute("SELECT 1 FROM vector_index WHERE book_id=? AND version=?",
                              (book_id, VERSION)).fetchone()
            if done or book_id in self.working:
                return
            self.working.add(book_id)
        if wait:
            self._compute(book_id)
        else:
            threading.Thread(target=self._compute, args=(book_id,), daemon=True,
                             name=f"vectors-{book_id}").start()

    def _compute(self, book_id):
        import numpy as np

        try:
            with self.library.connect() as db:
                rows = db.execute("SELECT rowid, text FROM passages WHERE book_id=? ORDER BY rowid",
                                  (book_id,)).fetchall()
            for start in range(0, len(rows), VECTOR_BATCH):
                part = rows[start:start + VECTOR_BATCH]
                vectors = self.embedder.encode([row["text"] for row in part]).astype(np.float16)
                with self.library.connect() as db:
                    db.executemany("INSERT OR REPLACE INTO passage_vectors VALUES(?,?,?)",
                                   [(row["rowid"], book_id, vector.tobytes()) for row, vector in zip(part, vectors)])
            with self.library.connect() as db:
                db.execute("INSERT OR REPLACE INTO vector_index VALUES(?,?,?)", (book_id, VERSION, len(rows)))
        except Exception:
            pass  # vectors are an improvement, never a requirement: full text still answers
        finally:
            with self.lock:
                self.working.discard(book_id)

    def _vectors(self, book_id):
        """(passage ids, chapters, matrix) for a book whose vectors are complete, else None."""
        import numpy as np

        if book_id in self.cache:
            return self.cache[book_id]
        with self.library.connect() as db:
            if not db.execute("SELECT 1 FROM vector_index WHERE book_id=? AND version=?",
                              (book_id, VERSION)).fetchone():
                return None
            rows = db.execute("""SELECT v.rowid AS id, CAST(p.chapter AS INTEGER) AS chapter, v.vector
                                 FROM passage_vectors v JOIN passages p ON p.rowid = v.rowid
                                 WHERE v.book_id=? ORDER BY v.rowid""", (book_id,)).fetchall()
        if not rows:
            return None
        found = (np.array([row["id"] for row in rows]), np.array([row["chapter"] for row in rows]),
                 np.frombuffer(b"".join(row["vector"] for row in rows), np.float16).reshape(len(rows), -1)
                 .astype(np.float32))
        if len(self.cache) >= CACHED_BOOKS:
            self.cache.pop(next(iter(self.cache)))
        self.cache[book_id] = found
        return found

    def _similar(self, book_ids, question, up_to, floor=SIMILARITY_FLOOR):
        """Passage ids by vector similarity, best first, at or above `floor`."""
        import numpy as np

        if not self.embedder:
            return []
        loaded = [(book_id, self._vectors(book_id)) for book_id in book_ids]
        loaded = [(book_id, vectors) for book_id, vectors in loaded if vectors]
        if not loaded:
            return []
        query = self.embedder.encode([question])[0]
        scored = []
        for book_id, (ids, chapters, matrix) in loaded:
            scores = matrix @ query
            if book_id in up_to:
                scores = np.where(chapters <= int(up_to[book_id]), scores, -1.0)
            best = np.argsort(-scores)[:12]
            scored += [(float(scores[index]), int(ids[index])) for index in best if scores[index] >= floor]
        return [key for _, key in sorted(scored, reverse=True)[:12]]

    def search(self, book_ids, question, *, limit=MAX_PASSAGES, budget=BUDGET, up_to=None):
        """The passages most relevant to the question, best first, within `budget` characters:
        [{"book_id", "chapter", "chapter_title", "text"}]. Empty when nothing matches.
        up_to: {book id: last chapter allowed}; a book in it yields no passage from a later
        chapter, so what the reader has not reached yet never reaches the model."""
        terms = grams(question, query=True).split()
        book_ids = [book_id for book_id in dict.fromkeys(book_ids) if book_id][:3]
        if not book_ids or not (terms or self.embedder):
            return []
        for book_id in book_ids:
            self.ensure(book_id)
        up_to = up_to or {}
        scopes, values = [], []
        for book_id in book_ids:
            if book_id in up_to:
                scopes.append("(book_id = ? AND CAST(chapter AS INTEGER) <= ?)")
                values += [book_id, int(up_to[book_id])]
            else:
                scopes.append("book_id = ?")
                values.append(book_id)
        with self.library.connect() as db:
            lexical = [row["rowid"] for row in db.execute(
                f"""SELECT rowid FROM passages
                    WHERE passages MATCH ? AND ({" OR ".join(scopes)})
                    ORDER BY bm25(passages) LIMIT 12""",
                (" OR ".join(f'"{term}"' for term in terms[:40]), *values)).fetchall()] if terms else []
        # Words for names and rare terms, vectors for the same thing said differently.
        similar = self._similar(book_ids, question, up_to, SIMILARITY_FLOOR if lexical else ALONE_FLOOR)
        order = fuse(lexical, similar)[:12]
        with self.library.connect() as db:
            found = {row["rowid"]: row for row in db.execute(
                f"SELECT rowid, book_id, chapter, text FROM passages WHERE rowid IN ({','.join('?' * len(order))})",
                order).fetchall()} if order else {}
            rows = [found[key] for key in order if key in found]
            titles = {}
            for row in rows:
                key = (row["book_id"], row["chapter"])
                if key not in titles:
                    found = db.execute("SELECT title FROM chapters WHERE book_id=? AND number=?", key).fetchone()
                    titles[key] = found["title"] if found else ""
        picked, used = [], 0
        for row in rows:
            if len(picked) >= limit:
                break
            # Overlapping neighbours say the same thing twice; one per stretch is enough.
            if any(p["book_id"] == row["book_id"] and p["chapter"] == row["chapter"]
                   and (row["text"][:40] in p["text"] or p["text"][:40] in row["text"]) for p in picked):
                continue
            if used + len(row["text"]) > budget:
                continue
            used += len(row["text"])
            picked.append({"book_id": row["book_id"], "chapter": row["chapter"],
                           "chapter_title": titles[(row["book_id"], row["chapter"])], "text": row["text"]})
        return picked
