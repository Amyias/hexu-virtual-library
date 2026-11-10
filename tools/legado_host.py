"""阅读 App（Legado）宿主接口的有界实现。

只提供三类能力，越界的调用一律报错而不是静默放行：
1. 纯计算：base64 / hex / md5 / 时间格式化 / URL 编码；
2. 每源作用域的变量表 java.put / java.get；
3. 同站点受限 ajax：只能访问该书源自己的域名，GET/POST，单次响应 4 MiB、
   单规则最多 4 次，TLS 正常校验，不允许跳转到别的站点。
浏览器/设备类接口（startBrowserAwait、getVerificationCode、Packages.*）
不实现，只做无副作用的空实现或明确报错，并在 capabilities 里标出来。
"""
import base64
import hashlib
import json
import re
import threading
import time
import urllib.parse

MAX_AJAX_CALLS = 4


class HostError(RuntimeError):
    """A host call the source asked for but this runtime refuses or cannot do."""


class LegadoHost:
    def __init__(self, request=None, base_url="", variables=None):
        self.request = request          # callable(url, method=, body=, headers=, charset=) -> str
        self.base_url = base_url or ""
        self.variables = variables if variables is not None else {}
        self.lock = threading.Lock()
        self.calls = 0
        self.warnings = []
        self.value_rule = None          # set by the rule engine: java.getString support
        self.deadline = 0.0             # set by begin(); every host call checks it

    def begin(self, budget=25.0):
        """带宿主接口的规则没有 JS 时间限制，改由每次宿主调用检查墙钟预算。"""
        self.deadline = time.monotonic() + budget

    def _alive(self):
        if self.deadline and time.monotonic() > self.deadline:
            raise HostError("书源规则执行超时，已中止")

    # ---------- 字符串进、字符串出，供 quickjs 调用 ----------
    @staticmethod
    def _box(value):
        return json.dumps({"ok": True, "v": "" if value is None else str(value)}, ensure_ascii=False)

    @staticmethod
    def _fail(message):
        return json.dumps({"ok": False, "v": str(message)[:200]}, ensure_ascii=False)

    def ajax(self, url, options=""):
        if self.request is None:
            return self._fail("此运行环境不允许书源发起网络请求")
        with self.lock:
            if self.calls >= MAX_AJAX_CALLS:
                return self._fail("单个规则最多发起 4 次 java.ajax 请求")
            self.calls += 1
        target = urllib.parse.urljoin(self.base_url or "/", str(url or ""))
        method, body, headers, charset = "GET", None, {}, "utf-8"
        if options:
            try:
                data = json.loads(options) if str(options).lstrip().startswith("{") else {"method": str(options)}
            except ValueError:
                return self._fail("java.ajax 的选项不是合法 JSON")
            if not isinstance(data, dict):
                return self._fail("java.ajax 的选项必须是对象")
            method = str(data.get("method", "GET")).upper()
            body = data.get("body")
            headers = data.get("headers") or {}
            charset = str(data.get("charset") or "utf-8")
        if not isinstance(headers, dict):
            headers = {}
        try:
            return self._box(self.request(target, method=method, body=body,
                                         headers={str(k): str(v) for k, v in headers.items()},
                                         charset=charset))
        except Exception as error:  # 站点/策略/网络错误都折成可读消息，不回显地址
            return self._fail(getattr(error, "args", ["书源请求失败"])[0] if error.args else "书源请求失败")

    def get(self, key):
        with self.lock:
            return self._box(self.variables.get(str(key), ""))

    def put(self, key, value):
        with self.lock:
            self.variables[str(key)] = "" if value is None else str(value)
        return self._box("")

    def get_string(self, rule):
        """java.getString(rule)：在当前的 result 上再跑一条规则。"""
        if self.value_rule is None:
            return self._fail("java.getString 在此上下文中不可用")
        try:
            return self._box(self.value_rule(str(rule)))
        except Exception as error:
            return self._fail(str(error)[:160])

    # ---------- 纯计算 ----------
    def base64_decode(self, value):
        try:
            return self._box(base64.b64decode(str(value), validate=False).decode("utf-8", errors="replace"))
        except Exception:
            return self._fail("base64 解码失败")

    def base64_encode(self, value):
        return self._box(base64.b64encode(str(value).encode("utf-8")).decode())

    def hex_decode(self, value):
        try:
            return self._box(bytes.fromhex(re.sub(r"\s+", "", str(value))).decode("utf-8", errors="replace"))
        except Exception:
            return self._fail("十六进制解码失败")

    def hex_encode(self, value):
        return self._box(str(value).encode("utf-8").hex())

    def md5(self, value, short=False):
        digest = hashlib.md5(str(value).encode("utf-8")).hexdigest()
        return self._box(digest[8:24] if short else digest)

    def time_format(self, value=""):
        stamp = time.time()
        if str(value).strip():
            try:
                stamp = float(value)
            except ValueError:
                stamp = time.time()
            if stamp > 1e11:
                stamp /= 1000.0
        return self._box(time.strftime("%Y/%m/%d %H:%M", time.localtime(stamp)))

    def encode_uri(self, value):
        return self._box(urllib.parse.quote(str(value)))

    def note(self, message):
        with self.lock:
            if len(self.warnings) < 20 and message not in self.warnings:
                self.warnings.append(message)
        return self._box("")


PREAMBLE = r"""
var __hexuDecode = function (name, a, b) {
  var raw = globalThis[name](a == null ? '' : String(a), b == null ? '' : String(b));
  var box = JSON.parse(raw);
  if (!box.ok) { throw new Error(box.v); }
  return box.v;
};
var java = {
  ajax: function (url, options) {
    return __hexuDecode('__hexuAjax', url,
      (options && typeof options === 'object') ? JSON.stringify(options) : (options == null ? '' : String(options)));
  },
  get: function (key) { return __hexuDecode('__hexuGet', key); },
  put: function (key, value) { return __hexuDecode('__hexuPut', key, value); },
  getString: function (rule) { return __hexuDecode('__hexuGetString', rule); },
  base64Decode: function (v) { return __hexuDecode('__hexuBase64Decode', v); },
  base64Encode: function (v) { return __hexuDecode('__hexuBase64Encode', v); },
  hexDecodeToString: function (v) { return __hexuDecode('__hexuHexDecode', v); },
  hexEncodeToString: function (v) { return __hexuDecode('__hexuHexEncode', v); },
  md5Encode: function (v) { return __hexuDecode('__hexuMd5', v); },
  md5Encode16: function (v) { return __hexuDecode('__hexuMd5Short', v); },
  timeFormat: function (v) { return __hexuDecode('__hexuTime', v); },
  encodeURI: function (v) { return __hexuDecode('__hexuEncodeUri', v); },
  log: function () { return ''; },
  toast: function () { return ''; },
  longToast: function () { return ''; },
  setContent: function () { return ''; },
  startBrowserAwait: function () { return ''; },
  startBrowser: function () { return ''; },
  getCookie: function () { return ''; },
  refreshBookInfo: function () { return ''; },
  refreshToc: function () { return ''; },
  refreshContent: function () { return ''; },
  getVerificationCode: function () { throw new Error('此源需要人工图形验证码，当前运行环境不提供'); }
};
var book = {}, source = {}, cookie = { getCookie: function () { return ''; }};
var sleep = function () { return ''; };
var console = { log: function () {}, warn: function () {}, error: function () {} };
"""


def bind(ctx, host):
    """把宿主能力挂进 quickjs 上下文；每个调用都只收字符串、只回字符串。

    quickjs-ng 在设置时间限制时不允许回调 Python，所以带宿主接口的规则不设 JS 时间限制，
    统一由每次调用前的墙钟检查（host._alive）与请求次数预算收口。"""
    def guarded(function):
        def call(*args):
            try:
                host._alive()
                return function(*args)
            except HostError as error:
                return LegadoHost._fail(str(error))
            except Exception:
                return LegadoHost._fail("宿主接口调用失败")
        return call

    # 前导脚本固定传两个参数，单参数接口在这里补齐第二个。
    def single(function):
        return lambda first, second=None: function(first)

    ctx.add_callable("__hexuAjax", guarded(host.ajax))
    ctx.add_callable("__hexuGet", guarded(single(host.get)))
    ctx.add_callable("__hexuPut", guarded(host.put))
    ctx.add_callable("__hexuGetString", guarded(single(host.get_string)))
    ctx.add_callable("__hexuBase64Decode", guarded(single(host.base64_decode)))
    ctx.add_callable("__hexuBase64Encode", guarded(single(host.base64_encode)))
    ctx.add_callable("__hexuHexDecode", guarded(single(host.hex_decode)))
    ctx.add_callable("__hexuHexEncode", guarded(single(host.hex_encode)))
    ctx.add_callable("__hexuMd5", guarded(host.md5))
    ctx.add_callable("__hexuMd5Short", guarded(lambda value, _unused=None: host.md5(value, short=True)))
    ctx.add_callable("__hexuTime", guarded(single(host.time_format)))
    ctx.add_callable("__hexuEncodeUri", guarded(single(host.encode_uri)))
    ctx.eval(PREAMBLE)
