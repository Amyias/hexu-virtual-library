"""Bounded Legado rule adapters. No Python callbacks, OS, file or network bindings in JS."""
import json
import re
from functools import lru_cache


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


def javascript(code, value, context=None, library=""):
    import quickjs
    raw = markup(value)
    if len(raw) + len(code) + len(library) > MAX_INPUT:
        raise SourceError("JS 规则输入过大")
    ctx = quickjs.Context()
    ctx.set_memory_limit(32 * 1024 * 1024)
    ctx.set_max_stack_size(512 * 1024)
    ctx.set_time_limit(0.5)
    values = {"result": raw, "baseUrl": "", "key": "", "page": 1, **(context or {})}
    try:
        for name in ("result", "baseUrl", "key", "page"):
            ctx.eval("globalThis[" + json.dumps(name) + "]=" + json.dumps(values[name], ensure_ascii=True))
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
    except (quickjs.JSException, TypeError, ValueError) as error:
        # Never include the script or response in diagnostics (may contain source-specific keys).
        raise SourceError("JS 规则执行失败、超时或超过内存限制；不提供 Android/Java、本机文件及网络桥接") from error


class RuleEngine:
    def __init__(self, library="", context=None):
        dependencies()
        self.library, self.context = library, context or {}

    def validate(self, rule):
        """Compile rules at import time without executing source scripts or making requests."""
        if not rule:
            return
        if not isinstance(rule, str) or len(rule) > 128 * 1024:
            raise SourceError("书源规则必须是长度受限的字符串")
        match = re.search(r"@js:", rule, re.I)
        if match or (rule.lower().startswith("<js>") and rule.lower().endswith("</js>")):
            import quickjs
            code = rule[match.end():] if match else rule[4:-5]
            ctx = quickjs.Context(); ctx.set_memory_limit(32 * 1024 * 1024); ctx.set_time_limit(0.5)
            try:
                ctx.eval("new Function(" + json.dumps(self.library + "\n" + code) + ")")
                if match and match.start(): self.validate(rule[:match.start()])
            except quickjs.JSException as error:
                raise SourceError("JS 规则语法错误，未启用此书源") from error
            return
        selector = rule.split("##", 1)[0]
        if "||" in selector or "&&" in selector:
            for part in re.split(r"\|\||&&", selector): self.validate(part)
            return
        try:
            path = re.sub(r"^@json:", "", selector, flags=re.I)
            if path.startswith("$"):
                json_path(path)
                return
            xpath = re.sub(r"^@xpath:", "", selector, flags=re.I)
            if xpath != selector or xpath.startswith(("/", "./", "(")):
                from lxml import etree
                etree.XPath(xpath)
                return
            self._css("<div></div>", re.sub(r"^@css:", "", selector, flags=re.I))
        except SourceError:
            raise
        except Exception as error:
            raise SourceError("书源选择器、XPath 或 JSONPath 语法错误，未启用此书源") from error

    def items(self, value, rule):
        if not isinstance(rule, str) or len(rule) > 128 * 1024:
            raise SourceError("书源规则必须是长度受限的字符串")
        rule = rule.strip()
        if not rule:
            return [value]
        match = re.search(r"@js:", rule, re.I)
        if match:
            before = rule[:match.start()]
            initial = self.value(value, before) if before else value
            output = javascript(rule[match.end():], initial, self.context, self.library)
            return self._bounded(output if isinstance(output, list) else ([] if output is None else [output]))
        if rule.lower().startswith("<js>") and rule.lower().endswith("</js>"):
            output = javascript(rule[4:-5], value, self.context, self.library)
            return self._bounded(output if isinstance(output, list) else [output])
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
            path = re.sub(r"^@json:", "", rule, flags=re.I)
            if path.startswith("$"):
                obj = json.loads(value) if isinstance(value, str) else value
                return self._bounded([m.value for m in json_path(path).find(obj)])
            xpath = re.sub(r"^@xpath:", "", rule, flags=re.I)
            if xpath != rule or xpath.startswith(("/", "./", "(")):
                result = tree(value).xpath(xpath, smart_strings=False)
                return self._bounded(result if isinstance(result, list) else [result])
            return self._css(value, re.sub(r"^@css:", "", rule, flags=re.I))
        except SourceError:
            raise
        except Exception as error:
            raise SourceError("书源选择器、XPath 或 JSONPath 无法解析") from error

    @staticmethod
    def _bounded(items):
        if len(items) > MAX_RESULTS:
            raise SourceError("书源规则返回超过 2000 项")
        return items

    def _css(self, value, rule):
        from lxml import etree
        from lxml.cssselect import CSSSelector
        root = tree(value)
        attributes = {"text", "ownText", "html", "all", "href", "src", "title", "content"}
        parts = rule.split("@")
        attribute = parts.pop() if parts[-1] in attributes else None
        nodes = [root]
        for part in parts:
            if not part:
                continue
            if part.startswith("text."):
                wanted = part[5:]
                nodes = [n for node in nodes for n in node.iter() if n.tag not in {"script", "style"} and plain(n).strip() == wanted]
                continue
            part = re.sub(r"^class\.", ".", part)
            part = re.sub(r"^id\.", "#", part)
            part = re.sub(r"^tag\.", "", part)
            selector = CSSSelector(part)
            nodes = self._bounded([n for node in nodes for n in selector(node)])
        if attribute is None:
            return nodes
        if attribute == "text":
            return [plain(n).strip() for n in nodes]
        if attribute == "ownText":
            return ["".join(n.xpath("text()", smart_strings=False)).strip() for n in nodes]
        if attribute in {"html", "all"}:
            return [etree.tostring(n, encoding="unicode", method="html") for n in nodes]
        return [n.get(attribute, "") for n in nodes if n.get(attribute)]

    def value(self, value, rule, default=""):
        # Legado regex replacement suffix. JS owns its own syntax.
        if "##" in rule and not re.search(r"@js:|<js>", rule, re.I):
            selector, pattern, *replacement = rule.split("##", 2)
            text = self.value(value, selector)
            # Run regex in the time-limited JS VM; Python re has no execution deadline.
            repl = replacement[0] if replacement else ""
            code = "result.replace(new RegExp(" + json.dumps(pattern) + ", 'g'), " + json.dumps(repl) + ")"
            return javascript(code, text, self.context)
        result = self.items(value, rule)
        return "\n".join(plain(item) for item in result).strip() if result else default

    def render_url(self, template, key="", page=1):
        import urllib.parse
        context = {**self.context, "key": key, "page": page}
        if re.match(r"\s*(?:@js:|<js>)", template, re.I):
            return RuleEngine(self.library, context).value("", template)
        def replace(match):
            expr = match.group(1).strip()
            if expr == "key":
                return urllib.parse.quote(key)
            if expr == "page":
                return str(page)
            return str(javascript(expr, "", context, self.library))
        return re.sub(r"\{\{(.*?)\}\}", replace, template).replace("{query}", urllib.parse.quote(key))
