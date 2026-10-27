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
"""
import re
import threading

PASSAGE = 300
OVERLAP = 60
MAX_PASSAGES = 4
BUDGET = 1600
VERSION = 1  # bump when chunking or tokenising changes; books are then re-indexed on demand

SCHEMA = """
    CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
        grams, book_id UNINDEXED, chapter UNINDEXED, text UNINDEXED, tokenize = 'unicode61');
    CREATE TABLE IF NOT EXISTS passage_index(book_id TEXT PRIMARY KEY, version INTEGER, passages INTEGER);
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


class BookTextSearch:
    def __init__(self, library):
        self.library = library
        self.lock = threading.Lock()
        with library.connect() as db:
            db.executescript(SCHEMA)

    def ensure(self, book_id):
        """Index one book if it is not indexed at the current VERSION. Returns passage count."""
        with self.lock, self.library.connect() as db:
            row = db.execute("SELECT version, passages FROM passage_index WHERE book_id=?", (book_id,)).fetchone()
            if row and row["version"] == VERSION:
                return row["passages"]
            db.execute("DELETE FROM passages WHERE book_id=?", (book_id,))
            count = 0
            for chapter in db.execute("SELECT number, title, body FROM chapters WHERE book_id=? ORDER BY number",
                                      (book_id,)).fetchall():
                rows = [(grams(piece), book_id, chapter["number"], piece) for piece in chunks(chapter["body"])]
                db.executemany("INSERT INTO passages(grams, book_id, chapter, text) VALUES(?,?,?,?)", rows)
                count += len(rows)
            db.execute("INSERT OR REPLACE INTO passage_index VALUES(?,?,?)", (book_id, VERSION, count))
            return count

    def search(self, book_ids, question, *, limit=MAX_PASSAGES, budget=BUDGET, up_to=None):
        """The passages most relevant to the question, best first, within `budget` characters:
        [{"book_id", "chapter", "chapter_title", "text"}]. Empty when nothing matches.
        up_to: {book id: last chapter allowed}; a book in it yields no passage from a later
        chapter, so what the reader has not reached yet never reaches the model."""
        terms = grams(question, query=True).split()
        book_ids = [book_id for book_id in dict.fromkeys(book_ids) if book_id][:3]
        if not terms or not book_ids:
            return []
        for book_id in book_ids:
            self.ensure(book_id)
        match = " OR ".join(f'"{term}"' for term in terms[:40])
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
            rows = db.execute(
                f"""SELECT book_id, chapter, text FROM passages
                    WHERE passages MATCH ? AND ({" OR ".join(scopes)})
                    ORDER BY bm25(passages) LIMIT 12""",
                (match, *values)).fetchall()
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
