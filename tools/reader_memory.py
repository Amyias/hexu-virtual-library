"""小和's long-term memory of the reader, kept on this machine only.

Three kinds of entry, each with a source the reader can see:

    facts      what the reader explicitly asked 小和 to remember (「记住我喜欢科幻」). The model never
               writes here; a memory 小和 invented for itself would be worse than none.
    reading    which local books were opened, and when. The chapter reached comes from the
               reading library's own progress table, so nothing is recorded twice.
    summaries  one line per finished conversation, written by the configured model from the
               conversation the reader had, or nothing when the talk was only small talk.

context() condenses them into a short block for the chat prompt. That block is the only part
that leaves the machine, and only towards the model service the reader configured. The reader can
list, delete, clear or switch all of it off from the settings page.
"""
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from book_text_search import grams

MAX_FACTS = 30
MAX_FACT_CHARS = 120
MAX_SUMMARIES = 20
MAX_SUMMARY_CHARS = 120
CONTEXT_CHARS = 400  # a ceiling on what every chat turn pays for in tokens
RECENT_BOOKS = 3
RECENT_SUMMARIES = 3
HALF_LIFE_DAYS = 14  # how fast an old memory gives way to a newer one when neither fits better
# Characters too common to say what a sentence is about.
FUNCTION_CHARACTERS = set("我你他她它们的了吗呢吧啊呀是在有和就都也还要会能可不没这那个一么什怎哪谁很太想说过对把被给让")


def memory_directory():
    override = os.environ.get("HEXU_MEMORY_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".local" / "share")))
    return base / "hexu-library"


def clean_line(text, limit):
    """One line of reader-visible text, or ValueError."""
    if not isinstance(text, str):
        raise ValueError("内容必须是文字")
    text = " ".join(text.split()).strip(" ，,。.")
    if len(text) < 2:
        raise ValueError("内容太短")
    if len(text) > limit:
        raise ValueError(f"内容不超过 {limit} 字")
    return text


def ago(seconds):
    days = int(seconds // 86400)
    return "今天" if days <= 0 else "昨天" if days == 1 else f"{days} 天前"


class ReaderMemory:
    def __init__(self, directory=None, clock=time.time):
        self.directory = Path(directory or memory_directory())
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "memory.sqlite"
        self.clock = clock
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, text TEXT UNIQUE, created_at INTEGER);
                CREATE TABLE IF NOT EXISTS reading(book_id TEXT PRIMARY KEY, opened INTEGER,
                    first_opened INTEGER, last_opened INTEGER);
                CREATE TABLE IF NOT EXISTS summaries(id INTEGER PRIMARY KEY, text TEXT, turns INTEGER,
                    created_at INTEGER);
            """)

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    # --- switch ---------------------------------------------------------------
    def enabled(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='enabled'").fetchone()
        return row is None or row["value"] == "1"

    def set_enabled(self, on):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES('enabled', ?)", ("1" if on else "0",))
        return self.enabled()

    # --- writes ---------------------------------------------------------------
    def add_fact(self, text):
        if not self.enabled():
            raise PermissionError("记忆已关闭")
        text = clean_line(text, MAX_FACT_CHARS)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO facts(text, created_at) VALUES(?, ?)", (text, int(self.clock())))
            # Keep the newest ones; an old preference the reader never repeated ages out first.
            db.execute("DELETE FROM facts WHERE id NOT IN (SELECT id FROM facts ORDER BY created_at DESC, id DESC LIMIT ?)",
                       (MAX_FACTS,))
            row = db.execute("SELECT id, text, created_at FROM facts WHERE text=?", (text,)).fetchone()
        return dict(row)

    def record_opened(self, book_id):
        if not self.enabled():
            return False
        if not isinstance(book_id, str) or not 1 <= len(book_id) <= 64:
            raise ValueError("书籍编号无效")
        now = int(self.clock())
        with self.connect() as db:
            db.execute("""INSERT INTO reading VALUES(?, 1, ?, ?)
                          ON CONFLICT(book_id) DO UPDATE SET opened=opened+1, last_opened=excluded.last_opened""",
                       (book_id, now, now))
        return True

    def add_summary(self, text, turns):
        if not self.enabled():
            return None
        text = clean_line(text, MAX_SUMMARY_CHARS)
        with self.connect() as db:
            cursor = db.execute("INSERT INTO summaries(text, turns, created_at) VALUES(?, ?, ?)",
                                (text, int(turns), int(self.clock())))
            db.execute("DELETE FROM summaries WHERE id NOT IN (SELECT id FROM summaries ORDER BY id DESC LIMIT ?)",
                       (MAX_SUMMARIES,))
        return {"id": cursor.lastrowid, "text": text}

    def delete(self, kind, identifier):
        table = {"fact": "facts", "summary": "summaries", "reading": "reading"}.get(kind)
        if not table:
            raise ValueError("记忆类型无效")
        column = "book_id" if table == "reading" else "id"
        with self.connect() as db:
            removed = db.execute(f"DELETE FROM {table} WHERE {column}=?", (identifier,)).rowcount
        return removed > 0

    def clear(self):
        with self.connect() as db:
            for table in ("facts", "reading", "summaries"):
                db.execute(f"DELETE FROM {table}")

    # --- reads ----------------------------------------------------------------
    def reading(self, describe):
        """Opened books, newest first, joined with what the library knows about each.
        describe(book_id) -> {"title", "author", "chapter", "chapters", "chapter_title"} or None
        (a book deleted from the library is skipped)."""
        with self.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM reading ORDER BY last_opened DESC")]
        entries = []
        for row in rows:
            book = describe(row["book_id"])
            if book:
                entries.append({**row, **book})
        return entries

    def snapshot(self, describe):
        """Everything, for the settings page."""
        with self.connect() as db:
            facts = [dict(row) for row in db.execute("SELECT id, text, created_at FROM facts ORDER BY created_at DESC, id DESC")]
            summaries = [dict(row) for row in db.execute("SELECT id, text, turns, created_at FROM summaries ORDER BY id DESC")]
        return {"enabled": self.enabled(), "facts": facts, "reading": self.reading(describe),
                "summaries": summaries, "path": str(self.path)}

    def context(self, describe, question=""):
        """The few lines a chat turn carries, within CONTEXT_CHARS, or "" when off or empty.
        Facts and conversation summaries come in ranked() order, so what bears on the question
        is not crowded out by whatever was said last; opened books stay newest first, except
        that a book the question names comes first."""
        if not self.enabled():
            return ""
        now = self.clock()
        question = question if isinstance(question, str) else ""
        lines = []
        with self.connect() as db:
            facts = [dict(row) for row in db.execute(
                "SELECT text, created_at FROM facts ORDER BY created_at DESC, id DESC")]
            summaries = [dict(row) for row in db.execute(
                "SELECT text, created_at FROM summaries ORDER BY id DESC")]
        facts = [fact["text"] for fact in ranked(facts, question, now)]
        summaries = ranked(summaries, question, now)[:RECENT_SUMMARIES]
        if facts:
            # Newest first, fact by fact, within half the budget: many remembered preferences
            # must not crowd out the books and conversations, nor empty the block altogether.
            line = "读者让你记住的事：" + facts[0][: CONTEXT_CHARS // 2]
            for fact in facts[1:]:
                if len(line) + 1 + len(fact) > CONTEXT_CHARS // 2:
                    break
                line += "；" + fact
            lines.append(line)
        books = sorted(self.reading(describe), key=lambda book: not (book.get("title") and book["title"] in question))
        for book in books[:RECENT_BOOKS]:
            where = f"读到第 {book['chapter'] + 1} 章「{book['chapter_title']}」" if book.get("chapter_title") else "刚开始读"
            lines.append(f"在读《{book['title']}》（{book.get('author') or '未知作者'}），{where}，"
                         f"{ago(now - book['last_opened'])}打开过")
        for summary in summaries:
            lines.append(f"{ago(now - summary['created_at'])}聊过：{summary['text']}")
        text = ""
        for line in lines:  # whole lines only, most important first, never a cut-off sentence
            if len(text) + len(line) + 1 > CONTEXT_CHARS:
                break
            text += line + "\n"
        return text.strip()


def characters(text):
    """The single CJK characters of a text that carry meaning: 「我能养猫吗」 and 「我对猫毛过敏」
    share no character pair, only 猫."""
    return {char for char in text if "一" <= char <= "鿿" and char not in FUNCTION_CHARACTERS}


def ranked(entries, question, now):
    """Entries ({"text", "created_at"}) best first, scored as Generative Agents scores memories:
    3 × relevance + 0.5 × recency, recency halving every HALF_LIFE_DAYS. Relevance is the share of
    the question's character pairs (as the book search indexes them) the entry contains, with the
    share of its single meaningful characters counting for less. With no question, or nothing in
    common, that is simply newest first. Importance, the third term there, is left out: every
    fact here was said by the reader and weighs the same."""
    pairs = set(grams(question, query=True).split())
    chars = characters(question)

    def score(entry):
        shared = 0.0
        if pairs:
            shared += 0.6 * len(pairs & set(grams(entry["text"]).split())) / len(pairs)
        if chars:
            shared += 0.4 * len(chars & characters(entry["text"])) / len(chars)
        recency = 0.5 ** (max(0, now - entry["created_at"]) / 86400 / HALF_LIFE_DAYS)
        return 3 * shared + 0.5 * recency

    return sorted(entries, key=score, reverse=True)


def context_if_present(describe, question=""):
    """The chat prompt's memory block without creating a memory file just to find it empty: a
    conversation alone never leaves a file behind; remembering something or opening a book does."""
    if _instance is None and not (memory_directory() / "memory.sqlite").is_file():
        return ""
    return instance().context(describe, question)


def snapshot_if_present(describe):
    """The settings snapshot, or an empty one without creating the memory file (the greeting
    peeks at this on every start)."""
    if _instance is None and not (memory_directory() / "memory.sqlite").is_file():
        return {"enabled": True, "facts": [], "reading": [], "summaries": [], "path": ""}
    return instance().snapshot(describe)


_instance = None
_instance_lock = threading.Lock()


def instance():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ReaderMemory()
    return _instance
