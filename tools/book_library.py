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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

from book_sources import CssSource, Document, SourceError, Wikisource, clean, normalize_source, split_chapters as split_text


def library_directory():
    override = os.environ.get("HEXU_BOOK_LIBRARY_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".local" / "share")))
    return base / "hexu-library" / "books"


def normalize(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


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
    return {"title": title, "author": author or "未知作者", "chapters": chapters, "source_id": "local", "source_key": hashlib.sha256(raw).hexdigest(), "source": "本地导入", "source_url": "", "license": "用户本地文件"}


class BookLibrary:
    def __init__(self, directory=None):
        self.directory = Path(directory or library_directory())
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, source_id TEXT, source_key TEXT,
                    title TEXT, slot INTEGER UNIQUE, metadata TEXT, UNIQUE(source_id,source_key));
                CREATE TABLE IF NOT EXISTS chapters(book_id TEXT, number INTEGER, title TEXT, body TEXT,
                    PRIMARY KEY(book_id,number));
                CREATE TABLE IF NOT EXISTS progress(book_id TEXT PRIMARY KEY, chapter INTEGER, offset INTEGER);
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, config TEXT);
            """)

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
        if identifier == "wikisource":
            return Wikisource()
        config = self.sources().get(identifier)
        if not config:
            raise SourceError("书源不存在")
        if not config.get("enabled", True):
            raise SourceError("书源已停用，请在书源管理中启用")
        return CssSource(identifier, config)

    def list_sources(self):
        built_in = {"id": "wikisource", "name": Wikisource.name, "enabled": True,
                    "capabilities": {"search": True, "url_import": False, "engines": []}, "builtin": True}
        return [built_in, *[{"id": key, "name": value["name"], "enabled": value.get("enabled", True),
                            "capabilities": value.get("capabilities", {"search": True, "url_import": True, "engines": ["CSS"]})}
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

    def preview_url(self, url, source_id="all"):
        if not isinstance(url, str) or not 0 < len(url) <= 2048:
            raise SourceError("请输入有效的书籍目录网址")
        host = urlsplit(url).hostname
        sources = self.sources()
        matches = [key for key, value in sources.items() if value.get("enabled", True) and value.get("capabilities", {}).get("url_import", True)
                   and urlsplit(value["base_url"]).hostname == host and (source_id == "all" or source_id == key)]
        if not matches:
            raise SourceError("没有已启用且匹配此网址的书源；请先导入对应书源并勾选启用")
        return self.provider(matches[0]).preview(url)

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
            slot = db.execute("SELECT COALESCE(MAX(slot),-1)+1 FROM books").fetchone()[0]
            if slot >= 11000:
                raise SourceError("本地书架位置已满")
            metadata = {key: value for key, value in document.items() if key != "chapters"}
            metadata.update(id=identifier, slot=slot, title=str(document["title"])[:160], author=str(document.get("author", "未知作者"))[:120],
                            chapter_count=len(chapters), characters=len(content), synopsis=chapters[0]["text"][:120],
                            sha256=hashlib.sha256(content.encode()).hexdigest(), created_at=int(time.time()))
            if not metadata["title"]:
                raise SourceError("书名不能为空")
            db.execute("INSERT INTO books VALUES(?,?,?,?,?,?)", (identifier, document["source_id"], key, metadata["title"], slot, json.dumps(metadata, ensure_ascii=False)))
            db.executemany("INSERT INTO chapters VALUES(?,?,?,?)", ((identifier, index, item["title"], item["text"]) for index, item in enumerate(chapters)))
            target = self.directory / (identifier + ".txt")
            temporary = target.with_suffix(".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(target)
            return metadata

    def search(self, query, source_id="all"):
        query = query.strip()
        if not query or len(query) > 160:
            raise SourceError("请输入 1～160 字的书名")
        local = [book for book in self.list_books() if any(normalize(query) in normalize(title) for title in [book["title"], *book.get("aliases", [])])]
        if any(any(normalize(query) == normalize(title) for title in [book["title"], *book.get("aliases", [])]) for book in local):
            return {"local": local, "results": [], "errors": []}
        candidates, errors = [], []
        available = self.sources()
        providers = [source_id] if source_id != "all" else [key for key, value in available.items()
            if value.get("enabled", True) and value.get("capabilities", {}).get("search", True)][:5] + ["wikisource"]
        if source_id in available and not available[source_id].get("capabilities", {}).get("search", True):
            return {"local": local, "results": [], "errors": [{"source_id": source_id, "message": "此源支持网址导入，不提供按书名搜索；请粘贴书籍目录网址"}]}
        def search_source(identifier):
            try:
                return self.provider(identifier).search(query), None
            except (SourceError, ValueError, KeyError, TypeError) as error:
                return [], {"source_id": identifier, "message": str(error)[:160]}
        with ThreadPoolExecutor(max_workers=6) as pool:
            for result, error in pool.map(search_source, providers):
                candidates.extend(result)
                if error:
                    errors.append(error)
        return {"local": local, "results": candidates, "errors": errors}

    def start_download(self, candidate):
        provider = self.provider(candidate.get("source_id"))
        key = candidate.get("source_key")
        if not isinstance(key, str) or len(key) > 2048:
            raise SourceError("下载目标无效")
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
            try:
                with self.lock:
                    job["state"] = "downloading"
                def report(done, total, title):
                    with self.lock:
                        job.update(done=done, total=total, message="正在下载：" + title)
                document = provider.download(key, report, job["cancel"].is_set)
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
                    job.update(state="cancelled" if job["cancel"].is_set() else "failed", message=str(error)[:200] if isinstance(error, (SourceError, ValueError)) else "下载失败，未保存不完整正文，请换源或重试")
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
            db.execute("INSERT OR REPLACE INTO progress VALUES(?,?,?)", (identifier, chapter, offset))
        return {"ok": True}


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
            elif url.path.startswith("/library/books/"):
                reply(200, library.get(url.path.rsplit("/", 1)[-1]))
            elif url.path.startswith("/library/jobs/"):
                reply(200, library.job(url.path.rsplit("/", 1)[-1]))
            elif url.path == "/library/sources":
                reply(200, {"sources": library.list_sources()})
            else:
                reply(404, {"error": "接口不存在"})
        elif handler.command == "POST":
            origin = handler.headers.get("Origin")
            if origin and urlsplit(origin).netloc != handler.headers.get("Host"):
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
            elif url.path == "/library/url":
                reply(200, library.preview_url(body.get("url"), body.get("source_id", "all")))
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
