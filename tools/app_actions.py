"""The library actions 小和's model may ask for in a conversation ("tool calling").

A short whitelist, offered only when it makes sense in the current state, with every argument
checked here before anything happens:

    set_sky          day / night / auto (the clock)                       any time
    search_library   find books by title or author: the local library,    any time
                     and the online sources when asked (online: true)
    fetch_book       an HX number of a book in the local library          while idle
    locate_book      show where a local book stands on the shelf          while idle
    download_book    one of this turn's online search results; the page   while idle
                     asks the reader first and downloads only on a yes
    open_chapter     chapter number of the book being read                while reading
    reading_music    play / pause                                         while reading
    set_font_size    larger / smaller / default                           while reading
    add_bookmark     where the reader is now, with an optional note       while reading
    list_bookmarks   the bookmarks of the book being read                 while reading
    open_bookmark    one of those bookmarks                               while reading

After fetch_book, open_chapter and reading_music are offered for that book too, so 「取《三体》
翻到第三章」 is one turn: the chapter is checked against the book being fetched, and the page runs
the step once the book is in the reader's hands (action "after": "arrival").

The page carries out an action (src/app/assistant.js) and checks it once more; searches and
bookmarks are answered here from the reading library, and only change data the reader can see
and delete. An invalid call is answered to the model as an error, so it can tell the reader what
went wrong. The server never moves anything on the page itself.
"""
import json

MAX_ACTIONS = 3
CATALOG_LINES = 40  # books listed for fetch_book; beyond this the prompt would cost too much
SEARCH_RESULTS = 5


def tool(name, description, properties=None, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": list(required),
                       "additionalProperties": False}}}


SKY = tool("set_sky", "切换图书馆窗外的天空。day=太阳白天，night=月亮夜晚，auto=按电脑时间自动。只在读者明确要求切换白天、夜晚或自动时调用。",
           {"mode": {"type": "string", "enum": ["day", "night", "auto"]}}, ["mode"])
MUSIC = tool("reading_music", "播放或暂停阅读时的背景音乐。只在读者明确要求时调用。",
             {"action": {"type": "string", "enum": ["play", "pause"]}}, ["action"])
CHAPTER = tool("open_chapter", "把正在阅读（或刚取出）的书翻到第几章（从 1 开始数）。只在读者明确要求翻到某一章时调用。",
               {"chapter": {"type": "integer", "minimum": 1}}, ["chapter"])
FETCH = tool("fetch_book", "让小和从书架取出一本已入库的书交给读者。bookId 只能用系统提示里本机书库清单中的 HX 编号。只在读者明确想读、想取某本书时调用；"
             "读者同时要求翻到某章或放音乐时，取书后再调用 open_chapter 或 reading_music。",
             {"bookId": {"type": "string", "pattern": "^HX-\\d{5}$"}}, ["bookId"])
LOCATE = tool("locate_book", "让镜头转到一本已入库的书在书架上的位置，书留在架上。只在读者问某本书放在哪里、想看看它在哪时调用。",
              {"bookId": {"type": "string", "pattern": "^HX-\\d{5}$"}}, ["bookId"])
SEARCH = tool("search_library", "按书名或作者查找书。先查本机书库；读者想要的书本机没有、并且想下载时，再设 online=true 查在线书源（较慢）。"
              "只返回候选清单，不会下载任何东西。",
              {"query": {"type": "string", "minLength": 1, "maxLength": 40}, "online": {"type": "boolean"}}, ["query"])
DOWNLOAD = tool("download_book", "下载一本在线书源里的书并上架。candidate 只能是本轮 search_library 在线结果里的编号（如 C1）。"
                "界面会先问读者是否下载，读者同意后才下载；告诉读者需要确认，不要说已经下载好了。",
                {"candidate": {"type": "string", "pattern": "^C\\d$"}}, ["candidate"])
FONT = tool("set_font_size", "调整正文的字号：larger 放大一档，smaller 缩小一档，default 恢复默认。只在读者明确要求时调用。",
            {"size": {"type": "string", "enum": ["larger", "smaller", "default"]}}, ["size"])
BOOKMARK_ADD = tool("add_bookmark", "在读者现在读到的位置加一个书签，可附一句不超过二十字的备注。只在读者明确要求加书签、做记号时调用。",
                    {"note": {"type": "string", "maxLength": 40}})
BOOKMARK_LIST = tool("list_bookmarks", "列出正在读的这本书的书签。读者问有哪些书签、上次标记在哪时调用。")
BOOKMARK_OPEN = tool("open_bookmark", "翻到正在读的这本书的某个书签。id 只能来自 list_bookmarks 的结果。",
                     {"id": {"type": "integer", "minimum": 1}}, ["id"])
RECOMMEND = tool("recommend_books", "从本机书库里推荐至多三本书，附推荐理由。like 是读者描述的口味（如“轻松一点的科幻”），"
                 "bookId 是读者说“像这本的”那一本；都不给时按读者最近读过的书推荐。只能推荐结果里的书，不要推荐书库里没有的书。",
                 {"like": {"type": "string", "maxLength": 40}, "bookId": {"type": "string", "pattern": "^HX-\\d{5}$"}})
PAGE_ACTIONS = {"set_sky", "reading_music", "open_chapter", "fetch_book", "locate_book", "download_book",
                "set_font_size", "open_bookmark"}
NAMES = PAGE_ACTIONS | {"search_library", "add_bookmark", "list_bookmarks", "recommend_books"}
RECOMMENDATIONS = 3
CLOSE_VECTOR = 0.62  # cosine at which two books' descriptions count as close (see book_text_search)
CLOSE_WORDS = 0.25
_signatures = {}  # (book id, signature text) -> vector, shared by every turn


def signature(book):
    """What a book is about, in one line: title, author, subjects and synopsis."""
    return " ".join([book.get("title", ""), book.get("author", ""), " ".join(book.get("subjects") or []),
                     (book.get("description") or book.get("synopsis") or "")[:120]]).strip()


def pairs(text):
    return {text[i:i + 2] for i in range(len(text) - 1) if not text[i:i + 2].isspace()}


class AppActions:
    """What this conversation turn may do.

    phase: the page's state; reading: the book being read as describe_book() reports it (with
    "chapters"), or None; reading_id: its id in the reading library; catalog: HX number -> local
    book; library: the reading library (book_library.BookLibrary), for searches and bookmarks."""

    def __init__(self, phase, reading=None, catalog=None, *, reading_id=None, library=None, embedder=None,
                 recent=()):
        self.phase = phase
        self.reading = reading
        self.reading_id = reading_id
        self.catalog = catalog or {}
        self.library = library
        self.embedder = embedder if embedder is not None and embedder.state()[0] else None
        self.recent = [book_id for book_id in recent if isinstance(book_id, str)][:3]  # local ids, newest first
        self.count = 0
        self.incoming = None  # the book fetched this turn: {"bookId", "chapters"}
        self.candidates = {}  # this turn's online search results by "C1".."C5"
        self.bookmark_ids = set()

    @property
    def tools(self):
        """Offered now. Recomputed each round: fetching a book opens its chapters and music."""
        offered = [SKY]
        if self.library:
            offered.append(SEARCH)
        if len(self.catalog) >= 2:
            offered.append(RECOMMEND)
        reading = self.phase == "READING" and self.reading
        if reading or self.incoming:
            offered += [MUSIC, CHAPTER]
        if reading:
            offered.append(FONT)
            if self.library and self.reading_id:
                offered += [BOOKMARK_ADD, BOOKMARK_LIST, BOOKMARK_OPEN]
        if self.phase == "IDLE" and not self.incoming:
            if self.catalog:
                offered += [FETCH, LOCATE]
            if self.candidates:
                offered.append(DOWNLOAD)
        return offered

    def handles(self, name):
        return name in NAMES

    def prompt(self):
        text = ("你可以调用界面工具（" + "、".join(tool["function"]["name"] for tool in self.tools) + "）替读者操作图书馆，"
                "但只在读者明确提出要求时调用；调用后用一句话告诉读者做了什么，不要假装做了没调用的操作。")
        if self.phase == "IDLE" and self.catalog:
            lines = [f"{key} | {book.get('title', '')} | {book.get('author', '')}"
                     + (f" | {'、'.join(book['subjects'][:2])}" if book.get("subjects") else "")
                     for key, book in list(self.catalog.items())[:CATALOG_LINES]]
            text += "本机书库（编号 | 书名 | 作者 | 分类，有的话）：" + "；".join(lines) + "。"
        return text

    def execute(self, name, arguments):
        """(action for the page or None, result for the model)."""
        if self.count >= MAX_ACTIONS:
            return None, {"error": "本轮操作次数已达上限"}
        if name not in {tool["function"]["name"] for tool in self.tools}:
            return None, {"error": "当前状态下不能执行这个操作"}
        try:
            args = json.loads(arguments) if isinstance(arguments, str) and len(arguments) <= 2000 else None
        except ValueError:
            args = None
        if not isinstance(args, dict):
            return None, {"error": "参数格式不正确"}
        handler = getattr(self, "_" + name)
        try:
            action, result = handler(args)
        except (KeyError, TypeError, ValueError) as error:
            return None, {"error": f"参数不正确：{error}"[:120]}
        if action is None and "error" in result:
            return None, result
        self.count += 1
        if action is None:
            return None, result
        return {"type": "action", "name": name, "args": action}, result

    # --- page actions --------------------------------------------------------
    def _set_sky(self, args):
        if args.get("mode") not in ("day", "night", "auto"):
            return None, {"error": "参数不正确"}
        return {"mode": args["mode"]}, {"ok": True, "done": "界面会立即执行"}

    def _reading_music(self, args):
        if args.get("action") not in ("play", "pause"):
            return None, {"error": "参数不正确"}
        if self.incoming:
            return ({"action": args["action"], "after": "arrival"},
                    {"ok": True, "done": "还没有执行：书到读者手上后才执行，不要说已经做了"})
        return {"action": args["action"]}, {"ok": True, "done": "界面会立即执行"}

    def _open_chapter(self, args):
        chapter = args.get("chapter")
        total = int((self.incoming or self.reading or {}).get("chapters", 0))
        if type(chapter) is not int or not 1 <= chapter <= total:
            return None, {"error": f"这本书只有 {total} 章"}
        if self.incoming:
            return {"chapter": chapter, "after": "arrival"}, {"ok": True, "done": "还没有翻：书到读者手上后才翻到这一章；你没读过这一章，不要描述它的内容"}
        return {"chapter": chapter}, {"ok": True, "done": "界面会立即执行"}

    def _fetch_book(self, args):
        book = self.catalog.get(args.get("bookId"))
        if not book:
            return None, {"error": "本机书库里没有这个编号"}
        self.incoming = {"bookId": args["bookId"], "chapters": int(book.get("chapter_count") or 0)}
        return ({"bookId": args["bookId"], "title": book.get("title", "")},
                {"ok": True, "done": "还没有取：小和说完这句话才出发去取，告诉读者这就去取，不要说已经取来",
                 "chapters": self.incoming["chapters"]})

    def _locate_book(self, args):
        book = self.catalog.get(args.get("bookId"))
        if not book:
            return None, {"error": "本机书库里没有这个编号"}
        return {"bookId": args["bookId"], "title": book.get("title", "")}, {"ok": True, "done": "镜头会转到这本书"}

    def _download_book(self, args):
        candidate = self.candidates.get(args.get("candidate"))
        if not candidate:
            return None, {"error": "没有这个候选，请先用 search_library 在线查找"}
        return ({"candidate": candidate},
                {"ok": True, "done": "界面已请读者确认，读者同意后才会下载；请告诉读者需要确认"})

    def _set_font_size(self, args):
        if args.get("size") not in ("larger", "smaller", "default"):
            return None, {"error": "参数不正确"}
        return {"size": args["size"]}, {"ok": True, "done": "界面会立即执行"}

    def _open_bookmark(self, args):
        identifier = args.get("id")
        found = next((item for item in self.library.bookmarks(self.reading_id) if item["id"] == identifier), None)
        if not found:
            return None, {"error": "这本书没有这个书签，请先用 list_bookmarks 查看"}
        return ({"chapter": found["chapter"] + 1, "offset": found["offset"]},
                {"ok": True, "done": f"翻到第 {found['chapter'] + 1} 章的书签处"})

    # --- answered here ---------------------------------------------------------
    def _search_library(self, args):
        query = args.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 40:
            return None, {"error": "请给出书名或作者"}
        query = query.strip()
        numbers = {book.get("id"): key for key, book in self.catalog.items()}
        local = [{"bookId": numbers.get(book["id"]), "title": book.get("title", ""), "author": book.get("author", "")}
                 for book in self.library.list_books()
                 if query in book.get("title", "") or query in book.get("author", "")][:SEARCH_RESULTS]
        result = {"local": local}
        if args.get("online") is True:
            found = self.library.search(query)
            self.candidates = {}
            for index, item in enumerate(found.get("results", [])[:SEARCH_RESULTS], start=1):
                self.candidates[f"C{index}"] = {key: item.get(key) for key in
                                                ("title", "author", "source_id", "source_key", "source")}
            result["online"] = [{"candidate": key, "title": item["title"], "author": item.get("author", ""),
                                 "source": item.get("source", "")} for key, item in self.candidates.items()]
            if found.get("errors"):
                result["failed_sources"] = len(found["errors"])
        return None, result

    def _recommend_books(self, args):
        """Up to RECOMMENDATIONS local books like the reader's description, a given book, or what
        they read lately, best first, each with a reason. Only books of this library."""
        like = args.get("like") if isinstance(args.get("like"), str) else ""
        numbers = {book.get("id"): key for key, book in self.catalog.items()}
        seed_number = args.get("bookId")
        if seed_number and seed_number not in self.catalog:
            return None, {"error": "本机书库里没有这个编号"}
        seeds = [self.catalog[seed_number]] if seed_number else []
        if not seeds and not like:
            seeds = [self.catalog[numbers[book_id]] for book_id in self.recent if book_id in numbers]
        if not seeds and not like:
            return None, {"error": "还不知道读者的口味：请问读者想看什么样的书"}
        excluded = {book.get("id") for book in seeds} | {self.reading_id}
        candidates = [(key, book) for key, book in self.catalog.items() if book.get("id") not in excluded]
        if not candidates:
            return None, {"error": "书库里没有别的书可以推荐"}
        wanted = " ".join([like, *(signature(book) for book in seeds)]).strip()
        seed_subjects = {subject for book in seeds for subject in book.get("subjects") or []}
        seed_authors = {book.get("author") for book in seeds if book.get("author") not in (None, "", "未知作者")}
        similar = self._similarity(wanted, [book for _, book in candidates])
        asked = pairs(wanted)
        scored = []
        for (key, book), score in zip(candidates, similar):
            shared = [subject for subject in book.get("subjects") or [] if subject in seed_subjects][:2]
            same_author = book.get("author") in seed_authors
            # Words in common count too: short synopses give the vectors little to go on.
            words = len(asked & pairs(signature(book))) / max(1, len(asked))
            close = score >= (CLOSE_VECTOR if self.embedder else CLOSE_WORDS)
            score += 0.5 * words + 0.1 * len(shared) + 0.05 * same_author
            # The reason has to be true: a weak match is offered as one of the other books here.
            why = (f"同属{'、'.join(shared)}" if shared else "") or ("同一位作者" if same_author else "") or (
                "内容相近" if close else "书库里的其他选择")
            scored.append((score, key, book, why))
        scored.sort(key=lambda item: -item[0])
        return None, {"books": [{"bookId": key, "title": book.get("title", ""), "author": book.get("author", ""),
                                 "subjects": (book.get("subjects") or [])[:2], "why": why}
                                for _, key, book, why in scored[:RECOMMENDATIONS]]}

    def _similarity(self, wanted, books):
        """How close each book's signature is to `wanted`: sentence vectors when the model is here,
        else the share of `wanted`'s character pairs the signature contains."""
        if self.embedder:
            texts = [signature(book) for book in books]
            missing = [(book.get("id"), text) for book, text in zip(books, texts) if (book.get("id"), text) not in _signatures]
            if missing:
                for key, vector in zip(missing, self.embedder.encode([text for _, text in missing])):
                    _signatures[key] = vector
            query = self.embedder.encode([wanted])[0]
            return [float(_signatures[(book.get("id"), text)] @ query) for book, text in zip(books, texts)]
        asked = pairs(wanted)
        return [len(asked & pairs(signature(book))) / max(1, len(asked)) for book in books]

    def _add_bookmark(self, args):
        mark = self.library.add_bookmark(self.reading_id, args.get("note", ""))
        self.bookmark_ids.add(mark["id"])
        return None, {"ok": True, "bookmark": {"id": mark["id"], "chapter": mark["chapter"] + 1,
                                               "chapter_title": mark["chapter_title"], "note": mark["note"]}}

    def _list_bookmarks(self, args):
        marks = self.library.bookmarks(self.reading_id)[-10:]
        return None, {"bookmarks": [{"id": item["id"], "chapter": item["chapter"] + 1,
                                     "chapter_title": item["chapter_title"], "note": item["note"]} for item in marks]}
