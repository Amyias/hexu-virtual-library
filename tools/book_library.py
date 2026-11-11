"""Persistent local reading library, asynchronous downloads and HTTP API (stdlib only)."""
import base64
import hashlib
import io
import json
import os
import posixpath
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
import zipfile
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
import urllib.request
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

from aggregate_search import SearchJobs, group_candidates
from builtin_book_sources import BUILTIN_SOURCES, BuiltinNovelSource
from book_sources import (CssSource, Document, SourceError, Wikisource, clean, fetch, normalize_source,
                          set_fake_ip_allowed, split_chapters as split_text, validate_url)


def library_directory():
    override = os.environ.get("HEXU_BOOK_LIBRARY_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".local" / "share")))
    return base / "hexu-library" / "books"


SHELF_LIMIT = 11000
# Preferred order of free slot numbers for new books; None keeps the plain next-number rule.
_fill_order = None


def physical_rows(inventory):
    """Inventory row index for each persisted slot number, oldest rule first.

    A stored book keeps its slot number forever, so this mapping must never change: literature
    (shelf 2) first, then the other shelves, with the IDs earlier releases skipped at the end.
    src/data/shelf-slots.js expands the same order in the browser."""
    deferred = set(inventory["library_deferred_ids"])
    rows = inventory["books"]
    physical = [i for i in range(len(rows)) if i + 1 not in deferred]
    physical.sort(key=lambda i: rows[i][0] != 2)
    return physical + [i for i in range(len(rows)) if i + 1 in deferred]


def shelf_fill_order(inventory):
    """Slot numbers in the order a new book takes them: where a reader sees it first.

    Slot 0 of the persisted order sits at the window end of the bottom layer, which no view of
    the hall shows. New books instead start at the front-desk end of the literature shelf's
    A face (the one the overview camera faces), filling each column top layer down before
    stepping one spine further from the end panel. Only the choice of a free number changes;
    the number -> position mapping above is untouched, so stored books never move."""
    rows = inventory["books"]
    physical = physical_rows(inventory)[:SHELF_LIMIT]
    columns = inventory["columns"]
    shelf, side, layer, z = (columns.index(name) for name in ("shelf", "side", "layer", "z"))

    def visibility(slot):
        row = rows[physical[slot]]
        return (row[shelf] != 2, row[shelf], row[side] != "A", -row[z], -row[layer])

    return sorted(range(len(physical)), key=visibility)


def configure_shelves(inventory_path):
    """Called by the server with the shipped inventory; tests may leave it unconfigured."""
    global _fill_order
    _fill_order = shelf_fill_order(json.loads(Path(inventory_path).read_text(encoding="utf-8")))


def next_slot(used):
    if _fill_order is None:
        slot = max(used, default=-1) + 1
        return slot if slot < SHELF_LIMIT else None
    return next((slot for slot in _fill_order if slot not in used), None)


def normalize(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def isbn_of(text):
    """The first valid ISBN-13 or ISBN-10 in a text (an EPUB identifier is often
    「urn:isbn:978-7-5366-9293-0」), as bare digits; "" when there is none."""
    for found in re.findall(r"(?:97[89][\d\- ]{10,16}|\b\d[\d\- ]{8,12}[\dXx]\b)", text or ""):
        digits = re.sub(r"[^\dXx]", "", found).upper()
        if len(digits) == 13 and digits.isdigit():
            if sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits)) % 10 == 0:
                return digits
        elif len(digits) == 10 and digits[:9].isdigit():
            total = sum((10 - i) * (10 if d == "X" else int(d)) for i, d in enumerate(digits))
            if total % 11 == 0:
                return digits
    return ""


OPEN_LIBRARY = "https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&jscmd=data&format=json"


def lookup_isbn(isbn, opener=urllib.request.urlopen, timeout=10):
    """What Open Library (free, no key) knows about an ISBN: subjects, publisher, date and
    pages; {} when it knows nothing or cannot be reached. Only the ISBN is sent."""
    try:
        with opener(urllib.request.Request(OPEN_LIBRARY.format(isbn=isbn),
                                           headers={"User-Agent": "hexu-library"}), timeout=timeout) as response:
            entry = json.loads(response.read(512_000).decode("utf-8")).get(f"ISBN:{isbn}") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    found = {}
    # Whole names, without machine tags such as 「award:hugo_award=2015」.
    subjects = [item.get("name", "") for item in entry.get("subjects", []) if isinstance(item, dict)]
    subjects = [name for name in subjects if name and len(name) <= 40 and not set(name) & set(":=")]
    if subjects:
        found["subjects"] = subjects[:8]
    publishers = [item.get("name", "") for item in entry.get("publishers", []) if isinstance(item, dict)]
    if publishers and publishers[0]:
        found["publisher"] = publishers[0][:60]
    if isinstance(entry.get("publish_date"), str):
        found["published"] = entry["publish_date"][:20]
    if isinstance(entry.get("number_of_pages"), int):
        found["pages"] = entry["number_of_pages"]
    return found


def epub_details(opf):
    """What an EPUB says about itself beyond title and author: ISBN, subjects, description,
    publisher and date. Tags in the description are dropped; nothing is fetched."""
    fields = {}
    for node in opf.iter():
        name = node.tag.split("}")[-1]
        if name in {"identifier", "subject", "description", "publisher", "date", "language"} and node.text:
            fields.setdefault(name, []).append(node.text.strip())
    details = {}
    isbn = next((isbn_of(value) for value in fields.get("identifier", []) if isbn_of(value)), "")
    if isbn:
        details["isbn"] = isbn
    subjects = [value[:20] for value in fields.get("subject", []) if value][:8]
    if subjects:
        details["subjects"] = subjects
    if fields.get("description"):
        details["description"] = " ".join(re.sub(r"<[^>]+>", " ", fields["description"][0]).split())[:300]
    if fields.get("publisher"):
        details["publisher"] = fields["publisher"][0][:60]
    if fields.get("date"):
        details["published"] = fields["date"][0][:10]
    return details


def import_document(filename, raw, title="", author=""):
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise SourceError("文件为空或超过 8 MiB")
    title = title.strip()[:160] or Path(filename).stem[:160]
    if filename.lower().endswith(".epub"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(item.file_size for item in entries) > 32 * 1024 * 1024 or any(item.file_size > 4 * 1024 * 1024 for item in entries):
                    raise SourceError("EPUB 解压体积超出限制")
                if "META-INF/encryption.xml" in archive.namelist():
                    raise SourceError("当前只支持没有加密/DRM 的 EPUB")
                container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
                opf_path = next(node.attrib["full-path"] for node in container.iter() if node.tag.endswith("rootfile"))
                opf = ElementTree.fromstring(archive.read(opf_path))
                metadata = {node.tag.split("}")[-1]: node.text for node in opf.iter() if node.tag.split("}")[-1] in {"title", "creator"} and node.text}
                details = epub_details(opf)
                title = title if title != Path(filename).stem else metadata.get("title", title)
                author = author or metadata.get("creator", "未知作者")
                manifest = {node.attrib["id"]: node.attrib["href"] for node in opf.iter() if node.tag.endswith("}item")}
                chapters = []
                for node in opf.iter():
                    if not node.tag.endswith("}itemref") or node.attrib.get("linear") == "no":
                        continue
                    href = manifest[node.attrib["idref"]].split("#")[0]
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
                    if target.startswith("../") or target.startswith("/"):
                        raise SourceError("EPUB 内部路径不合法")
                    document = Document(archive.read(target).decode("utf-8-sig"))
                    heading = next((clean(item.text()) for item in document.root.walk() if item.tag in {"h1", "h2", "h3"}), "第 %d 节" % (len(chapters) + 1))
                    text = clean(document.root.text())
                    if text:
                        chapters.append({"title": heading, "text": text})
        except (zipfile.BadZipFile, KeyError, StopIteration, ElementTree.ParseError, UnicodeError) as error:
            raise SourceError("EPUB 文件结构损坏或不受支持") from error
    elif filename.lower().endswith(".txt"):
        for encoding in (["utf-16"] if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeError:
                continue
        else:
            raise SourceError("TXT 编码无法识别，请转换为 UTF-8")
        chapters = split_text(text)
    else:
        raise SourceError("只支持 TXT 与无 DRM 的 EPUB")
    document = {"title": title, "author": author or "未知作者", "chapters": chapters, "source_id": "local", "source_key": hashlib.sha256(raw).hexdigest(), "source": "本地导入", "source_url": "", "license": "用户本地文件"}
    if filename.lower().endswith(".epub"):
        document.update(details)
    return document


class BookLibrary:
    def __init__(self, directory=None):
        self.directory = Path(directory or library_directory())
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        self.searches = SearchJobs(self)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, source_id TEXT, source_key TEXT,
                    title TEXT, slot INTEGER UNIQUE, metadata TEXT, UNIQUE(source_id,source_key));
                CREATE TABLE IF NOT EXISTS chapters(book_id TEXT, number INTEGER, title TEXT, body TEXT,
                    PRIMARY KEY(book_id,number));
                CREATE TABLE IF NOT EXISTS progress(book_id TEXT PRIMARY KEY, chapter INTEGER, offset INTEGER);
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, config TEXT);
                CREATE TABLE IF NOT EXISTS bookmarks(id INTEGER PRIMARY KEY, book_id TEXT, chapter INTEGER,
                    offset INTEGER, note TEXT, created_at INTEGER);
                CREATE TABLE IF NOT EXISTS source_health(id TEXT PRIMARY KEY, attempts INTEGER DEFAULT 0,
                    ok INTEGER DEFAULT 0, fail INTEGER DEFAULT 0, consecutive_fail INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0, last_error TEXT DEFAULT '', updated INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            """)
            # 上次打开过的 fake-IP 例外要保持；否则用户每次重启程序都得重新勾一次。
            set_fake_ip_allowed(self.setting("allow_fake_ip", "0") in {"1", "true", "True", "on"})
            # The furthest chapter ever reached: 小和's book answers stop there (no spoilers), and
            # turning back to reread an early chapter must not hide what was already read.
            try:
                db.execute("ALTER TABLE progress ADD COLUMN furthest INTEGER")
            except sqlite3.OperationalError:
                pass  # already there

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.directory / "library.sqlite", timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def sources(self):
        with self.connect() as db:
            return {row["id"]: json.loads(row["config"]) for row in db.execute("SELECT * FROM sources ORDER BY id")}

    def provider(self, identifier):
        if identifier == "wyshu":
            from wyshu_source import WyshuSource
            return WyshuSource()
        if identifier == "wikisource":
            return Wikisource()
        if identifier in BUILTIN_SOURCES:
            return BuiltinNovelSource(identifier)
        config = self.sources().get(identifier)
        if not config:
            raise SourceError("书源不存在")
        if not config.get("enabled", True):
            raise SourceError("书源已停用，请在书源管理中启用")
        return CssSource(identifier, config)

    def list_sources(self):
        health = self.health_map()
        def with_health(item):
            state = health.get(item["id"]) or {}
            item["health"] = {"attempts": int(state.get("attempts") or 0), "ok": int(state.get("ok") or 0),
                              "fail": int(state.get("fail") or 0),
                              "consecutive_fail": int(state.get("consecutive_fail") or 0),
                              "latency_ms": int(state.get("latency_ms") or 0),
                              "last_error": state.get("last_error") or ""}
            return item
        built_in = [{"id": key, "name": value["name"], "enabled": True,
                     "default_search": value.get("default_search", True),
                     "capabilities": {"search": True, "engines": ["CSS"]}, "builtin": True}
                    for key, value in BUILTIN_SOURCES.items()]
        return [*map(with_health, built_in), *[with_health(
            {"id": key, "name": value["name"], "enabled": value.get("enabled", True),
             "capabilities": {"search": value.get("capabilities", {}).get("search", True),
                              "engines": value.get("capabilities", {}).get("engines", ["CSS"]),
                              "java_ajax": bool(value.get("capabilities", {}).get("java_ajax")),
                              "needs_browser": bool(value.get("capabilities", {}).get("needs_browser")),
                              "header_note": value.get("capabilities", {}).get("header_note", "")}})
            for key, value in self.sources().items()]]

    def set_source_enabled(self, identifier, enabled):
        if not isinstance(enabled, bool):
            raise SourceError("启用状态必须为布尔值")
        with self.lock, self.connect() as db:
            row = db.execute("SELECT config FROM sources WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise SourceError("书源不存在或为内置书源")
            config = json.loads(row["config"])
            config["enabled"] = enabled
            db.execute("UPDATE sources SET config=? WHERE id=?", (json.dumps(config, ensure_ascii=False), identifier))
        return {"id": identifier, "enabled": enabled}

    def list_books(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT metadata FROM books ORDER BY slot")]

    def get(self, identifier, include_text=True):
        with self.connect() as db:
            row = db.execute("SELECT metadata FROM books WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise SourceError("本地书籍不存在")
            book = json.loads(row[0])
            columns = "number,title,body" if include_text else "number,title"
            book["chapters"] = [dict(item) for item in db.execute(f"SELECT {columns} FROM chapters WHERE book_id=? ORDER BY number", (identifier,))]
            progress = db.execute("SELECT chapter,offset FROM progress WHERE book_id=?", (identifier,)).fetchone()
            book["progress"] = dict(progress) if progress else {"chapter": 0, "offset": 0}
            return book

    def save(self, document):
        chapters = document.get("chapters", [])
        if not chapters or any(not item.get("text", "").strip() for item in chapters) or len(chapters) > 2000:
            raise SourceError("正文或章节为空，未入库")
        content = "\n\n".join(item["title"] + "\n\n" + item["text"] for item in chapters)
        if len(content) > 10_000_000:
            raise SourceError("正文超过 1000 万字")
        key = str(document["source_key"])
        identifier = hashlib.sha256((document["source_id"] + "\0" + key).encode()).hexdigest()[:24]
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT metadata FROM books WHERE id=?", (identifier,)).fetchone()
            if existing:
                return json.loads(existing[0])
            slot = next_slot({row[0] for row in db.execute("SELECT slot FROM books")})
            if slot is None:
                raise SourceError("本地书架位置已满")
            metadata = {key: value for key, value in document.items() if key != "chapters"}
            metadata.update(id=identifier, slot=slot, title=str(document["title"])[:160], author=str(document.get("author", "未知作者"))[:120],
                            chapter_count=len(chapters), characters=len(content),
                            synopsis=(document.get("description") or chapters[0]["text"])[:120],
                            sha256=hashlib.sha256(content.encode()).hexdigest(), created_at=int(time.time()))
            if not metadata["title"]:
                raise SourceError("书名不能为空")
            db.execute("INSERT INTO books VALUES(?,?,?,?,?,?)", (identifier, document["source_id"], key, metadata["title"], slot, json.dumps(metadata, ensure_ascii=False)))
            db.executemany("INSERT INTO chapters VALUES(?,?,?,?)", ((identifier, index, item["title"], item["text"]) for index, item in enumerate(chapters)))
            target = self.directory / (identifier + ".txt")
            temporary = target.with_suffix(".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(target)
        # A book that carries an ISBN is looked up once, in the background, to fill in what the
        # file left out. HEXU_METADATA_LOOKUP=0 turns it off; nothing but the ISBN is sent.
        if metadata.get("isbn") and os.environ.get("HEXU_METADATA_LOOKUP", "1") != "0":
            threading.Thread(target=self.enrich, args=(identifier,), daemon=True).start()
        return metadata

    def enrich(self, identifier, lookup=lookup_isbn):
        """Fill a book's missing subjects, publisher, date and pages from its ISBN, once. What the
        book's own file said is never overwritten. Returns the fields added."""
        with self.connect() as db:
            row = db.execute("SELECT metadata FROM books WHERE id=?", (identifier,)).fetchone()
        if not row:
            return {}
        metadata = json.loads(row[0])
        if not metadata.get("isbn") or metadata.get("looked_up"):
            return {}
        added = {key: value for key, value in lookup(metadata["isbn"]).items() if not metadata.get(key)}
        with self.lock, self.connect() as db:
            row = db.execute("SELECT metadata FROM books WHERE id=?", (identifier,)).fetchone()
            if not row:
                return {}
            current = json.loads(row[0])
            current.update(added, looked_up=int(time.time()))
            db.execute("UPDATE books SET metadata=? WHERE id=?", (json.dumps(current, ensure_ascii=False), identifier))
        return added

    def search(self, query, source_id="all"):
        query = query.strip()
        if not query or len(query) > 160:
            raise SourceError("请输入 1～160 字的书名")
        local = [book for book in self.list_books() if any(normalize(query) in normalize(title) for title in [book["title"], *book.get("aliases", [])])]
        if any(any(normalize(query) == normalize(title) for title in [book["title"], *book.get("aliases", [])]) for book in local):
            return {"local": local, "results": [], "errors": []}
        providers, errors = self.search_providers(source_id)
        if not providers:
            return {"local": local, "results": [], "errors": errors, "groups": []}
        candidates, search_errors = self.run_search(query, providers)
        return {"local": local, "results": candidates, "errors": [*errors, *search_errors],
                "groups": group_candidates(candidates, query, self.health_map())}

    def search_providers(self, source_id="all"):
        """参与检索的书源：默认全部启用且支持搜索的源，不再只取前五个。"""
        available, errors, providers = self.sources(), [], []
        if source_id != "all":
            if source_id in available and not available[source_id].get("capabilities", {}).get("search", True):
                return [], [{"source_id": source_id, "message": "此源不提供按书名搜索，请选择支持搜索的书源"}]
            if source_id not in available and source_id not in BUILTIN_SOURCES and source_id != "wikisource":
                return [], [{"source_id": source_id, "message": "书源不存在或已被移除"}]
            identifiers = [source_id]
        else:
            identifiers = [key for key, value in BUILTIN_SOURCES.items() if value.get("default_search", True)]
            identifiers += [key for key, value in available.items()
                            if value.get("enabled", True) and value.get("capabilities", {}).get("search", True)]
            identifiers = identifiers[:40]
        for identifier in identifiers:
            try:
                providers.append(self.provider(identifier))
            except (SourceError, ValueError, KeyError, TypeError) as error:
                config = BUILTIN_SOURCES.get(identifier) or available.get(identifier) or {}
                errors.append({"source_id": identifier, "source_name": config.get("name", identifier), "message": str(error)[:160]})
        return providers, errors

    def run_search(self, query, providers, timeout=None):
        """并发检索；每个源独立超时，结果按书源顺序归位，健康度写进 SQLite。"""
        import aggregate_search
        timeout = timeout or aggregate_search.SOURCE_TIMEOUT
        order = {provider.id: index for index, provider in enumerate(providers)}
        results, errors = [], []

        def search(provider):
            started = time.monotonic()
            try:
                return provider, provider.search(query) or [], None, int((time.monotonic() - started) * 1000)
            except (SourceError, ValueError, KeyError, TypeError) as error:
                return provider, [], str(error)[:160], int((time.monotonic() - started) * 1000)
            except Exception:
                return provider, [], "检索失败，请稍后重试或换源", int((time.monotonic() - started) * 1000)

        if not providers:
            return [], []
        pool = ThreadPoolExecutor(max_workers=min(aggregate_search.MAX_WORKERS, len(providers)))
        owners = {pool.submit(search, provider): provider for provider in providers}
        done, pending = wait(owners, timeout=timeout)
        for future in done:
            provider, found, message, latency = future.result()
            self.record_health(provider.id, not message, latency, message or "")
            results.extend(found)
            if message:
                errors.append({"source_id": provider.id, "source_name": getattr(provider, "name", provider.id), "message": message})
        for future in pending:
            provider = owners[future]
            future.cancel()
            self.record_health(provider.id, False, int(timeout * 1000), "响应超时")
            errors.append({"source_id": provider.id, "source_name": getattr(provider, "name", provider.id),
                           "message": "书源响应超时，请稍后重试或单独选择该书源"})
        pool.shutdown(wait=False)
        results.sort(key=lambda item: order.get(item.get("source_id"), 99))
        return results, errors

    def record_health(self, identifier, ok, latency_ms=0, message=""):
        if not isinstance(identifier, str) or not identifier:
            return
        with self.connect() as db:
            db.execute("""INSERT INTO source_health(id, attempts, ok, fail, consecutive_fail, latency_ms, last_error, updated)
                          VALUES(?,1,?,?,?,?,?,?)
                          ON CONFLICT(id) DO UPDATE SET attempts=attempts+1, ok=ok+excluded.ok, fail=fail+excluded.fail,
                          consecutive_fail=CASE WHEN excluded.ok>0 THEN 0 ELSE consecutive_fail+1 END,
                          latency_ms=CASE WHEN excluded.latency_ms>0 THEN excluded.latency_ms ELSE latency_ms END,
                          last_error=excluded.last_error, updated=excluded.updated""",
                       (identifier, 1 if ok else 0, 0 if ok else 1, 0 if ok else 1,
                        int(latency_ms or 0), message[:160], int(time.time())))

    def setting(self, key, default=""):
        try:
            with self.connect() as db:
                row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        except sqlite3.Error:
            return default
        return row[0] if row else default

    def set_setting(self, key, value):
        if not isinstance(key, str) or len(key) > 60:
            raise SourceError("设置项不合法")
        stored = "1" if value in {True, 1, "1", "true", "True", "on"} else "0"
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, stored))
        if key == "allow_fake_ip":
            set_fake_ip_allowed(stored == "1")
        return {key: stored}

    def allow_fake_ip(self):
        return self.setting("allow_fake_ip", "0") == "1"

    def health_map(self):
        try:
            with self.connect() as db:
                return {row["id"]: dict(row) for row in db.execute("SELECT * FROM source_health")}
        except sqlite3.Error:
            return {}

    def probe_source(self, identifier, query="三体"):
        """给单个书源做一次真实体检：能不能连通、多快、能不能解析出书名。"""
        try:
            provider = self.provider(identifier)
        except (SourceError, ValueError, KeyError, TypeError) as error:
            return {"id": identifier, "ok": False, "count": 0, "latency_ms": 0, "message": str(error)[:160]}
        started = time.monotonic()
        try:
            found = provider.search(query) or []
        except Exception as error:
            message = str(error)[:160] if isinstance(error, (SourceError, ValueError)) else "书源请求失败"
            self.record_health(provider.id, False, int((time.monotonic() - started) * 1000), message)
            return {"id": provider.id, "name": provider.name, "ok": False, "count": 0,
                    "latency_ms": int((time.monotonic() - started) * 1000), "message": message}
        latency = int((time.monotonic() - started) * 1000)
        self.record_health(provider.id, True, latency, "")
        return {"id": provider.id, "name": provider.name, "ok": True, "count": len(found), "latency_ms": latency,
                "message": "可用" if found else "能连上，但这个书名没有结果", "sample": [item.get("title", "") for item in found[:4]]}

    def import_sources_from_url(self, url):
        """从公开 URL 直接导入书源 JSON（源仓库、GitHub raw、Gist 都可以）。"""
        if not isinstance(url, str) or not re.match(r"^https?://", url.strip(), re.I):
            raise SourceError("请填写书源 JSON 的 http(s) 地址")
        url = url.strip()
        host = urlsplit(url).hostname
        if not host:
            raise SourceError("书源地址缺少域名")
        validate_url(url, host)
        raw = fetch(url, host)
        try:
            data = json.loads(raw.replace("\ufeff", ""))
        except ValueError as error:
            raise SourceError("这个地址返回的不是 JSON 书源文件") from error
        return self.add_sources(data)

    def start_download(self, candidate):
        provider = self.provider(candidate.get("source_id"))
        key = candidate.get("source_key")
        if not isinstance(key, str) or len(key) > 2048:
            raise SourceError("下载目标无效")
        # 同一本书可能有多个源；主源失败时按给定顺序换源，最多再试两个。
        attempts = [(provider, key)]
        for alternate in (candidate.get("alternates") or [])[:2]:
            if not isinstance(alternate, dict) or not isinstance(alternate.get("source_key"), str):
                continue
            try:
                attempts.append((self.provider(alternate.get("source_id")), alternate["source_key"][:2048]))
            except (SourceError, ValueError, KeyError, TypeError):
                continue
        with self.lock:
            for job in self.jobs.values():
                if job["source_id"] == provider.id and job["source_key"] == key and job["state"] in {"queued", "downloading"}:
                    return {key: value for key, value in job.items() if key != "cancel"}
            if sum(job["state"] in {"queued", "downloading"} for job in self.jobs.values()) >= 2:
                raise SourceError("已有两个下载任务，请等待或取消")
            if len(self.jobs) >= 64:
                for identifier in list(self.jobs):
                    if self.jobs[identifier]["state"] not in {"queued", "downloading"}:
                        del self.jobs[identifier]
                        break
            identifier = uuid.uuid4().hex
            job = {"id": identifier, "state": "queued", "source_id": provider.id, "source_key": key, "done": 0, "total": 0, "message": "正在连接书源", "cancel": threading.Event()}
            self.jobs[identifier] = job
        def work():
            failures = []
            try:
                with self.lock:
                    job["state"] = "downloading"
                def report(done, total, title):
                    with self.lock:
                        job.update(done=done, total=total, message="正在下载：" + title)
                document = None
                for attempt, alternate_key in attempts:
                    if job["cancel"].is_set():
                        raise SourceError("已取消下载")
                    started = time.monotonic()
                    try:
                        with self.lock:
                            job.update(source_id=attempt.id, source_key=alternate_key, message="正在连接：" + getattr(attempt, "name", attempt.id))
                        document = attempt.download(alternate_key, report, job["cancel"].is_set)
                        self.record_health(attempt.id, True, int((time.monotonic() - started) * 1000), "")
                        break
                    except Exception as error:
                        message = str(error)[:160] if isinstance(error, (SourceError, ValueError)) else "下载失败"
                        self.record_health(attempt.id, False, int((time.monotonic() - started) * 1000), message)
                        failures.append(message)
                        document = None
                if document is None:
                    raise SourceError(failures[0] if failures else "下载失败，未保存不完整正文")
                if job["cancel"].is_set():
                    raise SourceError("已取消下载")
                document["title"] = document.get("title") or str(candidate.get("title", "未命名书籍"))[:160]
                document["author"] = document.get("author") or str(candidate.get("author", "未知作者"))[:120]
                document["aliases"] = [value[:160] for value in candidate.get("aliases", [])[:8] if isinstance(value, str)]
                saved = self.save(document)
                with self.lock:
                    job.update(state="completed", book=saved, done=job["total"], message="正文已下载并入库")
            except Exception as error:
                with self.lock:
                    job.update(state="cancelled" if job["cancel"].is_set() else "failed",
                               message=str(error)[:200] if isinstance(error, (SourceError, ValueError)) else "下载失败，未保存不完整正文，请换源或重试")
        threading.Thread(target=work, daemon=True).start()
        return self.job(identifier)

    def job(self, identifier, cancel=False):
        with self.lock:
            if identifier not in self.jobs:
                raise SourceError("下载任务不存在或服务已重启，请重新检索")
            job = self.jobs[identifier]
            if cancel:
                job["cancel"].set()
            return {key: value for key, value in job.items() if key != "cancel"}

    def add_sources(self, data):
        items = data if isinstance(data, list) else [data]
        if len(items) > 50:
            raise SourceError("每次最多导入 50 个书源")
        accepted, rejected = [], []
        with self.connect() as db:
            for item in items:
                try:
                    config = normalize_source(item)
                    config["enabled"] = item.get("enabled", True) is not False
                    identifier = hashlib.sha256(config["base_url"].encode()).hexdigest()[:16]
                    db.execute("INSERT OR REPLACE INTO sources VALUES(?,?)", (identifier, json.dumps(config, ensure_ascii=False)))
                    accepted.append({"id": identifier, "name": config["name"], "enabled": config["enabled"], "capabilities": config["capabilities"]})
                except (SourceError, TypeError, AttributeError) as error:
                    rejected.append({"name": str(item.get("bookSourceName", item.get("name", "书源")))[:80] if isinstance(item, dict) else "书源", "message": str(error)[:200]})
        return {"accepted": accepted, "rejected": rejected}

    def progress(self, identifier, chapter, offset):
        book = self.get(identifier, False)
        if not isinstance(chapter, int) or not 0 <= chapter < len(book["chapters"]) or not isinstance(offset, int) or not 0 <= offset <= 10_000_000:
            raise SourceError("阅读进度参数不合法")
        with self.connect() as db:
            db.execute("""INSERT INTO progress(book_id, chapter, offset, furthest) VALUES(?,?,?,?)
                          ON CONFLICT(book_id) DO UPDATE SET chapter=excluded.chapter, offset=excluded.offset,
                          furthest=MAX(COALESCE(furthest, chapter), excluded.chapter)""",
                       (identifier, chapter, offset, chapter))
        return {"ok": True}

    MAX_BOOKMARKS = 50  # per book; the oldest goes first

    def add_bookmark(self, identifier, note=""):
        """A bookmark where the reader is now (the saved reading position), with an optional note
        of up to 40 characters. Returns it, with the chapter title for saying it back."""
        book = self.get(identifier, False)
        note = " ".join(note.split())[:40] if isinstance(note, str) else ""
        chapter, offset = int(book["progress"]["chapter"]), int(book["progress"]["offset"])
        with self.connect() as db:
            cursor = db.execute("INSERT INTO bookmarks(book_id, chapter, offset, note, created_at) VALUES(?,?,?,?,?)",
                                (identifier, chapter, offset, note, int(time.time())))
            db.execute("""DELETE FROM bookmarks WHERE book_id=? AND id NOT IN
                          (SELECT id FROM bookmarks WHERE book_id=? ORDER BY id DESC LIMIT ?)""",
                       (identifier, identifier, self.MAX_BOOKMARKS))
        return {"id": cursor.lastrowid, "chapter": chapter, "offset": offset, "note": note,
                "chapter_title": book["chapters"][chapter]["title"] if chapter < len(book["chapters"]) else ""}

    def bookmarks(self, identifier):
        """A book's bookmarks, oldest first, each with its chapter title."""
        titles = {item["number"]: item["title"] for item in self.get(identifier, False)["chapters"]}
        with self.connect() as db:
            rows = db.execute("SELECT id, chapter, offset, note, created_at FROM bookmarks WHERE book_id=? ORDER BY id",
                              (identifier,)).fetchall()
        return [{**dict(row), "chapter_title": titles.get(row["chapter"], "")} for row in rows]

    def read_up_to(self, identifiers):
        """{book id: furthest chapter reached} for the given books the reader has opened; a book
        never opened is absent (nothing read yet, so nothing to protect from spoilers)."""
        identifiers = [item for item in identifiers if isinstance(item, str)]
        if not identifiers:
            return {}
        marks = ",".join("?" * len(identifiers))
        with self.connect() as db:
            rows = db.execute(f"SELECT book_id, COALESCE(furthest, chapter) AS furthest FROM progress "
                              f"WHERE book_id IN ({marks})", identifiers).fetchall()
        return {row["book_id"]: int(row["furthest"]) for row in rows}


_instance = None
_instance_lock = threading.Lock()


def instance():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = BookLibrary()
    return _instance


def handle_request(handler):
    """Shared by the desktop/Python service and the npm-start sidecar."""
    url = urlsplit(handler.path)
    if not url.path.startswith("/library/"):
        return False
    def reply(status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(data)
    try:
        library = instance()
        query = parse_qs(url.query)
        if handler.command == "GET":
            if url.path == "/library/ready":
                reply(200, {"ready": True, "directory": str(library.directory)})
            elif url.path == "/library/books":
                reply(200, {"books": library.list_books()})
            elif url.path == "/library/search":
                reply(200, library.search(query.get("q", [""])[0], query.get("source", ["all"])[0]))
            elif url.path.startswith("/library/search/jobs/"):
                reply(200, library.searches.get(url.path.rsplit("/", 1)[-1]))
            elif url.path.startswith("/library/books/"):
                reply(200, library.get(url.path.rsplit("/", 1)[-1]))
            elif url.path.startswith("/library/jobs/"):
                reply(200, library.job(url.path.rsplit("/", 1)[-1]))
            elif url.path == "/library/sources":
                reply(200, {"sources": library.list_sources(), "allow_fake_ip": library.allow_fake_ip()})
            else:
                reply(404, {"error": "接口不存在"})
        elif handler.command == "POST":
            origin = handler.headers.get("Origin")
            if origin and urlsplit(origin).netloc != handler.headers.get("Host"):
                # Read a small body first: closing a Windows socket with unread data resets the
                # connection, and the page would see an abort instead of this refusal.
                pending = handler.headers.get("Content-Length", "0")
                if pending.isdigit() and 0 < int(pending) <= 65_536:
                    handler.rfile.read(int(pending))
                reply(403, {"error": "拒绝跨站修改本地书库"})
                handler.close_connection = True
                return True
            length = int(handler.headers.get("Content-Length", "0"))
            if not 0 < length <= 12 * 1024 * 1024 or not handler.headers.get("Content-Type", "").startswith("application/json"):
                reply(413, {"error": "请求体过大或不是 JSON"})
                handler.close_connection = True
                return True
            body = json.loads(handler.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise SourceError("请求必须为 JSON 对象")
            if url.path == "/library/download":
                reply(202, library.start_download(body))
            elif url.path == "/library/search/jobs":
                query_text = str(body.get("q", "")).strip()
                if not query_text or len(query_text) > 160:
                    raise SourceError("请输入 1～160 字的书名")
                reply(202, library.searches.start(query_text, str(body.get("source", "all"))))
            elif url.path.startswith("/library/search/jobs/"):
                reply(200, library.searches.get(url.path.rsplit("/", 1)[-1], cancel=True))
            elif url.path == "/library/settings":
                key = str(body.get("key", ""))[:60]
                if key != "allow_fake_ip":
                    raise SourceError("不支持这个设置项")
                reply(200, library.set_setting(key, body.get("value")))
            elif url.path == "/library/sources/import-url":
                reply(200, library.import_sources_from_url(body.get("url")))
            elif url.path.startswith("/library/sources/") and url.path.endswith("/probe"):
                reply(200, library.probe_source(url.path.rsplit("/", 2)[-2], str(body.get("q", "三体"))))
            elif url.path.startswith("/library/sources/"):
                reply(200, library.set_source_enabled(url.path.rsplit("/", 1)[-1], body.get("enabled")))
            elif url.path == "/library/import":
                raw = base64.b64decode(body.get("data", ""), validate=True)
                reply(200, library.save(import_document(body.get("filename", ""), raw, body.get("title", ""), body.get("author", ""))))
            elif url.path == "/library/sources":
                reply(200, library.add_sources(body.get("sources")))
            elif url.path.startswith("/library/jobs/"):
                reply(200, library.job(url.path.rsplit("/", 1)[-1], cancel=True))
            elif url.path.startswith("/library/progress/"):
                reply(200, library.progress(url.path.rsplit("/", 1)[-1], body.get("chapter"), body.get("offset")))
            else:
                reply(404, {"error": "接口不存在"})
    except (SourceError, ValueError, TypeError, KeyError, UnicodeError) as error:
        reply(400, {"error": str(error)[:200]})
    except Exception:
        reply(500, {"error": "本地书库操作失败，请检查数据目录权限"})
    return True
