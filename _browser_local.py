# -*- coding: utf-8 -*-
"""本地浏览器传输层：用 Selenium 驱动本机浏览器，页内 fetch 取数。

与 App 内 WebView 后端（_browser.py）同构：同一个页内 fetch 脚本、
同一套 base64 回传，区别只在于"谁来执行这个脚本"——
这里是本机 Chrome / Edge / Brave / Firefox，登录态由浏览器自己的
profile 携带，客户端同样不落 cookie。

桌面端（Windows / macOS / Linux）没有 Minis App 的 WebView 可借，
用这套后端，-b 就能跨平台生效。
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse


class LocalBrowserError(RuntimeError):
    pass


class _BrowserResponse:
    """与 _browser.BrowserResponse 同构的最小响应对象。"""

    def __init__(self, status_code, content, headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")

    def __repr__(self):
        return "<Response %d %d bytes>" % (self.status_code, len(self.content))


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
        r"Chromium\Application\chrome.exe",
        r"Google\Chrome for Testing\chrome.exe",
    ],
    "edge": [r"Microsoft\Edge\Application\msedge.exe"],
    "firefox": [r"Mozilla Firefox\firefox.exe"],
    "brave": [r"BraveSoftware\Brave-Browser\Application\brave.exe"],
}

# 找不到时的候选启动名
BROWSER_BIN = {
    "chrome": ["google-chrome", "google-chrome-stable", "chromium",
               "chromium-browser", "chrome"],
    "edge": ["microsoft-edge", "msedge"],
    "firefox": ["firefox"],
    "brave": ["brave-browser", "brave"],
}


def _default_browser_key():
    """读系统默认浏览器（Windows 用 UCRT / Linux 用 xdg）。"""
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"SOFTWARE\Microsoft\Windows\Shell\Associations"
                    r"\UrlAssociations\https\UserChoice") as k:
                prog, _ = winreg.QueryValueEx(k, "ProgId")
            p = prog.lower()
            for key in ("brave", "edge", "chrome", "firefox"):
                if key in p:
                    return key
        except Exception:
            pass
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
    import shutil
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

    # 1) Windows 注册表 App Paths（能装在自定义盘符的浏览器）
    if sys.platform.startswith("win"):
        try:
            import winreg
            for scope in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for key in ("chrome.exe", "msedge.exe", "firefox.exe",
                            "brave.exe"):
                    try:
                        with winreg.OpenKey(
                                scope,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                                r"\App Paths\%s" % key) as k:
                            val, _ = winreg.QueryValueEx(k, None)
                            if val:
                                add({"chrome.exe": "chrome",
                                     "msedge.exe": "edge",
                                     "firefox.exe": "firefox",
                                     "brave.exe": "brave"}[key], val)
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

    # 系统默认浏览器提前
    pref = _default_browser_key()
    if pref:
        found.sort(key=lambda kv: 0 if kv[0] == pref else 1)
    return found


# ---------------------------------------------------------------- 驱动构造

def make_driver(browser_key, browser_path, profile_dir=None, proxy=None,
                headless=False):
    """按浏览器类型构造 selenium driver（Chrome 系共用 --user-data-dir）。"""
    from selenium import webdriver
    if browser_key == "firefox":
        opts = webdriver.FirefoxOptions()
        if headless:
            opts.add_argument("-headless")
        if proxy:
            opts.add_argument("--proxy-server=%s" % proxy)
        if profile_dir:
            opts.add_argument("-profile")
            opts.add_argument(profile_dir)
        return webdriver.Firefox(options=opts)
    if browser_key == "edge":
        opts = webdriver.EdgeOptions()
    else:
        opts = webdriver.ChromeOptions()
    if browser_path:
        opts.binary_location = browser_path
    if headless:
        opts.add_argument("--headless=new")
    if profile_dir:
        opts.add_argument("--user-data-dir=%s" % profile_dir)
    if proxy:
        opts.add_argument("--proxy-server=%s" % proxy)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    # 本机已装 chromedriver 时直接用，免得 Selenium Manager 去网上抓版本
    service = None
    exe = shutil.which("chromedriver") or shutil.which("msedgedriver")
    if exe:
        try:
            from selenium.webdriver.chrome.service import Service
            service = Service(executable_path=exe)
        except Exception:
            service = None
    if browser_key == "edge":
        return webdriver.Edge(options=opts)
    if service is not None:
        return webdriver.Chrome(options=opts, service=service)
    return webdriver.Chrome(options=opts)


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
        self._drv = None
        self._curl = None
        self._at_origin = False

    # -- 懒启动浏览器 --
    @property
    def driver(self):
        if self._drv is None:
            self._drv = self._start()
        return self._drv

    def _start(self):
        try:
            import selenium  # noqa: F401
        except ImportError:
            raise LocalBrowserError(
                "需要 selenium：python -m pip install selenium")
        key, path = self.browser_key, self.browser_path
        if not key or not path:
            browsers = find_browsers()
            if not browsers:
                raise LocalBrowserError(
                    "未检测到 Chrome / Edge / Brave / Firefox，"
                    "请安装其一或改用默认传输层")
            key, path = browsers[0]
        try:
            return make_driver(key, path, self.profile_dir, self.proxy,
                               self.headless)
        except Exception as exc:
            raise LocalBrowserError("启动浏览器失败：%s" % exc)

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

    # -- 保证浏览器停在本站，才能带同源 cookie --
    def _ensure_origin(self):
        if self._at_origin:
            return
        drv = self.driver
        drv.get(self.base + "/")
        time.sleep(1.5)
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
        drv = self.driver
        script = self._script(url, method, kw.get("data"))
        try:
            text = drv.execute_async_script(
                "var cb=arguments[arguments.length-1];"
                "(async function(){" + script + "})()"
                ".then(function(v){cb(v);},function(e){cb('ERR:'+e);});")
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
        except Exception as exc:
            raise LocalBrowserError("浏览器返回无法解析: %s" % exc)
        return _BrowserResponse(status, content, {"content-type": ctype})

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def close(self):
        if self._drv is not None:
            try:
                self._drv.quit()
            except Exception:
                pass
            self._drv = None
