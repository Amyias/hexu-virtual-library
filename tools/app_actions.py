"""The library actions 小和's model may ask for in a conversation ("tool calling").

A short whitelist, offered only when it makes sense in the current state, with every argument
checked here before the page is told to act:

    set_sky        day / night / auto (the clock)            any time
    reading_music  play / pause                              while a book is being read
    open_chapter   chapter number of the book being read     while a book is being read
    fetch_book     an HX number of a book in the local library   while the library is idle

The server never moves anything itself. A valid call becomes an "action" event in the reply
stream; the page carries it out (src/app/assistant.js) and checks it once more. An invalid call
is answered to the model as an error, so it can tell the reader what went wrong.
"""
import json

MAX_ACTIONS = 3
CATALOG_LINES = 40  # books listed for fetch_book; beyond this the prompt would cost too much

SKY = {"type": "function", "function": {
    "name": "set_sky",
    "description": "切换图书馆窗外的天空。day=太阳白天，night=月亮夜晚，auto=按电脑时间自动。只在读者明确要求切换白天、夜晚或自动时调用。",
    "parameters": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["day", "night", "auto"]}},
                   "required": ["mode"], "additionalProperties": False}}}
MUSIC = {"type": "function", "function": {
    "name": "reading_music",
    "description": "播放或暂停阅读时的背景音乐。只在读者明确要求时调用。",
    "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["play", "pause"]}},
                   "required": ["action"], "additionalProperties": False}}}
CHAPTER = {"type": "function", "function": {
    "name": "open_chapter",
    "description": "把正在阅读的书翻到第几章（从 1 开始数）。只在读者明确要求翻到某一章时调用。",
    "parameters": {"type": "object", "properties": {"chapter": {"type": "integer", "minimum": 1}},
                   "required": ["chapter"], "additionalProperties": False}}}
FETCH = {"type": "function", "function": {
    "name": "fetch_book",
    "description": "让小和从书架取出一本已入库的书交给读者。bookId 只能用系统提示里本机书库清单中的 HX 编号。只在读者明确想读、想取某本书时调用。",
    "parameters": {"type": "object", "properties": {"bookId": {"type": "string", "pattern": "^HX-\\d{5}$"}},
                   "required": ["bookId"], "additionalProperties": False}}}
NAMES = {"set_sky", "reading_music", "open_chapter", "fetch_book"}


class AppActions:
    """What this conversation turn may do. phase: the page's state; reading: the book being read
    as describe_book() reports it (with "chapters"), or None; catalog: HX number -> local book."""

    def __init__(self, phase, reading=None, catalog=None):
        self.phase = phase
        self.reading = reading
        self.catalog = catalog or {}
        self.count = 0
        self.tools = [SKY]
        if phase == "READING" and reading:
            self.tools += [MUSIC, CHAPTER]
        if phase == "IDLE" and self.catalog:
            self.tools.append(FETCH)

    def handles(self, name):
        return name in NAMES

    def prompt(self):
        text = ("你可以调用界面工具（" + "、".join(tool["function"]["name"] for tool in self.tools) + "）替读者操作图书馆，"
                "但只在读者明确提出要求时调用；调用后用一句话告诉读者做了什么，不要假装做了没调用的操作。")
        if any(tool is FETCH for tool in self.tools):
            lines = [f"{key} | {book.get('title', '')} | {book.get('author', '')}"
                     for key, book in list(self.catalog.items())[:CATALOG_LINES]]
            text += "本机书库（编号 | 书名 | 作者）：" + "；".join(lines) + "。"
        return text

    def execute(self, name, arguments):
        """(action for the page or None, result for the model)."""
        if self.count >= MAX_ACTIONS:
            return None, {"error": "本轮操作次数已达上限"}
        offered = {tool["function"]["name"] for tool in self.tools}
        if name not in offered:
            return None, {"error": "当前状态下不能执行这个操作"}
        try:
            args = json.loads(arguments) if isinstance(arguments, str) and len(arguments) <= 2000 else None
        except ValueError:
            args = None
        if not isinstance(args, dict):
            return None, {"error": "参数格式不正确"}
        if name == "set_sky" and args.get("mode") in ("day", "night", "auto"):
            action = {"mode": args["mode"]}
        elif name == "reading_music" and args.get("action") in ("play", "pause"):
            action = {"action": args["action"]}
        elif name == "open_chapter" and type(args.get("chapter")) is int:
            total = int(self.reading.get("chapters", 0))
            if not 1 <= args["chapter"] <= total:
                return None, {"error": f"这本书只有 {total} 章"}
            action = {"chapter": args["chapter"]}
        elif name == "fetch_book" and isinstance(args.get("bookId"), str):
            book = self.catalog.get(args["bookId"])
            if not book:
                return None, {"error": "本机书库里没有这个编号"}
            action = {"bookId": args["bookId"], "title": book.get("title", "")}
        else:
            return None, {"error": "参数不正确"}
        self.count += 1
        return {"type": "action", "name": name, "args": action}, {"ok": True, "done": "界面会立即执行"}
