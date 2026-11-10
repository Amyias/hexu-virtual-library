"""Bounded Legado rule adapters. No Python callbacks, OS, file or network bindings in JS
beyond the same-host java.ajax bridge provided by legado_host."""
import json
import re
from functools import lru_cache

from legado_host import HostError, LegadoHost


class SourceError(ValueError):
    pass


MAX_INPUT = 4 * 1024 * 1024
MAX_RESULTS = 2000


def dependencies():
    try:
        import lxml.html
        import cssselect
        import jsonpath_ng.ext
        import quickjs
    except ImportError as error:
        raise SourceError("书源解析依赖未安装，请运行 python -m pip install -r tools/requirements-sources.txt，或使用新版桌面程序") from error


@lru_cache(maxsize=128)
def json_path(rule):
    from jsonpath_ng.ext import parse
    return parse(rule)


def markup(value):
    from lxml import etree
    if isinstance(value, etree._Element):
        return etree.tostring(value, encoding="unicode", method="html")
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def tree(value):
    from lxml import etree, html
    if isinstance(value, etree._Element):
        return value
    raw = markup(value)
    if len(raw) > MAX_INPUT:
        raise SourceError("书源规则输入超过 4 MiB")
    return html.fromstring(raw or "<div></div>", parser=html.HTMLParser(no_network=True, huge_tree=False))


def plain(value):
    from lxml import etree
    if isinstance(value, etree._Element):
        # Use a copy: stripping script/style must not mutate another field's source tree.
        root = tree(markup(value))
        for node in root.xpath(".//script|.//style|.//noscript|.//iframe"):
            node.drop_tree()
        for node in root.xpath(".//p|.//div|.//br|.//li|.//h1|.//h2|.//h3"):
            node.tail = "\n" + (node.tail or "")
        value = root.text_content()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value) if value is not None else ""


def javascript(code, value, context=None, library="", host=None):
    import quickjs
    code = re.sub(r"\bawait\s+", "", code)   # 宿主接口本身是同步的，去掉 await 语义不变
    raw = markup(value)
    if len(raw) + len(code) + len(library) > MAX_INPUT:
        raise SourceError("JS 规则输入过大")
    ctx = quickjs.Context()
    ctx.set_memory_limit(32 * 1024 * 1024)
    ctx.set_max_stack_size(512 * 1024)
    # quickjs-ng 不允许在设置了时间限制时回调 Python，所以带宿主接口的规则改用宿主侧
    # 截止时间（每次调用都检查），纯 JS 规则仍然限制在 0.5 秒。
    network = bool(re.search(r"\bjava\s*\.", code))
    if host is not None and network:
        host.begin()
    else:
        ctx.set_time_limit(0.5)
    values = {"result": raw, "baseUrl": "", "key": "", "page": 1, **(context or {})}
    try:
        if host is not None:
            from legado_host import bind
            bind(ctx, host)
        for name, item in values.items():
            ctx.eval("globalThis[" + json.dumps(name) + "]=" + json.dumps(item, ensure_ascii=True))
        if library:
            ctx.eval(library)
        if re.match(r"\s*return\b", code):
            code = "(function(){" + code + "})()"
        output = ctx.eval(code)
        if isinstance(output, quickjs.Object):
            output = json.loads(output.json())
        if len(json.dumps(output, ensure_ascii=False)) > MAX_INPUT:
            raise SourceError("JS 规则输出过大")
        return output
    except SourceError:
        raise
    except (quickjs.JSException, TypeError, ValueError) as error:
        # Never include the script or response in diagnostics (may contain source-specific keys).
        raise SourceError("JS 规则执行失败、超时或超过内存限制；宿主接口只提供同站点的 java.ajax 与纯计算函数") from error


# ---- Legado 规则的通用语法：class.x.0@tag.a.1@text、[0:2] 切片、!0 排除、{{表达式}} ----

ATTRIBUTES = {"text", "ownText", "textNodes", "html", "all", "href", "src", "title", "content"}
INDEX_TAIL = re.compile(r"(\[\s*(-?\d*)\s*:\s*(-?\d*)\s*\]|\[\s*(-?\d+)\s*\]|!(-?\d+)|\.(-?\d+))$")
NUMBER_RULE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
GROUP_RULE = re.compile(r"^\$\{?(\d+)\}?$")
# Legado 允许整条规则就是一个正则（配合 $1..$n 取分组），例如起点目录。
REGEX_RULE = re.compile(r"^(?![.#\[])[^@\s]*(?:\\[dwsDWS]|\.\*|\(\?:|\[\^)[^@\s]*$")
STEP_NAME = re.compile(r"^(?:tag|class|id|text)\.[^\s@]+$|^[.#][\w\-\u4e00-\u9fff]+$|^children(?:\[\d+\])?$|^\*$|^[A-Za-z][\w-]*$")
# 标准 CSS（带后代/子代组合、伪类、分组）不是 Legado 的 step 语法，整条交给 cssselect。
CSS_EXTRA = re.compile(r"[\s>,:()\[\]+~]")
# JSON 取值必须带下标（data[0]、$.a），避免把「ownText」「a.btn」这类选择器当成 JSON 路径。
JSON_RULE = re.compile(r"^(?:[A-Za-z_$][\w$]*)(?:\s*\[\s*-?\d+\s*\]|\[\s*['\"][^'\"]*['\"]\s*\]|\.\s*[A-Za-z_$][\w$]*)+$")
URL_RULE = re.compile(r"^(?:https?://|/|\.\.?/)", re.I)


def split_rule(rule):
    """Split 「class.x.0@tag.a@href」 into selector steps and an attribute name."""
    parts = [part for part in rule.split("@")]
    attribute = None
    # 只有属性名的规则（ownText、href）作用在当前元素上。
    if len(parts) == 1 and parts[0].strip() in ATTRIBUTES:
        return [], parts[0].strip()
    if len(parts) > 1:
        last = parts[-1].strip()
        # 「@」后面一定是属性：Legado 的链式步骤必须带 tag./class./id./text./children 前缀。
        if last in ATTRIBUTES or not re.match(r"^(?:tag|class|id|text)\.|^[.#]|^children", last):
            attribute = parts.pop().strip()
    return [part.strip() for part in parts if part.strip()], attribute


CSS_INDEX_TAIL = re.compile(r"(\.(-?\d+):(-?\d+)|\[\s*(-?\d*)\s*:\s*(-?\d*)\s*\]|\[\s*(-?\d+)\s*\]|!(-?\d+)|\.(-?\d+))$")


def strip_css_index(selector):
    """标准 CSS 里常见的 Legado 尾部索引：span.0、a.1、p.-1、span.0:3、a[0:2]。"""
    indexes = []
    while True:
        match = CSS_INDEX_TAIL.search(selector)
        if not match:
            return selector, indexes
        token = match.group(1)
        if ":" in token and not token.startswith("["):
            start, end = token[1:].split(":")
            indexes.insert(0, "[" + start + ":" + end + "]")
        else:
            indexes.insert(0, token)
        selector = selector[: match.start()]


def normalize_alternatives(selector):
    """Legado 用 [attr~=a|b|c] 表示"任一"，标准 CSS 只认单个词。"""
    return re.sub(r"\[\s*([\w-]+)\s*~=\s*([^\]|]+)(?:\|[^\]]*)?\]", r"[\1~=\2]", selector)


def split_indexes(part):
    indexes = []
    while True:
        match = INDEX_TAIL.search(part)
        if not match:
            return part, indexes
        indexes.insert(0, match.group(1))
        part = part[: match.start()]


def step_kind(name):
    if name == "children":
        return "children", ""
    for prefix, kind in (("tag.", "tag"), ("class.", "class"), ("id.", "id"), ("text.", "text"), (".", "class"), ("#", "id")):
        if name.startswith(prefix):
            return kind, name[len(prefix):]
    return "tag", name


def apply_index(nodes, token):
    if token.startswith("[") and ":" in token:
        start, end = (int(value) if value not in ("", "-") else None for value in token[1:-1].split(":"))
        return nodes[slice(start, end)]
    if token.startswith("["):
        position = int(token[1:-1])
        if position < 0:
            position += len(nodes)
        return [nodes[position]] if 0 <= position < len(nodes) else []
    if token.startswith("!"):
        position = int(token[1:])
        return [node for index, node in enumerate(nodes) if index != position]
    position = int(token[1:])
    if position < 0:
        position += len(nodes)
    return [nodes[position]] if 0 <= position < len(nodes) else []


def own_text(node):
    return "".join([node.text or ""] + [(child.tail or "") for child in node]).strip()


def json_walk(value, rule):
    """「data[0].name」 / 「$.data[0]」 式的取值，用于 JSON 书源（不联网、不执行代码）。"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if rule.startswith("$"):
        return [match.value for match in json_path(rule).find(value)]
    current = value
    for index, name, quoted in re.findall(r"\[\s*(-?\d+)\s*\]|\.?([A-Za-z_$][\w$]*)|\[\s*['\"]([^'\"]*)['\"]\s*\]", rule):
        if index:
            if isinstance(current, list) and -len(current) <= int(index) < len(current):
                current = current[int(index)]
            else:
                return None
        else:
            key = name or quoted
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list):
                current = [item.get(key) for item in current if isinstance(item, dict)]
            else:
                return None
        if current is None:
            return None
    return current


class RuleEngine:
    def __init__(self, library="", context=None, host=None):
        dependencies()
        self.library, self.context = library, context or {}
        self.host = host if host is not None else LegadoHost()
        self.depth = 0

    # ---- 导入期的离线校验：编译规则，不执行源脚本、不发请求 ----
    def validate(self, rule):
        if not rule:
            return
        if not isinstance(rule, str) or len(rule) > 128 * 1024:
            raise SourceError("书源规则必须是长度受限的字符串")
        rule = rule.strip()
        if "{{" in rule and "}}" in rule:
            for expression in re.findall(r"\{\{(.*?)\}\}", rule, re.S):
                expression = expression.strip()
                if not expression or expression in {"key", "page", "baseUrl"} or expression.startswith("$"):
                    continue
                if expression.startswith("@@"):
                    self.validate(expression[2:])
                    continue
                self._compile(expression)
            return
        match = re.search(r"@js:", rule, re.I)
        if match:
            if match.start():
                self.validate(rule[: match.start()])
            self._compile(rule[match.end():])
            return
        if rule.lower().startswith("<js>"):
            self._compile(re.sub(r"</js>\s*$", "", rule[4:], flags=re.I))
            return
        selector = rule.split("##", 1)[0]
        if "||" in selector or "&&" in selector:
            for part in re.split(r"\|\||&&", selector):
                self.validate(part)
            return
        try:
            if GROUP_RULE.match(selector) or NUMBER_RULE.match(selector):
                return
            path = re.sub(r"^@json:", "", selector, flags=re.I)
            if path.startswith("$"):
                json_path(path)
                return
            xpath = re.sub(r"^@xpath:", "", selector, flags=re.I)
            if xpath != selector or xpath.startswith(("//", "./", "(")):
                from lxml import etree
                etree.XPath(xpath)
                return
            self._validate_css(selector)
        except SourceError:
            raise
        except Exception as error:
            raise SourceError("书源选择器、XPath 或 JSONPath 语法错误，未启用此书源") from error

    def _compile(self, code):
        import quickjs
        code = re.sub(r"\bawait\s+", "", code)
        ctx = quickjs.Context()
        ctx.set_memory_limit(32 * 1024 * 1024)
        ctx.set_time_limit(0.5)
        try:
            ctx.eval("new Function(" + json.dumps(self.library + "\n" + code) + ")")
        except quickjs.JSException as error:
            raise SourceError("JS 规则语法错误，未启用此书源") from error

    def _validate_css(self, rule):
        rule = re.sub(r"^@css:", "", rule, flags=re.I).strip()
        if not rule:
            return
        if URL_RULE.match(rule) and not rule.startswith("//"):
            return
        compact = re.sub(r"\s+", "", rule)
        if "[" in compact and JSON_RULE.match(compact):
            return
        if NUMBER_RULE.match(rule) or GROUP_RULE.match(rule):
            return
        if REGEX_RULE.match(rule):
            re.compile(rule)
            return
        steps, attribute = split_rule(rule)
        if not steps:
            if attribute is None:
                raise SourceError("书源规则缺少选择器")
            return
        for step in steps:
            if not STEP_NAME.fullmatch(split_indexes(step)[0]):
                break
        else:
            return
        from lxml.cssselect import CSSSelector
        selector, _ = strip_css_index(normalize_alternatives("".join(rule.split("@")[:-1]) if attribute else rule))
        CSSSelector(selector)

    # ---- 取值 ----
    def items(self, value, rule):
        if not isinstance(rule, str) or len(rule) > 128 * 1024:
            raise SourceError("书源规则必须是长度受限的字符串")
        rule = rule.strip()
        if not rule:
            return [value]
        if rule.startswith("@@"):
            rule = rule[2:]
            if not rule:
                return [value]
        if NUMBER_RULE.match(rule):
            return [rule]
        if "{{" in rule and "}}" in rule:
            if re.fullmatch(r"\{\{.*\}\}", rule, re.S):
                expanded = self.expand(value, rule)
                return [] if expanded is None or not expanded.strip() else [expanded]
            rule = self.expand(value, rule)
            if not rule.strip():
                return []
        match = re.search(r"@js:", rule, re.I)
        if match:
            before = rule[: match.start()]
            initial = self.value(value, before) if before else value
            return self._bounded(self._js(rule[match.end():], initial))
        if rule.lower().startswith("<js>"):
            return self._bounded(self._js(re.sub(r"</js>\s*$", "", rule[4:], flags=re.I), value))
        # Alternatives/concatenation are outside JS; do not split expressions inside JS code.
        if "||" in rule:
            for part in rule.split("||"):
                output = self.items(value, part)
                if output:
                    return output
            return []
        if "&&" in rule:
            return self._bounded([item for part in rule.split("&&") for item in self.items(value, part)])
        try:
            if GROUP_RULE.match(rule):
                index = int(GROUP_RULE.match(rule).group(1)) - 1
                rows = value if isinstance(value, list) else [value]
                return self._bounded([row[index] for row in rows if isinstance(row, tuple) and index < len(row)])
            path = re.sub(r"^@json:", "", rule, flags=re.I)
            if path.startswith("$"):
                obj = json.loads(value) if isinstance(value, str) else value
                return self._bounded([match.value for match in json_path(path).find(obj)])
            xpath = re.sub(r"^@xpath:", "", rule, flags=re.I)
            if xpath != rule or xpath.startswith(("//", "./", "(")):
                result = tree(value).xpath(xpath, smart_strings=False)
                return self._bounded(result if isinstance(result, list) else [result])
            if REGEX_RULE.match(rule):
                text = plain(value)
                return self._bounded([match.groups() if match.groups() else (match.group(0),)
                                      for match in re.finditer(rule, text)])
            compact = re.sub(r"\s+", "", rule)
            if "[" in compact and JSON_RULE.match(compact):
                found = json_walk(value, compact)
                if found is None:
                    return []
                return self._bounded(found if isinstance(found, list) else [found])
            if URL_RULE.match(rule) and not rule.startswith("//"):
                return [rule]
            return self._css(value, rule)
        except SourceError:
            raise
        except Exception as error:
            raise SourceError("书源选择器、XPath 或 JSONPath 无法解析") from error

    def _js(self, code, value):
        if self.depth > 4:
            raise SourceError("书源规则嵌套过深")
        previous, self.depth = self.host.value_rule, self.depth + 1
        self.host.value_rule = lambda rule: self.value(value, rule)
        try:
            output = javascript(code, value, self.context, self.library, self.host)
        finally:
            self.host.value_rule, self.depth = previous, self.depth - 1
        return output if isinstance(output, list) else ([] if output is None else [output])

    @staticmethod
    def _bounded(items):
        if len(items) > MAX_RESULTS:
            raise SourceError("书源规则返回超过 2000 项")
        return items

    def expand(self, value, text):
        """把 {{key}} / {{page}} / {{$.field}} / {{JS}} 展开成具体文本。"""
        def one(match):
            expression = match.group(1).strip()
            if expression == "key":
                return plain(self.context.get("key", ""))
            if expression == "page":
                return plain(self.context.get("page", 1))
            if expression == "baseUrl":
                return plain(self.context.get("baseUrl", ""))
            if expression.startswith("@@"):
                return self.value(value, expression[2:])
            if expression.startswith("$"):
                found = json_walk(value, expression)
                if isinstance(found, list):
                    found = found[0] if found else None
                return plain(found)
            return plain(self._js(expression, value)[:1] or "")
        return re.sub(r"\{\{(.*?)\}\}", one, text, flags=re.S)

    def _css(self, value, rule):
        from lxml import etree
        rule = re.sub(r"^@css:", "", rule, flags=re.I).strip()
        if not rule:
            return [value]
        steps, attribute = split_rule(rule)
        nodes = [tree(value)]
        if steps and any(not STEP_NAME.fullmatch(split_indexes(step)[0]) for step in steps):
            nodes = self._css_plain(nodes, "@".join(steps))
        else:
            for step in steps:
                nodes = self._walk(nodes, step)
                if not nodes:
                    return []
        if attribute is None:
            return nodes
        if attribute == "text":
            return [plain(node).strip() for node in nodes]
        if attribute == "ownText":
            return [own_text(node) for node in nodes]
        if attribute == "textNodes":
            return ["".join(node.xpath("text()", smart_strings=False)) for node in nodes]
        if attribute in {"html", "all"}:
            return [etree.tostring(node, encoding="unicode", method="html") for node in nodes]
        return [node.get(attribute, "") for node in nodes if node.get(attribute)]

    @staticmethod
    def _css_plain(nodes, rule):
        """整条按标准 CSS 处理：#id .cls:not(...)、a.btn,.page>span 这类写法。"""
        from lxml.cssselect import CSSSelector
        bare, indexes = strip_css_index(normalize_alternatives(rule))
        selector = CSSSelector(bare)
        found, seen = [], set()
        for node in nodes:
            for match in selector(node):
                if id(match) not in seen:
                    seen.add(id(match))
                    found.append(match)
        for index in indexes:
            found = apply_index(found, index)
        return found

    @staticmethod
    def _walk(nodes, step):
        name, indexes = split_indexes(step)
        kind, wanted = step_kind(name)
        found, seen = [], set()
        for node in nodes:
            candidates = [child for child in node if child.tag] if kind == "children" else [node, *node.iterdescendants()]
            for candidate in candidates:
                if kind == "tag" and wanted not in ("", "*") and candidate.tag != wanted:
                    continue
                if kind == "class" and wanted not in (candidate.get("class") or "").split():
                    continue
                if kind == "id" and candidate.get("id") != wanted:
                    continue
                if kind == "text" and plain(candidate).strip() != wanted:
                    continue
                if id(candidate) not in seen:
                    seen.add(id(candidate))
                    found.append(candidate)
        for index in indexes:
            found = apply_index(found, index)
        return found

    def value(self, value, rule, default=""):
        if not isinstance(rule, str):
            return default
        rule = rule.strip()
        if not rule:
            return default
        # Legado regex replacement suffix. JS owns its own syntax.
        if "##" in rule and not re.search(r"@js:|<js>", rule, re.I):
            selector, pattern, *replacement = rule.split("##", 2)
            text = self.value(value, selector)
            if not text:
                return default
            code = "result.replace(new RegExp(" + json.dumps(pattern) + ", 'g'), " + json.dumps(replacement[0] if replacement else "") + ")"
            return plain(javascript(code, text, self.context)) or default
        result = self.items(value, rule)
        return "\n".join(plain(item) for item in result).strip() if result else default

    def render_url(self, template, key="", page=1):
        import urllib.parse
        context = {**self.context, "key": key, "page": page}
        if re.match(r"\s*(?:@js:|<js>)", template, re.I):
            return RuleEngine(self.library, context, self.host).value("", template)
        def replace(match):
            expression = match.group(1).strip()
            if expression == "key":
                return urllib.parse.quote(key)
            if expression == "page":
                return str(page)
            return str(javascript(expression, "", context, self.library, self.host))
        return re.sub(r"\{\{(.*?)\}\}", replace, template).replace("{query}", urllib.parse.quote(key))
