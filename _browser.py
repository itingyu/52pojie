# -*- coding: utf-8 -*-
"""浏览器传输层：把 HTTP 请求交给 Minis App 里的 WebView 执行。

为什么需要它：52pj 的登录 cookie 是 HttpOnly，只有 App 进程内的
CookieManager 能读到，而 App 对外暴露的 get_cookies 只给截断预览
（BrowserUseManager.kt 里 value.take(77)+"…"），沙箱拿不到完整串。

于是换条路：借 App 的浏览器发请求。同源 fetch 会自动带上登录态，
正文用 base64 回传（论坛是 GBK 编码，不能走 text()，否则中文乱码）。

注意：只有前台标签页不会被 WebView 冻结，后台标签里 fetch / 定时器
会被挂起，表现为脚本 30 秒超时。
"""
import base64
import json
import re
import subprocess
import urllib.parse
import time

CLI = "minis-browser-use"
DEFAULT_TIMEOUT = 60


def _same_host(url, base):
    try:
        return urllib.parse.urlsplit(url).netloc == urllib.parse.urlsplit(base).netloc
    except Exception:
        return False


class BrowserError(RuntimeError):
    pass


class BrowserResponse:
    """requests 风格的最小响应对象。"""

    def __init__(self, status_code, content, headers=None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("gbk", "replace")
        self.headers = headers or {}
        self.encoding = "gbk"

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise BrowserError("HTTP %s" % self.status_code)


class _NullCookies:
    """浏览器自己带 cookie，本地不存。"""

    def set(self, *a, **kw):
        pass

    def get(self, *a, **kw):
        return {}

    def clear(self, *a, **kw):
        pass


_TAB_RE = re.compile(r"^\s*(\*?)\s*Tab\s+(\d+):")
_SUFFIX_RE = re.compile(r"\n\s*tab_id:\s*\d+\s*$")


def _strip_suffix(text):
    return _SUFFIX_RE.sub("", text)


class BrowserSession:
    """requests 风格的最小会话接口，供 Client 直接复用。"""

    def __init__(self, base, timeout=DEFAULT_TIMEOUT, cli=CLI):
        self.base = base.rstrip("/")
        self._curl = None
        self.timeout = timeout
        self.cli = cli
        self.headers = {}
        self.cookies = _NullCookies()
        self._tab_id = None

    # ---------- App 浏览器通道 ----------
    def _run(self, payload, timeout=None):
        proc = subprocess.run(
            [self.cli, "-q", "--json", json.dumps(payload)],
            capture_output=True, text=True,
            timeout=timeout or self.timeout)
        raw = (proc.stdout or proc.stderr or "").strip()
        try:
            data = json.loads(raw)
        except Exception:
            raise BrowserError("浏览器回执无法解析: %s" % raw[:200])
        if isinstance(data, dict) and "code" in data and "text" not in data:
            raise BrowserError("minis-browser-use 失败: %s"
                               % data.get("message", data.get("code")))
        return data.get("text", "") if isinstance(data, dict) else ""

    def _tabs(self):
        return self._run({"action": "list_tabs"}, timeout=30)

    def _active_tab(self):
        for line in self._tabs().splitlines():
            m = _TAB_RE.match(line)
            if m and m.group(1) == "*":
                return int(m.group(2))
        return None

    @property
    def curl(self):
        """跨域回退：仍走 curl_cffi 的 Chrome 指纹。"""
        if self._curl is None:
            from curl_cffi import requests as _http
            self._curl = _http.Session(impersonate="chrome")
        return self._curl

    def _ensure_tab(self):
        """挑一个前台标签页，并保证它在本站（同源才有登录态）。"""
        if self._tab_id is not None:
            return self._tab_id
        host = self.base.split("//")[-1]
        tab = self._active_tab()
        if tab is None:
            self._run({"action": "new_tab", "url": self.base + "/"}, timeout=90)
            for _ in range(10):
                time.sleep(1)
                tab = self._active_tab()
                if tab is not None:
                    break
        if tab is None:
            raise BrowserError("找不到可用的前台标签页")
        info = self._run({"action": "get_page_info", "tab_id": tab}, timeout=30)
        if host not in info:
            self._run({"action": "navigate", "url": self.base + "/",
                       "tab_id": tab}, timeout=90)
            time.sleep(2)
        self._tab_id = tab
        return tab

    def _script(self, url, method, body):
        """页面内抓取脚本：取原始字节再 base64，避免 GBK 被当 UTF-8 解。"""
        return (
            "var u=%s, m=%s, b=%s;"
            "var o={method:m,credentials:'include'};"
            "if(b!==null){o.body=b;}"
            "var r=await fetch(u,o);"
            "var ab=await r.arrayBuffer();"
            "var u8=new Uint8Array(ab),s='',C=0x8000;"
            "for(var i=0;i<u8.length;i+=C){s+=String.fromCharCode.apply(null,u8.subarray(i,i+C));}"
            "return ''+r.status+'\\n'+(r.headers.get('content-type')||'')+'\\n'+btoa(s);"
        ) % (json.dumps(url), json.dumps(method),
             json.dumps(body if body is not None else None))

    def request(self, method="GET", url="", timeout=None, **kw):
        if url.startswith("/"):
            url = self.base + url
        # 跨域请求（搜索引擎等）会被同源策略挡掉，退回 curl 指纹会话
        if not _same_host(url, self.base):
            return self.curl.request(method, url, timeout=timeout, **kw)
        params = kw.get("params")
        if params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(params, doseq=True)
        tab = self._ensure_tab()
        payload = {"action": "execute_js", "tab_id": tab,
                   "script": self._script(url, method, kw.get("data"))}
        text = _strip_suffix(self._run(payload, timeout=timeout or self.timeout))
        parts = text.split("\n", 2)
        if len(parts) < 3:
            raise BrowserError("浏览器返回无法解析: %s" % text[:200])
        try:
            status = int(parts[0].strip())
            ctype = parts[1].strip()
            content = base64.b64decode(parts[2].strip())
        except Exception as exc:
            raise BrowserError("浏览器返回无法解析: %s" % exc)
        return BrowserResponse(status, content, {"content-type": ctype})

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def close(self):
        pass
