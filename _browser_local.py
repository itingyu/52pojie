# -*- coding: utf-8 -*-
"""本机浏览器传输层：用 Playwright 驱动系统已装的浏览器，页内 fetch 取数。

为什么不用 Selenium：
- Selenium 需要 chromedriver，且驱动大版本必须与浏览器一致；Selenium Manager
  要联网去 googlechromelabs.github.io 抓版本，国内基本连不上，还会把驱动
  下载到当前工作目录污染代码仓库。
- Playwright 可以直接用系统已安装的浏览器（executable_path 指向真实 exe），
  不需要下载任何浏览器或驱动，也不产生额外文件。

浏览器选择：读 Windows 注册表 UserChoice 的 ProgId，再顺着
HKCR\\<ProgId>\\shell\\open\\command 找到用户真正在用的那个 exe。
同一台机器可能装着多个 Chrome（不同盘/不同版本），只有走这一层才对。
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.parse


class LocalBrowserError(RuntimeError):
    pass


def _same_host(url, base):
    try:
        return (urllib.parse.urlsplit(url).netloc
                == urllib.parse.urlsplit(base).netloc)
    except Exception:
        return False


# ---------------------------------------------------------------- 浏览器探测

BROWSER_PATHS = {
    "chrome": [
        r"Google\Chrome\Application\chrome.exe",
        r"Chromium\Application\chromium.exe",
    ],
    "edge": [r"Microsoft\Edge\Application\msedge.exe"],
    "firefox": [r"Mozilla Firefox\firefox.exe"],
    "brave": [r"BraveSoftware\Brave-Browser\Application\brave.exe"],
}

BROWSER_BIN = {
    "chrome": ["google-chrome", "google-chrome-stable", "chromium",
               "chromium-browser", "chrome"],
    "edge": ["microsoft-edge", "msedge"],
    "firefox": ["firefox"],
    "brave": ["brave-browser", "brave"],
}


def _prog_id():
    """Windows 当前用户设置的默认 https 浏览器 ProgId。"""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\https\UserChoice") as k:
            prog, _ = winreg.QueryValueEx(k, "ProgId")
        return prog
    except Exception:
        return None


def _prog_id_exe(prog_id):
    """ProgId -> 实际可执行文件路径。

    UserChoice 的 ProgId 只说明「是哪家浏览器」，真正指向哪个 exe 要查
    HKCR 下的 ProgId shell open command。同机可能装有多个 Chrome
    （不同盘、不同版本），只有走这一层才能拿到用户真正在用的那个。
    """
    if not prog_id:
        return None
    try:
        import winreg
    except ImportError:
        return None
    bs = chr(92)
    sub = prog_id + bs + "shell" + bs + "open" + bs + "command"
    cls = "SOFTWARE" + bs + "Classes" + bs
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, cls + sub) as k:
                cmd, _ = winreg.QueryValueEx(k, None)
            if cmd:
                exe = cmd.split('"')[1] if '"' in cmd else cmd.split()[0]
                if os.path.exists(exe):
                    return exe
        except OSError:
            continue
    return None


def _browser_key_of(path):
    """由可执行文件路径反推浏览器类型 key。"""
    name = os.path.basename(path or "").lower()
    table = {
        "chrome.exe": "chrome", "msedge.exe": "edge",
        "firefox.exe": "firefox", "brave.exe": "brave",
    }
    if name in table:
        return table[name]
    if "firefox" in name:
        return "firefox"
    if "msedge" in name or "edge" in name:
        return "edge"
    if "brave" in name:
        return "brave"
    if "chrome" in name or "chromium" in name:
        return "chrome"
    return None


def _default_browser_key():
    """系统默认浏览器类型（Windows 用注册表 / Linux 用 xdg）。"""
    if sys.platform.startswith("win"):
        prog = _prog_id()
        exe = _prog_id_exe(prog)
        if exe:
            key = _browser_key_of(exe)
            if key:
                return key
        p = (prog or "").lower()
        for key in ("brave", "edge", "chrome", "firefox"):
            if key in p:
                return key
    else:
        try:
            out = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            p = out.lower()
            for key in ("brave", "edge", "chrome", "chromium", "firefox"):
                if key in p:
                    return "chrome" if key == "chromium" else key
        except Exception:
            pass
    return None


def find_browsers():
    """检测本机可用浏览器，返回 [(key, 路径)]，系统默认浏览器排最前。"""
    found = []
    seen = set()

    def add(key, path):
        if not path:
            return
        path = os.path.abspath(path)
        if path.lower() in seen or not os.path.exists(path):
            return
        seen.add(path.lower())
        found.append((key, path))

    # 1) Windows 注册表 App Paths（能发现装在自定义盘符的浏览器）
    if sys.platform.startswith("win"):
        try:
            import winreg
            names = {"chrome.exe": "chrome", "msedge.exe": "edge",
                     "firefox.exe": "firefox", "brave.exe": "brave"}
            for scope in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for exe_name, key in names.items():
                    try:
                        with winreg.OpenKey(
                                scope,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                                r"\App Paths\%s" % exe_name) as k:
                            val, _ = winreg.QueryValueEx(k, None)
                        if val:
                            add(key, val)
                    except OSError:
                        continue
        except ImportError:
            pass

    # 2) 常见安装目录
    roots = [os.environ.get("ProgramFiles", ""),
             os.environ.get("ProgramFiles(x86)", ""),
             os.environ.get("LOCALAPPDATA", ""),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")]
    for key, rels in BROWSER_PATHS.items():
        for root in roots:
            if not root:
                continue
            for rel in rels:
                add(key, os.path.join(root, rel))

    # 3) PATH
    for key, names in BROWSER_BIN.items():
        for name in names:
            exe = shutil.which(name)
            if exe:
                add(key, exe)
                break

    # 系统默认浏览器提前（用注册表真实路径，避免选到另一个版本的 Chrome）
    pref = default_browser()
    if pref:
        pkey, ppath = pref
        found.sort(key=lambda kv: 0 if (kv[0] == pkey
                                       and kv[1].lower() == ppath.lower())
                     else (1 if kv[0] != pkey else 2))
    return found


def default_browser():
    """系统默认浏览器的 (key, 路径)；取不到返回 None。

    优先用注册表 ProgId 指向的真实 exe —— 它才是用户双击链接时打开的那个。
    """
    if sys.platform.startswith("win"):
        exe = _prog_id_exe(_prog_id())
        if exe:
            key = _browser_key_of(exe)
            if key:
                return key, exe
    key = _default_browser_key()
    if key:
        for k, path in find_browsers():
            if k == key:
                return k, path
    return None


# ---------------------------------------------------------------- 会话

class LocalBrowserSession:
    """用本机浏览器当传输层：页内 fetch，登录态由浏览器 profile 携带。

    与 _browser.BrowserSession 同接口，可直接替换。
    """

    def __init__(self, base, timeout=40, profile_dir=None, browser_key=None,
                 browser_path=None, headless=False, proxy=None):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.profile_dir = profile_dir
        self.browser_key = browser_key
        self.browser_path = browser_path
        self.headless = headless
        self.proxy = proxy
        self.headers = {}
        self._pw = None
        self._ctx = None
        self._page = None
        self._curl = None
        self._at_origin = False

    # -- 懒启动浏览器 --
    @property
    def page(self):
        if self._page is None:
            self._page = self._start()
        return self._page

    def _launch_args(self):
        args = []
        if self.headless:
            args.append("--headless=new")
        if self.proxy:
            args.append("--proxy-server=%s" % self.proxy)
        args.append("--no-first-run")
        args.append("--no-default-browser-check")
        args.append("--disable-blink-features=AutomationControlled")
        return args

    def _start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise LocalBrowserError(
                "需要 playwright：python -m pip install playwright")
        key, path = self.browser_key, self.browser_path
        if not key or not path:
            browsers = find_browsers()
            if not browsers:
                raise LocalBrowserError(
                    "未检测到 Chrome / Edge / Brave / Firefox，"
                    "请安装其一或改用默认传输层")
            key, path = browsers[0]
        self.browser_key, self.browser_path = key, path
        self._pw = sync_playwright().start()
        try:
            # 用系统已装的浏览器（executable_path），不下载 playwright 自带浏览器
            ctx = self._pw.chromium.launch_persistent_context(
                self.profile_dir or _tmp_profile(),
                executable_path=path,
                headless=bool(self.headless),
                args=self._launch_args(),
                ignore_default_args=["--enable-automation"],
                viewport=None,
            )
        except Exception as exc:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None
            raise LocalBrowserError("启动浏览器失败：%s" % exc)
        self._ctx = ctx
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        return page

    @property
    def curl(self):
        """跨域回退：仍走 curl_cffi 的 Chrome 指纹。"""
        if self._curl is None:
            from curl_cffi import requests as _http
            self._curl = _http.Session(impersonate="chrome")
        return self._curl

    def _script(self, url, method, body):
        """页内抓取脚本：取原始字节再 base64，避免 GBK 被当 UTF-8 解。"""
        return (
            "var u=%s, m=%s, b=%s;"
            "var o={method:m,credentials:'include'};"
            "if(b!==null){o.body=b;}"
            "var r=await fetch(u,o);"
            "var ab=await r.arrayBuffer();"
            "var u8=new Uint8Array(ab),s='',C=0x8000;"
            "for(var i=0;i<u8.length;i+=C){"
            "s+=String.fromCharCode.apply(null,u8.subarray(i,i+C));}"
            "return ''+r.status+'\\n'+(r.headers.get('content-type')||'')"
            "+'\\n'+btoa(s);"
        ) % (json.dumps(url), json.dumps(method),
             json.dumps(body if body is not None else None))

    def _ensure_origin(self):
        """保证浏览器停在本站，才能带同源 cookie。"""
        if self._at_origin:
            return
        page = self.page
        page.goto(self.base + "/", wait_until="domcontentloaded",
                  timeout=self.timeout * 1000)
        self._at_origin = True

    def request(self, method="GET", url="", timeout=None, **kw):
        if url.startswith("/"):
            url = self.base + url
        # 跨域请求（搜索引擎等）同源策略挡不住，退回 curl 指纹会话
        if not _same_host(url, self.base):
            return self.curl.request(method, url, timeout=timeout, **kw)
        params = kw.get("params")
        if params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(params, doseq=True)
        self._ensure_origin()
        page = self.page
        script = self._script(url, method, kw.get("data"))
        try:
            text = page.evaluate("(async () => {" + script + "})()")
        except Exception as exc:
            raise LocalBrowserError("浏览器执行失败：%s" % exc)
        text = (text or "").strip()
        if text.startswith("ERR:"):
            raise LocalBrowserError("浏览器请求失败：%s" % text[4:200])
        parts = text.split("\n", 2)
        if len(parts) < 3:
            raise LocalBrowserError("浏览器返回无法解析: %s" % text[:200])
        try:
            status = int(parts[0].strip())
            ctype = parts[1].strip()
            content = base64.b64decode(parts[2].strip())
        except Exception:
            raise LocalBrowserError("浏览器返回无法解析: %s" % text[:200])
        return _Response(status, ctype, content, self.headers)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def close(self):
        try:
            if self._ctx is not None:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = self._page = None


class _Response:
    """最小 Response 替身：只需 status/headers/content。"""

    def __init__(self, status, ctype, content, headers=None):
        self.status_code = status
        self.headers = _Headers(ctype, headers or {})
        self.content = content
        self.text = content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)

    @property
    def ok(self):
        return 200 <= self.status_code < 400


class _Headers(dict):
    def __init__(self, ctype, extra):
        super().__init__(extra or {})
        if ctype:
            self["content-type"] = ctype


def _tmp_profile():
    """没有指定 profile 时用临时目录（不污染用户数据）。"""
    import tempfile
    return tempfile.mkdtemp(prefix="52pj-profile-")


# ---------------------------------------------------------------- 人工登录

def open_login_window(browser_key=None, browser_path=None, profile_dir=None,
                      proxy=None, headless=False, timeout=300,
                      on_poll=None):
    """打开登录页，等用户手动登录。

    on_poll: 每次轮询时调用，返回 True 表示登录完成（拿到 auth cookie）。
    返回 (cookies, fingerprint)。
    """
    from playwright.sync_api import sync_playwright
    key, path = browser_key, browser_path
    if not key or not path:
        browsers = find_browsers()
        if not browsers:
            raise LocalBrowserError("未检测到可用浏览器")
        key, path = browsers[0]
    args = ["--no-first-run", "--no-default-browser-check"]
    if proxy:
        args.append("--proxy-server=%s" % proxy)
    if headless:
        args.append("--headless=new")
    pw = sync_playwright().start()
    ctx = None
    try:
        ctx = pw.chromium.launch_persistent_context(
            profile_dir or _tmp_profile(),
            executable_path=path,
            headless=bool(headless),
            args=args,
            ignore_default_args=["--enable-automation"],
            viewport=None,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.52pojie.cn/member.php?mod=logging&action=login",
                  wait_until="domcontentloaded", timeout=60000)
        cookies = []
        deadline = __import__("time").time() + timeout
        while __import__("time").time() < deadline:
            __import__("time").sleep(2)
            try:
                cookies = ctx.cookies()
            except Exception:
                continue
            if on_poll:
                if on_poll(cookies):
                    break
        try:
            fingerprint = page.evaluate(
                "var u=navigator.userAgentData;return {ua:navigator.userAgent,"
                "brands:u?u.brands:null,platform:u?u.platform:null,"
                "mobile:u?u.mobile:false,lang:navigator.language};")
        except Exception:
            fingerprint = {}
        return cookies, fingerprint
    finally:
        try:
            if ctx is not None:
                ctx.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
