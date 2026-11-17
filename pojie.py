#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""52pj —— 52pojie.cn（吾爱破解）命令行客户端

只读浏览工具：列板块 / 列帖子 / 看帖（含楼层回复）/ 搜索 / 登录看私密内容
依赖：curl_cffi（强制 Chrome TLS 指纹）, beautifulsoup4
"""
import argparse
import getpass
import json
import os
import random
import re
import shutil
import sys
import time
import urllib.parse
from http.cookiejar import Cookie

try:
    # 强制走 curl_cffi 的 Chrome TLS/JA3 指纹：不提供 requests 降级，
    # 缺库直接退出，避免裸 TLS 请求被风控识别
    from curl_cffi import requests as _http
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "错误：缺少 curl_cffi，请求必须携 Chrome 指纹。\n"
        "  python -m pip install curl_cffi\n")
    raise SystemExit(2)
try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None

BASE = "https://www.52pojie.cn"
# 请求间隔范围（秒）：每次请求随机取一个值，避免固定节奏被风控识别
DELAY_MIN = 0.7
DELAY_MAX = 1.3

# 固定走 curl_cffi 的 Chrome TLS/JA3 指纹；UA 也由它按 profile 自动对齐，
# 手写 UA 反而会和 TLS 指纹对不上
IMPERSONATE = os.environ.get("POJIE_IMPERSONATE") or "chrome"
DEFAULT_HOME = os.path.join(os.path.expanduser("~"), ".52pj")
HOME = DEFAULT_HOME

ERR = sys.stderr


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _store
import _browser_local
import _browser

try:
    import _ui
except ImportError:  # 打包成单文件时把 _ui 的内容内联进来
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("_ui", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_ui.py"))
    _ui = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_ui)


def soup_of(resp):
    """按页面 meta charset 解码，返回 BeautifulSoup。"""
    return BeautifulSoup(resp.content, "html.parser")


def text_of(node, sep="\n"):
    if node is None:
        return ""
    t = node.get_text(sep)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def die(msg, code=1):
    ERR.write("错误: %s\n" % msg)
    sys.exit(code)


def info(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _iter_cookies_full(container):
    """兼容 requests / curl_cffi 的 cookie 容器，产出完整字段 dict。

    比 _iter_cookies 多带 expires / secure / http_only，供落库使用。
    http.cookiejar 把 HttpOnly 放在非标准属性 _rest 里。
    """
    jar = getattr(container, "jar", None)
    items = jar if jar is not None else container
    for c in items:
        if isinstance(c, (tuple, list)) and len(c) >= 4:
            d = {"name": c[0], "value": c[1], "domain": c[2],
                 "path": c[3] or "/"}
            if len(c) > 4 and isinstance(c[4], dict):
                d.update(c[4])
            yield d
            continue
        rest = getattr(c, "_rest", None) or {}
        yield {"name": getattr(c, "name", ""),
               "value": getattr(c, "value", ""),
               "domain": getattr(c, "domain", "") or "",
               "path": getattr(c, "path", "/") or "/",
               "expires": int(getattr(c, "expires", 0) or 0),
               "secure": bool(getattr(c, "secure", False)),
               "http_only": bool("HttpOnly" in rest
                                 or getattr(c, "http_only", False))}


def _iter_cookies(container):
    """兼容 requests / curl_cffi 两种 cookie 容器的遍历，统一产出
    (name, value, domain, path)。

    requests 的 session.cookies 和 curl_cffi 的 session.cookies 都内含
    一个 http.cookiejar.CookieJar（属性名 .jar），里面的元素是标准
    Cookie 对象（有 .name/.value/.domain/.path）。直接对容器本身迭代
    在 curl_cffi 下拿到的是 cookie 名字符串，必须走 .jar。
    """
    jar = getattr(container, "jar", None)
    if jar is not None:
        for c in jar:
            yield (getattr(c, "name", ""), getattr(c, "value", ""),
                   getattr(c, "domain", ""), getattr(c, "path", "/") or "/")
        return
    for c in container:
        if isinstance(c, (tuple, list)) and len(c) >= 4:
            yield (c[0], c[1], c[2], c[3])
        else:
            yield (getattr(c, "name", ""), getattr(c, "value", ""),
                   getattr(c, "domain", ""), getattr(c, "path", "/"))


def browser_profile_dir(home):
    """浏览器 profile 目录：auth 与传输层共用，登录态才能传递。"""
    return os.path.join(home or DEFAULT_HOME, "browser-profile")


def _browser_session(home):
    """挑一个可用的浏览器传输层后端。

    优先用 Minis App 内已登录的 WebView（Android），没有就退回本机浏览器
    （桌面端），两者提供同一个"页内 fetch"能力。
    """
    if shutil.which("minis-browser-use"):
        try:
            return _browser.BrowserSession(BASE)
        except Exception:
            pass
    return _browser_local.LocalBrowserSession(
        BASE, profile_dir=browser_profile_dir(home))


class Client:
    """带 cookie 持久化与限速的 52pj 会话。"""

    def __init__(self, home=DEFAULT_HOME, delay=None, cookie_file=None,
                 delay_min=None, delay_max=None, transport="curl"):
        self.home = home
        self.db = _store.connect(home, cookie_file)
        self.cookie_file = _store.db_path(home, cookie_file)
        # 请求间隔在 [delay_min, delay_max] 之间随机取，避免固定节奏被风控识别
        self.delay_min = delay_min if delay_min is not None else (
            delay * 0.75 if delay else DELAY_MIN)
        self.delay_max = delay_max if delay_max is not None else (
            delay * 1.5 if delay else DELAY_MAX)
        if self.delay_min > self.delay_max:
            self.delay_min, self.delay_max = self.delay_max, self.delay_min
        self.delay = delay
        # 首次请求也要遵守间隔，故 last 初始化为当前时刻
        self.last = time.time()
        self.fp = {}
        self.last_url = None   # 上一页地址，用作下一次的 Referer
        # 传输层：curl=本地直连（curl_cffi 指纹）；browser=借道 App 内已登录的
        # WebView 发请求，登录态由 App 携带，客户端不存 cookie
        self.transport = transport
        if transport == "browser":
            self.s = _browser_session(home)
        else:
            # 所有请求共用同一个带 Chrome 指纹的会话
            self.s = _http.Session(impersonate=IMPERSONATE)
        self.s.headers.update({
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        if transport != "browser":
            self.load_cookies()

    # ---------- cookie（存 SQLite） ----------
    def load_cookies(self):
        try:
            rows = _store.get_cookies(self.db)
        except Exception:
            return
        fp = _store.get_meta(self.db, "fingerprint")
        if fp:
            try:
                self.fp = json.loads(fp)
            except Exception:
                self.fp = {}
        for c in rows:
            if not c.get("name"):
                continue
            dom = c.get("domain") or None
            exp = int(c.get("expires") or 0)
            if exp and exp < time.time():      # 过期的不再带
                continue
            try:
                jar = getattr(self.s.cookies, "jar", None)
                if jar is not None and (exp or c.get("secure")
                                        or c.get("http_only")):
                    jar.set_cookie(Cookie(
                        0, c["name"], c.get("value") or "", None, False,
                        dom or "", bool(dom),
                        bool(dom and dom.startswith(".")),
                        c.get("path") or "/", True, bool(c.get("secure")),
                        exp or None, False, None, None,
                        {"HttpOnly": None} if c.get("http_only") else {},
                        False))
                    continue
                self.s.cookies.set(c["name"], c.get("value"),
                                   domain=dom,
                                   path=c.get("path") or "/")
            except Exception:
                pass

    def save_cookies(self, ua=None, fingerprint=None):
        if getattr(self, "transport", "curl") == "browser":
            return          # 浏览器自带会话，客户端不落库
        for c in _iter_cookies_full(self.s.cookies):
            if not c["name"]:      # 站点会下发空名 cookie，不存
                continue
            _store.set_cookie(self.db, c)
        _store.set_meta(self.db, "ua", ua or self.s.headers.get("User-Agent"))
        _store.set_meta(self.db, "fingerprint",
                        json.dumps(fingerprint or self.fp or {}, ensure_ascii=False))

    def logged_in(self):
        """判断当前是否已登录，返回用户名或 None。

        只有登录后才会渲染「退出」链接，用它做硬判据；
        游客首页也有别人的 uid 链接，不能拿它当依据。
        """
        try:
            r = self.get("/forum.php")
        except Exception:
            return None
        if r is None:
            return None
        sp = soup_of(r)
        if not sp.select_one("a[href*='action=logout']") and \
                "欢迎您回来" not in r.text:
            return None
        box = sp.select_one("#um .vwmy") or sp.select_one(".vwmy")
        if box is not None:
            m = re.search(r"欢迎您回来[，,]\s*(\S+)", text_of(box))
            if m:
                return m.group(1)
            a = box.select_one('a[href*="mod=space&uid="]')
            if a is not None and text_of(a).strip():
                return text_of(a).strip()
        um = sp.select_one("#um") or sp
        for a in um.select('a[href*="mod=space&uid="]'):
            name = text_of(a).strip()
            if name and name not in ("登录", "注册"):
                return name
        return None

    # ---------- http ----------
    def _throttle(self):
        """随机间隔限速：每次请求前在 [min, max] 里随机取一个值作为间隔。"""
        wait = random.uniform(self.delay_min, self.delay_max)
        gap = time.time() - self.last
        if gap < wait:
            time.sleep(wait - gap)
        self.last = time.time()

    def _browser_headers(self, method, url, referer=None, ajax=False,
                         external=False):
        """一套与真实 Chrome 一致的请求头（TLS 指纹由 curl_cffi 负责）。"""
        fp = self.fp or {}
        h = {
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,image/apng,*/*;q=0.8,"
                       "application/signed-exchange;v=b3;q=0.7"),
            "Accept-Language": fp.get("accept_language")
                               or "zh-CN,zh;q=0.9,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Site": ("cross-site" if external else "same-origin")
                              if referer else "none",
            "Cache-Control": "max-age=0",
        }
        if ajax:
            h["Accept"] = "*/*"
            h["X-Requested-With"] = "XMLHttpRequest"
            h["Sec-Fetch-Mode"] = "cors"
            h["Sec-Fetch-Dest"] = "empty"
            h.pop("Sec-Fetch-User", None)
        if referer:
            h["Referer"] = referer
        if method.upper() == "POST":
            h["Origin"] = BASE
            h["Content-Type"] = "application/x-www-form-urlencoded"
            h["Sec-Fetch-Site"] = "same-origin"
        return h

    def request(self, method, path, **kw):
        url = path if path.startswith("http") else BASE + path
        ext = bool(kw.pop("external", False))
        ref = kw.pop("referer", None) or (None if ext else self.last_url)
        headers = self._browser_headers(method, url, referer=ref,
                                        ajax=bool(kw.pop("ajax", False)),
                                        external=ext)
        headers.update(kw.pop("headers", None) or {})
        kw["headers"] = headers
        self._throttle()
        r = None
        for attempt in range(3):
            try:
                r = self.s.request(method, url, timeout=40, **kw)
            except Exception as e:
                if attempt == 2:
                    raise
                info("请求失败(%s)，重试…" % e)
                time.sleep(2)
                continue
            if not ext:
                self.last_url = url
            if r.status_code == 429:
                info("被限速(429)，等待 10 秒…")
                time.sleep(10)
                continue
            return r
        return r

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    # ---------- 通用 ----------
    def formhash(self, resp=None):
        r = resp or self.get("/")
        m = re.search(r'name="formhash"\s+value="([0-9a-fA-F]+)"', r.text)
        return m.group(1) if m else None

    def page_message(self, resp):
        """提取 Discuz 提示信息页里的消息文本。"""
        sp = soup_of(resp)
        for sel in ("#messagetext", ".alert_error", ".alert_info", ".alert_warning"):
            n = sp.select_one(sel)
            if n:
                t = text_of(n)
                if t:
                    return t
        m = re.search(r"showmessage\((.*?)\);", resp.text, re.S)
        if m:
            return m.group(1)
        return ""


# --------------------------------------------------------------------------- #
# 只读命令
# --------------------------------------------------------------------------- #
def parse_forum_list(sp):
    """解析论坛首页的版块清单。

    Discuz 里 forum-N-1.html 是「版块」(fid=N)，forum.php?mod=forumdisplay&fid=N
    是同一个版块的列表页；首页导航里的「XX新帖」只是快捷入口，名字和版块真名对不上。
    """
    forums = {}
    for a in sp.select('a[href*="forum-"]'):
        m = re.search(r"forum-(\d+)-1\.html", a.get("href", ""))
        if not m:
            continue
        fid = int(m.group(1))
        name = text_of(a)
        # 名称里常夹带说明文字与换行，只取第一行
        name = next((ln.strip() for ln in name.splitlines() if ln.strip()), "")
        name = re.sub(r"\s+", " ", name)
        if not name or len(name) > 24:
            continue
        forums.setdefault(fid, name)
    return forums


def cmd_forums(args, cl):
    """列出板块（fid + 名称）。板块很稳定，缓存一天。"""
    forums = fetch_forums(cl, force=getattr(args, "refresh", False))
    if not forums:
        die("未解析到板块列表（页面结构可能已变化）")
    if getattr(args, "grep", None):
        kw = args.grep.lower()
        forums = {f: n for f, n in forums.items()
                  if kw in n.lower() or kw in str(f)}
        if not forums:
            die("没有匹配的版块（关键词：%s）" % args.grep)
    if getattr(args, "json", False):
        _ui.json_out([{"fid": f, "name": n} for f, n in sorted(forums.items())])
        return 0
    items = sorted(forums.items())
    st = load_state(args.home)
    save_list(args.home, st, "boards",
              [{"id": f, "label": n} for f, n in items])
    rows = [("#%d" % (i + 1), str(f), n) for i, (f, n) in enumerate(items)]
    _ui.table(["序号", "FID", "版块"], rows, aligns=[">", "<", "<"])
    _ui.out()
    _ui.out(_ui.c("共 %d 个版块 · select #<序号> 直接选中 · 或 threads -f <#序号/FID/名称>"
                  % len(items), "grey"))
    return 0


def parse_thread_rows(sp):
    rows = []
    for tb in sp.select('tbody[id^="normalthread_"], tbody[id^="stickthread_"]'):
        tr = tb.find("tr")
        if tr is None:
            continue
        link = tr.select_one("a.xst") or tr.select_one('a[href*="thread-"]')
        if link is None:
            continue
        m = re.search(r"thread-(\d+)-", link.get("href", ""))
        if not m:
            continue
        tid = int(m.group(1))
        title = text_of(link)
        cits = tr.select("cite a")
        author = text_of(cits[0]) if cits else ""
        last_author = text_of(cits[-1]) if len(cits) > 1 else ""
        ems = tr.select("td.by em")
        post_time = text_of(ems[0]) if ems else ""
        last_time = ""
        if len(ems) > 1:
            a = ems[1].select_one("a")
            last_time = text_of(a) if a else text_of(ems[1])
        num = tr.select_one("td.num")
        replies = views = ""
        if num:
            nums = num.find_all("a")
            em = num.find("em")
            if nums:
                replies = text_of(nums[0])
            if em:
                views = text_of(em)
        pinned = tb.get("id", "").startswith("stickthread_")
        rows.append(dict(tid=tid, title=title, author=author, time=post_time,
                         replies=replies, views=views,
                         last_author=last_author, last_time=last_time,
                         pinned=pinned))
    return rows


_FORUM_CACHE = {}


def fetch_forums(cl, force=False):
    """板块列表很稳定，缓存一天（SQLite cache 表）。--refresh 可强刷。"""
    global _FORUM_CACHE
    if _FORUM_CACHE and not force:
        return _FORUM_CACHE
    if not force:
        raw = _store.cache_get(cl.db, "boards", ttl=_store.CACHE_TTL)
        if raw:
            try:
                _FORUM_CACHE = {int(k): v for k, v in json.loads(raw).items()}
                return _FORUM_CACHE
            except Exception:
                pass
    got = parse_forum_list(soup_of(cl.get("/forum.php")))
    if got:
        _FORUM_CACHE = got
        _store.cache_set(cl.db, "boards", json.dumps(
            {str(k): v for k, v in got.items()}, ensure_ascii=False))
    return _FORUM_CACHE


# --------------------------------------------------------------------------- #
# 选择状态（类似工作目录：select 过之后，后续命令默认作用于它）
# --------------------------------------------------------------------------- #
BIN = "52pj.bat" if os.name == "nt" else "52pj"


def equiv(*parts):
    """打印与当前上下文等价的显式命令。"""
    cmd = " ".join(str(x) for x in parts if x not in (None, "", False))
    _ui.out(_ui.c("等价命令  %s %s" % (BIN, cmd), "grey"))


def state_path(home):
    return _store.db_path(home)


def _db(home):
    return _store.connect(home or DEFAULT_HOME)


def load_state(home):
    """选择状态，从 SQLite 还原成原来的 dict 形状。"""
    sel = _store.get_selection(_db(home))
    st = {}
    b = sel.get("board") or {}
    if b.get("id"):
        st["board"] = {"fid": b["id"], "name": b.get("title") or ""}
    th = sel.get("thread") or {}
    if th.get("id"):
        st["thread"] = {"tid": th["id"], "title": th.get("title") or "",
                        "page": th.get("page") or 1}
    return st


def save_state(home, st):
    db = _db(home)
    b = st.get("board") or {}
    if b.get("fid"):
        _store.set_selection(db, "board", b["fid"], b.get("name") or "", 1)
    th = st.get("thread") or {}
    if th.get("tid"):
        _store.set_selection(db, "thread", th["tid"], th.get("title") or "",
                             int(th.get("page") or 1))


# ---- 列表序号（每次列出结果就记住，序号可直接当参数用） ----
def save_list(home, st, kind, items):
    _store.save_list(_db(home), kind,
                     [{"id": it["id"], "label": it.get("label", "")} for it in items])


def _idx_num(n):
    try:
        return int(str(n).strip().lstrip("#"))
    except Exception:
        return None


def index_id(st, kind, n):
    """把序号 n（可带 #）换成真实 id；不存在返回 None。"""
    num = _idx_num(n)
    if num is None:
        return None
    for it in _store.get_list(_db(HOME), kind):
        if it["seq"] == num:
            return it["id"]
    return None


def list_label(st, kind, n):
    num = _idx_num(n)
    for it in _store.get_list(_db(HOME), kind):
        if it["seq"] == num:
            return it.get("label", "")
    return ""


def resolve_number(st, n, kinds):
    """在给定的几类列表里按序号找 id，返回 (id, kind, label)。"""
    for kind in kinds:
        got = index_id(st, kind, n)
        if got:
            return got, kind, list_label(st, kind, n)
    return None, None, None


def get_sel_board(st):
    b = st.get("board") or {}
    return b.get("fid"), b.get("name")


def get_sel_thread(st):
    th = st.get("thread") or {}
    return th.get("tid"), th.get("page") or 1, th.get("title") or ""


def set_sel_board(home, st, fid, name):
    st["board"] = {"fid": int(fid), "name": name}
    st["thread"] = {}
    save_state(home, st)


def set_sel_thread(home, st, tid, title="", page=1):
    th = dict(tid=str(tid), title=title or "", page=int(page or 1))
    st["thread"] = th
    save_state(home, st)


_SMALL = 1000


def is_index_like(s):
    """列表序号必须带 # 前缀（#3），与真实 ID 彻底区分开。"""
    s = str(s or "").strip()
    return s.startswith("#") and s[1:].isdigit()


def pick_kinds(st, *prefer):
    kinds = [k for k in prefer if k]
    last = st.get("last_kind")
    if last and last not in kinds:
        kinds.insert(0, last)
    for k in ("threads", "search", "boards"):
        if k not in kinds:
            kinds.append(k)
    return kinds


def interpret_index(st, s):
    """把 '#3' 解释成列表第 3 项；返回 (kind, id, label) 或 (None, None, None)。"""
    if not is_index_like(s):
        return None, None, None
    n = int(str(s).strip().lstrip("#"))
    for kind in pick_kinds(st):
        got = index_id(st, kind, n)
        if got:
            return kind, got, list_label(st, kind, n)
    return None, None, None


def looks_like_tid(s):
    s = str(s or "")
    return bool(re.search(r"thread-\d+", s) or re.search(r"[?&]tid=\d+", s)
                or re.fullmatch(r"\d{4,}", s))


def resolve_fid(cl, key):
    """把用户给的板块标识解析成 fid。

    支持：数字 fid、版块名（'病毒分析'）、版块名的一部分（'病毒'）、
    英文/数字缩写。找不到时给出最接近的候选。
    """
    key = str(key).strip()
    if key.isdigit():
        return int(key)
    fetch_forums(cl)
    kw = key.lower()
    # 完全匹配
    for fid, name in _FORUM_CACHE.items():
        if name.lower() == kw:
            return fid
    # 去掉书名号等装饰后匹配
    def norm(s):
        return s.replace("『", "").replace("』", "").replace("「", "").replace("」", "").strip().lower()
    for fid, name in _FORUM_CACHE.items():
        if norm(name) == norm(key):
            return fid
    # 包含匹配
    hits = [f for f, n in _FORUM_CACHE.items() if kw in n.lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        die("'%s' 匹配到多个版块，请写得更具体：%s"
            % (key, "、".join("%s(%d)" % (_FORUM_CACHE[f], f) for f in hits[:8])))
    # 近似（去掉装饰后包含）
    hits = [f for f, n in _FORUM_CACHE.items() if kw in norm(n)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        die("'%s' 匹配到多个版块：%s"
            % (key, "、".join("%s(%d)" % (_FORUM_CACHE[f], f) for f in hits[:8])))
    # 找最接近的
    import difflib
    close = difflib.get_close_matches(key, list(_FORUM_CACHE.values()), n=3, cutoff=0.4)
    tip = ("你是不是想找：%s" % "、".join(close)) if close else \
          ("可用版块：%s ..." % "、".join(list(_FORUM_CACHE.values())[:6]))
    die("没有名为 '%s' 的版块。%s（用 forums 查看全部）" % (key, tip))


def cmd_select(args, cl):
    """选择当前板块 / 帖子，后续命令默认作用于它。"""
    st = load_state(args.home)
    target = (args.target or "").strip()

    if getattr(args, "clear", False):
        if getattr(args, "clear_board", False):
            st["board"] = {}
            st["thread"] = {}
        elif getattr(args, "clear_thread", False):
            st["thread"] = {}
        else:
            st = {}
        save_state(args.home, st)
        _ui.out(_ui.c("已清除选择", "green"))
        return 0

    if not target:
        return show_selection(args, st)

    fid, bname = get_sel_board(st)
    tid, tpage, ttitle = get_sel_thread(st)

    # 纯数字小序号：按最近一次列表解析（boards / threads / search）
    idx_kind = idx_id = idx_label = None
    if not getattr(args, "board_only", False) and not getattr(args, "thread_only", False):
        idx_kind, idx_id, idx_label = interpret_index(st, target)
        if idx_kind:
            _ui.out(_ui.c("序号 %s → %s：%s" %
                          (target, {"boards": "板块列表", "threads": "帖子列表",
                                    "search": "搜索结果"}[idx_kind],
                           (idx_label or "")[:50]), "grey"))

    if idx_kind == "boards":
        target = idx_id
    elif idx_kind in ("threads", "search"):
        target = idx_id
        args.thread_only = True

    as_thread = getattr(args, "thread_only", False) or (
        not getattr(args, "board_only", False) and looks_like_tid(target))

    if as_thread:
        ntid = normalize_tid(target)
        r = cl.get("/forum.php", params={"mod": "viewthread", "tid": ntid})
        sp = soup_of(r)
        ttl, posts = parse_thread_page(sp)
        if not ttl and not posts:
            m = re.search(r'id="messagetext"[^>]*>(.*?)</', r.text, re.S)
            reason = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""
            die("选不了这个帖子：%s" % (reason[:60] or "帖子不存在或需要登录"))
        bfid, btitle = "", ""
        pt = sp.select_one("#pt")
        for a in (pt.select("a") if pt else []):
            mm = re.search(r"forum-(\d+)-1\.html", a.get("href", "") or "")
            if mm:
                bfid, btitle = mm.group(1), text_of(a)
        if bfid:
            st["board"] = {"fid": int(bfid), "name": btitle}
        st["thread"] = {"tid": str(ntid), "title": ttl, "page": 1}
        save_state(args.home, st)
        _ui.out(_ui.c("已选择帖子", "green") + "  %s  (TID %s)" % (ttl or "(无标题)", ntid))
        if bfid:
            _ui.out(_ui.c("  所属板块：%s (%s) · 楼层 %d 层" %
                          (btitle, bfid, len(posts)), "grey"))
        equiv("thread", ntid)
        equiv("threads", "-f", st["board"].get("fid") if st.get("board") else None)
        _ui.out(_ui.c("  接下来：thread 看正文 · thread --next 翻页 · threads 看本版列表", "grey"))
        return 0

    fid2 = resolve_fid(cl, target)
    if not _FORUM_CACHE:
        r = cl.get("/forum.php")
        _FORUM_CACHE.update(parse_forum_list(soup_of(r)))
    name = _FORUM_CACHE.get(fid2, str(target))
    set_sel_board(args.home, st, fid2, name)
    _ui.out(_ui.c("已选择板块", "green") + "  %s  (fid %d)" % (name, fid2))
    equiv("threads", "-f", fid2)
    _ui.out(_ui.c("  接下来：threads 看帖子列表 · latest 看全站新帖", "grey"))
    return 0


def show_selection(args, st):
    fid, bname = get_sel_board(st)
    tid, tpage, ttitle = get_sel_thread(st)
    if getattr(args, "json", False) or _ui.json_mode():
        _ui.json_out(st)
        return 0
    if not fid and not tid:
        _ui.out(_ui.c("当前没有选择", "yellow"))
        _ui.out(_ui.c("  select 32           选择板块（也可写板块名）", "grey"))
        _ui.out(_ui.c("  select 2137132      选择帖子（也可粘网址）", "grey"))
        return 1
    if fid:
        _ui.out(_ui.c("板块 ", "grey") + _ui.c("%s" % bname, "bold") + _ui.c(" (%s)" % fid, "grey"))
    if tid:
        _ui.out(_ui.c("帖子 ", "grey") + _ui.c("%s" % (ttitle or "(无标题)"), "bold")
                + _ui.c(" (TID %s · 第 %s 页)" % (tid, tpage), "grey"))
    return 0


def cmd_status(args, cl):
    """显示当前选择 + 登录状态。"""
    st = load_state(args.home)
    fid, bname = get_sel_board(st)
    tid, tpage, ttitle = get_sel_thread(st)
    who = cl.logged_in()
    if getattr(args, "json", False) or _ui.json_mode():
        _ui.json_out({"board": st.get("board") or None,
                      "thread": st.get("thread") or None,
                      "logged_in": bool(who), "user": who or None})
        return 0
    if fid:
        _ui.out(_ui.c("板块  ", "grey") + _ui.c(bname or "", "bold")
                + _ui.c("  fid %s" % fid, "grey"))
    if tid:
        _ui.out(_ui.c("帖子  ", "grey") + _ui.c(ttitle or "(无标题)", "bold")
                + _ui.c("  TID %s · 第 %s 页" % (tid, tpage), "grey"))
    if not fid and not tid:
        _ui.out(_ui.c("尚未选择板块/帖子（select 板块名 或 select TID）", "yellow"))
    _ui.out(_ui.c("登录  ", "grey") + (_ui.c(who, "green") if who else _ui.c("未登录", "yellow")))
    if fid:
        equiv("threads", "-f", fid)
    if tid:
        equiv("thread", tid, "--page %s" % tpage if int(tpage) > 1 else None)
    _ui.out(_ui.c("状态文件  %s" % state_path(args.home), "grey"))
    return 0


def cmd_threads(args, cl):
    """列出某板块的帖子（不给 --fid 就用已选择的板块）。"""
    st = load_state(args.home)
    from_sel = not args.fid
    if args.fid:
        fid = None
        if is_index_like(args.fid):
            got, kind, label = resolve_number(st, args.fid, ["boards"])
            if got:
                fid = int(got)
                _ui.out(_ui.c("序号 %s → 板块列表：%s" %
                              (args.fid, (label or "")[:40]), "grey"))
            else:
                die("板块列表里没有序号 %s。先运行 52pj forums 看看。" % args.fid)
        if fid is None:
            fid = resolve_fid(cl, args.fid)
    else:
        fid, _sname = get_sel_board(st)
        if not fid:
            die("还没有选择板块。先 select 板块名（如 select 病毒分析），"
                "或直接 threads --fid 32")
    params = {"mod": "forumdisplay", "fid": fid}
    if args.page:
        params["page"] = args.page
    if args.typeid:
        params["filter"] = "typeid"
        params["typeid"] = args.typeid
    r = cl.get("/forum.php", params=params)
    sp = soup_of(r)
    title = sp.select_one("title")
    rows = parse_thread_rows(sp)
    if not rows:
        info("（本页无帖子，或需要登录/被风控拦截）")
        return 0
    if getattr(args, "no_pin", False):
        rows = [x for x in rows if not x["pinned"]]
    if getattr(args, "pin_only", False):
        rows = [x for x in rows if x["pinned"]]
    if getattr(args, "grep", None):
        kw = args.grep.lower()
        rows = [x for x in rows
                if kw in x["title"].lower() or kw in x["author"].lower()]
    if getattr(args, "json", False):
        _ui.json_out(rows)
        return 0
    _ui.heading(_clean_board_title(text_of(title) if title else "板块 %s" % args.fid),
                "来自 select 的选择" if from_sel else None)
    save_list(args.home, st, "threads",
              [{"id": x["tid"], "label": x["title"]} for x in rows])
    out_rows = []
    for i, x in enumerate(rows, 1):
        mark = _ui.c("置顶 ", "magenta") if x["pinned"] else ""
        out_rows.append(("#%d" % i, str(x["tid"]), _ui.c(x["replies"] or "-", "green"),
                         x["author"], _ui.short_time(x["time"]),
                         x["views"] or "-", mark + x["title"]))
    _ui.table(["序号", "TID", "回复", "作者", "时间", "浏览", "标题"], out_rows,
              aligns=[">", "<", ">", "<", "<", ">", "<"])
    _ui.out()
    _ui.out(_ui.c("共 %d 条 · select #<序号> 选中 · thread #<序号> 直接读" % len(rows), "grey"))
    equiv("threads", "-f", fid,
          "--page %d" % args.page if args.page and args.page > 1 else None,
          "--no-pin" if getattr(args, "no_pin", False) else None,
          "--pin-only" if getattr(args, "pin_only", False) else None,
          "--grep %s" % args.grep if getattr(args, "grep", None) else None)
    fid2, _bname = get_sel_board(st)
    if getattr(args, "keep", False):
        fid2 = fid
    if fid2 != fid:
        bname = _clean_board_title(text_of(title) if title else str(fid))
        set_sel_board(args.home, st, fid, bname)
        _ui.out(_ui.c("（已把「%s」记为当前选择）" % bname, "grey"))
    return 0


def _clean_board_title(s):
    """把 '『病毒分析区』 - 吾爱破解 - 52pojie.cn' 削成 '『病毒分析区』'。"""
    s = re.sub(r"\s*-\s*吾爱破解.*$", "", s or "")
    return s.strip()


def _floor_num(floor):
    """从 '11楼' / '楼主 · 1楼' 里取数字，取不到给大数排后面。"""
    m = re.search(r"(\d+)", floor or "")
    return int(m.group(1)) if m else 10 ** 9


def _floor_int(label):
    m = re.search(r"(\d+)", label or "")
    return int(m.group(1)) if m else None


def locate_floor(cl, tid, target, authorid=None):
    """找到第 target 楼所在的（页, 页内下标）。楼层顺序基本线性，先估再校正。"""
    guess = max(1, (target - 1) // 10 + 1)
    tried = {}
    for pg in [guess, guess - 1, guess + 1, guess + 2, guess - 2]:
        if pg < 1 or pg in tried:
            continue
        q = {"mod": "viewthread", "tid": tid,
             "extra": "page=%d" % (pg - 1), "page": pg}
        if authorid:
            q["authorid"] = authorid
        rr = cl.get("/forum.php", params=q)
        sp = soup_of(rr)
        _t, posts = parse_thread_page(sp, pg, renumber=not authorid)
        tried[pg] = (posts, thread_pages(sp))
        for i, x in enumerate(posts):
            if _floor_int(x["floor"]) == target:
                return pg, i, posts, thread_pages(sp)
    # 没精确命中：返回最接近的一页
    best = None
    for pg, (posts, tp) in tried.items():
        for i, x in enumerate(posts):
            n = _floor_int(x["floor"])
            if n is not None and best is None:
                best = (pg, i, posts, tp)
            elif n is not None and abs(n - target) < abs(
                    (_floor_int(best[2][best[1]]["floor"]) or 0) - target):
                best = (pg, i, posts, tp)
    return best if best else (1, 0, [], 1)


def thread_pages(sp):
    """总页数：优先取分页控件里最大的 page=N 链接。"""
    best = 0
    scope = sp.select_one("#pgt") or sp.select_one("div.pg") or sp
    for a in scope.select("a[href]"):
        m = re.search(r"[?&]page=(\d+)", a.get("href") or "")
        if m:
            best = max(best, int(m.group(1)))
    if best:
        return best
    m = re.search(r"共\s*(\d+)\s*页", text_of(scope) or "")
    if m:
        return int(m.group(1))
    return 1


def thread_info(sp):
    """从首屏拿 (总楼数, 总页数)。回复数在帖子标题栏里，+1 即总楼数。"""
    floors, pages = 0, thread_pages(sp)
    txt = text_of(sp) or ""
    m = re.search(r"回复[:：]\s*(\d+)", txt)
    if m:
        floors = int(m.group(1)) + 1
    return floors, pages


def parse_thread_page(sp, page_no=1, renumber=True):
    """解析帖子详情页：标题 + 各楼内容。

    Discuz 的楼号是 JS 渲染的，HTML 里没有 postnumber 元素，
    所以按 DOM 中楼块的顺序推算：第 N 页每页 10 楼。
    """
    subj = sp.select_one("#thread_subject")
    title = text_of(subj) if subj else ""
    posts = []
    for div in sp.select('div[id^="post_"]'):
        pid_m = re.match(r"post_(\d+)", div.get("id", ""))
        pid = pid_m.group(1) if pid_m else ""
        author, uid = "", ""
        au = div.select_one("div.authi a.xw1") or div.select_one("td.pls .authi a")
        if au:
            author = text_of(au)
            um = re.search(r"[?&]uid=(\d+)", au.get("href", "") or "")
            if um:
                uid = um.group(1)
        floor = ""
        fl = (div.select_one('a[id^="postnum"]') or
              div.select_one("div.pi strong a") or div.select_one("td.pls strong a"))
        if fl:
            floor = re.sub(r"\s+", " ", text_of(fl)).strip()
            # 可能带 "#"、"楼" 等后缀，只留数字或文字标记
            floor = re.sub(r"[#\u25a0\s]+$", "", floor).strip()
        ptime = ""
        for em in div.select("div.authi em"):
            tt = text_of(em)
            if "发表于" in tt or re.search(r"\d{4}-\d{1,2}", tt):
                ptime = re.sub(r"发表于|发表于\s*", "", tt).strip()
                if ptime:
                    break
        body = div.select_one("td.t_f")
        content = text_of(body) if body else ""
        if not author and not content:
            continue
        posts.append(dict(pid=pid, author=author, uid=uid, floor=floor,
                          time=ptime, content=content))
    # 补楼号：楼层块按出现顺序排列，每页 10 楼
    # （authorid 过滤视图由站点重新编号，此时不猜数字，保留站点标记）
    for i, p in enumerate(posts if renumber else []):
        num = (page_no - 1) * 10 + i + 1
        mark = p["floor"]
        if mark and re.fullmatch(r"\d+", mark):
            p["floor"] = "%d楼" % num
        elif mark:
            # "楼主" / "推荐" 这类标记保留，并补上数字楼号
            p["floor"] = "%s · %d楼" % (mark, num)
        else:
            p["floor"] = "%d楼" % num
    return title, posts


def cmd_thread(args, cl):
    """查看帖子（含各楼回复）。"""
    st = load_state(args.home)
    sel_tid, sel_page, sel_title = get_sel_thread(st)
    tid_from_sel = not args.tid
    if args.tid:
        tid = None
        if is_index_like(args.tid):
            kind, got, label = interpret_index(st, args.tid)
            if got and kind != "boards":
                tid = str(got)
                _ui.out(_ui.c("序号 %s → %s：%s" %
                              (args.tid, "搜索结果" if kind == "search" else "帖子列表",
                               (label or "")[:40]), "grey"))
        if tid is None:
            tid = normalize_tid(args.tid)
    elif sel_tid:
        tid = sel_tid
    else:
        die("还没有选择帖子。先 select <TID 或网址>，或直接 thread <TID>")

    # 页码：--next/--prev 相对上次，--page 绝对，粘网址取 URL 里的页码，
    # 都缺省才沿用记忆
    url_hint = url_page_hint(args.tid) if args.tid else None
    if getattr(args, "next_page", False):
        page = int(sel_page) + 1 if sel_tid == tid else 2
    elif getattr(args, "prev_page", False):
        page = max(1, int(sel_page) - 1) if sel_tid == tid else 1
    elif args.page and str(args.page).lower() == "last":
        page = -1            # 先抓第 1 页拿总页数，下面再折算
    elif args.page:
        page = int(args.page)
    elif url_hint:
        page = url_hint
    elif sel_tid == tid:
        page = int(sel_page)
    else:
        page = 1

    # 先取第 1 页：标题 / 楼主 uid / 总楼数 / 总页数 都在这一屏里
    r = cl.get("/forum.php", params={"mod": "viewthread", "tid": tid})
    sp = sp1 = soup_of(r)
    title, posts = parse_thread_page(sp, 1)
    total_floors, total_pages = thread_info(sp)

    # --page last / --floor N：用首屏信息直接算出目标页，不用试错
    want_last = str(getattr(args, "page", "") or "").lower() == "last"
    if want_last and total_pages > 1:
        page = total_pages
    if getattr(args, "floor", None) and total_floors > 1:
        per = max(1, -(-total_floors // max(1, total_pages)))   # 每页楼数
        page = max(1, min(total_pages or 1, (args.floor - 1) // per + 1))

    if total_pages and page > total_pages:
        info("该帖只有 %d 页，已定位到最后一页" % total_pages
             if page - total_pages > 1 or getattr(args, "next_page", False)
             else "已是最后一页（共 %d 页）" % total_pages)
        page = total_pages

    if page > 1:
        r = cl.get("/forum.php", params={
            "mod": "viewthread", "tid": tid,
            "extra": "page=%d" % (page - 1), "page": page})
        sp = soup_of(r)
        title, posts = parse_thread_page(sp, page)
        # 第 2 页起分页控件只显示"上一页"，总页数会退化，取两次的较大值
        _tf2, _tp2 = thread_info(sp)
        total_floors = max(total_floors, _tf2)
        total_pages = max(total_pages, _tp2)
    fid, board = "", ""
    pt = sp1.select_one("#pt")
    for a in (pt.select("a") if pt else []):
        mm = re.search(r"forum-(\d+)-1\.html", a.get("href", "") or "")
        if mm:
            fid, board = mm.group(1), text_of(a)

    # 解析筛选目标：--op 取楼主 uid，--author 按昵称找 uid
    want_name, want_uid = None, None
    if getattr(args, "only_op", False):
        if posts:
            want_name, want_uid = posts[0]["author"], posts[0]["uid"]
        if not want_uid and posts:
            # 末页等情况下首页没有楼主，回头问第 1 页
            r0 = cl.get("/forum.php", params={"mod": "viewthread", "tid": tid})
            _t0, p0 = parse_thread_page(soup_of(r0), 1)
            if p0:
                want_name, want_uid = p0[0]["author"], p0[0]["uid"]
    elif getattr(args, "author", None):
        want_name = args.author.strip()
        low = want_name.lower()
        for x in posts:
            if (x["author"] or "").lower() == low:
                want_uid = x["uid"]
                break
        if not want_uid:
            # 当前页没这人，去首页找
            r0 = cl.get("/forum.php", params={"mod": "viewthread", "tid": tid})
            for x in parse_thread_page(soup_of(r0), 1)[1]:
                if (x["author"] or "").lower() == low:
                    want_uid = x["uid"]
                    break

    filtered = bool(want_name)
    if filtered and not want_uid:
        info("没找到作者「%s」的 uid（可能不在此帖，或昵称写错）" % want_name)
        return 1

    # 命中筛选：改走服务端 authorid 过滤视图（站点自带"只看该作者"）
    if filtered:
        fp = {"mod": "viewthread", "tid": tid, "authorid": want_uid}
        if page > 1:
            fp["extra"] = "page=%d" % (page - 1)
            fp["page"] = page
        r = cl.get("/forum.php", params=fp)
        sp = soup_of(r)
        title, posts = parse_thread_page(sp, page, renumber=False)
        # 过滤视图的页数与原帖不同，这里单独取（退化时保留原值）
        total_pages = max(1, thread_pages(sp))

    if filtered and page > total_pages and total_pages:
        info("%s 在该帖只有 %d 页，已回到第 1 页" % (want_name, total_pages))

    # --all：自动把全部分页抓齐（筛选时抓筛选结果的所有页）
    if getattr(args, "scan_all", False):
        cap = min(total_pages, getattr(args, "max_pages", 50))
        collected = []

        def _collect(pg, ps):
            seen = {x.get("pid") or (x["author"], x["time"], x["content"][:40])
                    for x in collected}
            for x in ps:
                k = x.get("pid") or (x["author"], x["time"], x["content"][:40])
                if k not in seen:
                    collected.append(x)
                    seen.add(k)

        _collect(page, posts)
        for pg in range(1, cap + 1):
            if pg == page:
                continue
            info("抓第 %d/%d 页…" % (pg, cap))
            q = {"mod": "viewthread", "tid": tid,
                 "extra": "page=%d" % max(1, pg - 1), "page": pg}
            if filtered:
                q["authorid"] = want_uid
            rr = cl.get("/forum.php", params=q)
            _collect(pg, parse_thread_page(soup_of(rr), pg,
                                            renumber=not filtered)[1])
        if filtered:
            posts = collected
        else:
            # 跨页按 DOM 顺序重编楼号，避免各页公式拼接出现重复 11 楼
            posts = collected
            for i, x in enumerate(posts):
                x["floor"] = "楼主" if i == 0 else "%d楼" % (i + 1)
        if cap < total_pages:
            info("已达 --max-pages %d 上限（共 %d 页），其余未抓" % (cap, total_pages))

    # --floor：定位到该楼所在页，并从该楼开始显示
    if getattr(args, "floor", None) and posts:
        fld = args.floor
        idx2 = 0
        for i, x in enumerate(posts):
            if _floor_int(x["floor"]) == fld:
                idx2 = i
                break
        if idx2 or _floor_int(posts[0]["floor"]) == fld:
            info("跳到 %d 楼（第 %d 页第 %d 条，本页共 %d 条）"
                 % (fld, page, idx2 + 1, len(posts)))
            posts = posts[idx2:]
        else:
            info("第 %d 页没有 %d 楼（共 %d 页 %d 楼）"
                 % (page, fld, total_pages, total_floors))

    if getattr(args, "json", False):
        _ui.json_out({"tid": tid, "title": title, "filter": want_name,
                      "posts": posts})
        return 0

    _bits = ["第 %d/%d 页" % (page, total_pages or 1)]
    if total_floors:
        _bits.append("共 %d 楼" % total_floors)
    if tid_from_sel:
        _bits.append("来自 select")
    _ui.post_title(title, tid=tid, fid=fid or "?", note=" · ".join(_bits))
    if filtered:
        _ui.out(_ui.c("筛选：只看 %s（服务端 authorid 过滤 · 共 %d 楼%s）" %
                      (want_name, len(posts),
                       "" if getattr(args, "scan_all", False)
                       else " · 本页"), "grey"))
    if not posts:
        m = re.search(r'id="messagetext"[^>]*>(.*?)</', r.text, re.S)
        reason = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""
        if filtered:
            info("本页没有 %s 的楼层（加 --all 抓全部分页）" % want_name)
            return 0
        info("未解析到楼层内容（站点提示：%s）" % reason[:60] if reason
             else "未解析到楼层内容（帖子可能不存在、已删除，或需要登录）")
        return 1

    if getattr(args, "pager", False):
        import _pager

        def _fetch(pg):
            q = {"mod": "viewthread", "tid": tid,
                 "extra": "page=%d" % max(1, pg - 1), "page": pg}
            if filtered:
                q["authorid"] = want_uid
            rr = cl.get("/forum.php", params=q)
            return _pager.build_lines(
                parse_thread_page(soup_of(rr), pg, renumber=not filtered)[1],
                filtered)

        _pager.Pager(_pager.build_lines(posts, filtered), fetch=_fetch,
                     page=page, total_pages=total_pages,
                     title=title or ("TID %s" % tid)).run()
        return 0

    for i, p in enumerate(posts, 1):
        label = (p["floor"] or "").strip()
        if not label:
            label = "第 %d 条" % ((page - 1) * 10 + i) if not filtered else "第 %d 条" % i
        _ui.post_floor(label, p["author"] or "匿名", p["time"] or "")
        _ui.body(p["content"])
    # 选定帖子时，板块上下文跟着切到它所属板块，避免 board/thread 打架
    if getattr(args, "keep", False):
        pass
    elif fid:
        cur_fid, _cur_name = get_sel_board(st)
        if str(cur_fid or "") != str(fid):
            st["board"] = {"fid": int(fid), "name": board or str(fid)}
    if not getattr(args, "keep", False):
        set_sel_thread(args.home, st, tid, title, page)
    _ui.out()
    tail = "共 %d 楼" % len(posts)
    if filtered:
        tail = "%s 共 %d 楼" % (want_name, len(posts))
    elif getattr(args, "scan_all", False):
        tail += "（全帖 %d 页）" % min(total_pages, getattr(args, "max_pages", 50))
    elif page > 1:
        tail += "（第 %d 页）" % page
    _ui.out(_ui.c(tail, "grey"))
    equiv("thread", tid,
          "--page %d" % page if page > 1 else None,
          "--op" if getattr(args, "only_op", False) else None,
          "--all" if getattr(args, "scan_all", False) and total_pages > 1 else None,
          "--author %s" % args.author if getattr(args, "author", None) else None)
    _ui.out(_ui.c("  提示：--next/--prev 翻页 · --op 只看楼主", "grey"))
    return 0


def cmd_latest(args, cl):
    """新帖导读：全站最新发帖。"""
    params = {"mod": "guide", "view": "newthread"}
    if args.page and args.page > 1:
        params["page"] = args.page
    r = cl.get("/forum.php", params=params)
    sp = soup_of(r)
    rows = parse_thread_rows(sp)
    if not rows:
        info("未解析到新帖（页面结构可能变化）")
        return 1
    if getattr(args, "grep", None):
        kw = args.grep.lower()
        rows = [x for x in rows
                if kw in x["title"].lower() or kw in x["author"].lower()]
    if getattr(args, "json", False):
        _ui.json_out(rows)
        return 0
    _ui.heading("全站新帖导读")
    out_rows = []
    for x in rows:
        mark = "置顶 " if x["pinned"] else ""
        out_rows.append((str(x["tid"]), x["author"], x["time"], mark + x["title"]))
    _ui.table(["TID", "作者", "时间", "标题"], out_rows, aligns=["<", "<", "<", "<"])
    _ui.out()
    _ui.out(_ui.c("共 %d 条 · select #<序号> 选中 · thread #<序号> 直接读" % len(rows), "grey"))
    return 0


def _decode_bing_url(href):
    """Bing 跳转链接里藏了 base64 后的真实地址。"""
    m = re.search(r"[?&]u=a1([^&]+)", href or "")
    if not m:
        return href
    raw = m.group(1)
    raw += "=" * (-len(raw) % 4)
    try:
        import base64
        return base64.urlsafe_b64decode(raw).decode("utf-8", "ignore")
    except Exception:
        return href


def _clean_title(txt):
    """清掉搜索引擎结果标题里的域名前后缀。"""
    t = re.sub(r"[\u200b\u200c\u200d\ufeff\xa0]", " ", txt or "")
    t = re.sub(r"https?://(?:www\.)?52pojie\.cn/?\S*", "", t)
    t = re.sub(r"\s*[-|｜]\s*吾爱破解(\s*52pojie\.cn)?\s*$", "", t)
    t = re.sub(r"\s*[-|｜]\s*52pojie\.cn\s*$", "", t)
    t = re.sub(r"\s*[-|｜]\s*吾爱破解.*$", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -|")
    return t


def _search_so360(cl, keyword, page=1):
    """360 搜索（对该站帖子页有索引）。"""
    q = urllib.parse.quote("site:52pojie.cn " + keyword)
    r = cl.get("https://www.so.com/s?q=" + q, external=True,
               referer="https://www.so.com/")
    sp = soup_of(r)
    out = []
    seen = set()
    for a in sp.find_all("a", href=True):
        url = a.get("data-mdurl") or a.get("href") or ""
        m = re.search(r"52pojie\.cn/thread-(\d+)-\d+-\d+\.html", url)
        if not m:
            continue
        tid = int(m.group(1))
        if tid in seen:
            continue
        seen.add(tid)
        title = _clean_title(text_of(a))
        if not title:
            # 标题在 h3 里，取最近的 h3
            h3 = a.find_parent("h3")
            if h3:
                title = _clean_title(text_of(h3))
        out.append((tid, title, url))
    return out


def _search_bing(cl, keyword, page=1):
    """Bing 搜索（site: 限定）。"""
    q = urllib.parse.quote("site:52pojie.cn " + keyword)
    first = 1 + (page - 1) * 10
    r = cl.get("https://cn.bing.com/search?q=%s&first=%d" % (q, first),
               external=True, referer="https://cn.bing.com/")
    sp = soup_of(r)
    out = []
    seen = set()
    for a in sp.select("li.b_algo h2 a, .b_algo h2 a, h2 a"):
        href = _decode_bing_url(a.get("href", ""))
        if "52pojie.cn" not in href:
            continue
        m = re.search(r"thread-(\d+)-", href)
        if not m:
            continue
        tid = int(m.group(1))
        if tid in seen:
            continue
        seen.add(tid)
        out.append((tid, _clean_title(text_of(a)), href))
    return out


def cmd_search(args, cl):
    """搜索帖子。

    站点把站内搜索整体重定向到了 Bing，而 Bing 对 52pj 的帖子页几乎没有索引，
    所以这里改为直接查外部搜索引擎（360 优先，Bing 兜底）并解析出帖子链接。
    """
    engines = {
        "360": _search_so360,
        "bing": _search_bing,
    }
    order = [args.engine] if args.engine in engines else ["360", "bing"]
    results = []
    used = None
    for name in order:
        try:
            results = engines[name](cl, args.keyword, args.page)
        except Exception as e:
            info("引擎 %s 出错：%s" % (name, e))
            continue
        if results:
            used = name
            break
        info("引擎 %s 无结果，尝试下一个…" % name)
    if not results:
        info("没有搜到。")
        info("提示：站内搜索已被站点重定向到 Bing（索引很稀），"
             "更实用的是在版块列表里本地过滤：")
        info("  pojie.bat threads --fid 32 --grep %s" % args.keyword)
        info("  pojie.bat latest --grep %s" % args.keyword)
        return 1
    results = sorted(results, key=lambda x: -x[0])
    if getattr(args, "json", False) or _ui.json_mode():
        _ui.json_out([{"tid": a, "title": b, "url": c} for a, b, c in results])
        return 0
    _ui.heading("搜索：%s" % args.keyword,
                "引擎 %s · 命中 %d 条" % (used, len(results)))
    st = load_state(args.home)
    save_list(args.home, st, "search",
              [{"id": a, "label": b} for a, b, _ in results])
    _ui.table(["序号", "TID", "标题"],
              [("#%d" % (i + 1), str(a), b or "(无标题)") for i, (a, b, _) in enumerate(results)],
              aligns=[">", "<", "<"])
    if getattr(args, "verbose", False):
        _ui.out()
        for a, _b, href in results:
            _ui.out(_ui.c("  %s  %s" % (a, href), "grey"))
    _ui.out()
    _ui.out(_ui.c("select #<序号> 选中 · thread #<序号> 直接读", "grey"))
    return 0


# --------------------------------------------------------------------------- #
# 登录
# --------------------------------------------------------------------------- #
def _windows_registry_env(name):
    """从 Windows 注册表的用户/系统环境变量里取值（进程环境可能是旧的）。"""
    try:
        import winreg
    except ImportError:
        return None
    for scope in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        try:
            with winreg.OpenKey(getattr(winreg, scope), "Environment") as k:
                v, _ = winreg.QueryValueEx(k, name)
                if v:
                    return v
        except OSError:
            continue
    return None


def get_credential(env_name):
    """按 进程环境 -> Windows 注册表 的顺序取账号密码。"""
    val = os.environ.get(env_name)
    if val:
        return val
    return _windows_registry_env(env_name)


def parse_login_page(cl):
    """返回 (resp, formhash, idhash)。"""
    r = cl.get("/member.php", params={"mod": "logging", "action": "login"})
    sp = soup_of(r)
    fh = None
    m = re.search(r'name="formhash"\s+value="([0-9a-fA-F]+)"', r.text)
    if m:
        fh = m.group(1)
    idhash = None
    h = sp.select_one('input[name="seccodehash"]')
    if h:
        idhash = h.get("value")
    if not idhash:
        # 静态 HTML 里没有 seccodehash，它由 JS 的 updateseccode() 注入
        m = re.search(r"updateseccode\('([\w]+)'", r.text)
        if m:
            idhash = m.group(1)
    return r, fh, idhash


def turnstile_sitekey(cl, idhash):
    """调用 cdc_recaptcha 插件接口，获取 Turnstile sitekey。"""
    r = cl.post("/plugin.php?id=cdc_recaptcha:api&inajax=1",
                data={"status": 0, "idhash": idhash},
                headers={"X-Requested-With": "XMLHttpRequest"})
    txt = (r.text or "").strip()
    if not txt:
        return None
    try:
        j = json.loads(txt)
    except Exception:
        m = re.search(r'"sitekey"\s*:\s*"([^"]+)"', txt)
        return {"sitekey": m.group(1)} if m else None
    if isinstance(j, list) and len(j) >= 3:
        idx = j[2]
        cfg = (j[0] or {})[idx] if isinstance(j[0], list) else {}
        sitekey = cfg[0] if isinstance(cfg, (list, tuple)) and cfg else None
        if not sitekey and len(j) > 3 and isinstance(j[3], str):
            sitekey = j[3]
        return {"sitekey": sitekey, "raw": j}
    if isinstance(j, dict):
        return {"sitekey": j.get("sitekey"), "raw": j}
    return None


def submit_turnstile_token(cl, idhash, token):
    """把 Turnstile token 回传服务端校验，绑定到当前 session。"""
    return cl.post("/plugin.php?id=cdc_recaptcha:api",
                   data={"status": 1, "idhash": idhash, "token": token},
                   headers={"X-Requested-With": "XMLHttpRequest"})


def login_form(cl, username, password, seccode_verify=None, answer=""):
    """Discuz 表单登录，返回 (成功?, 消息)。"""
    r, fh, idhash = parse_login_page(cl)
    if not fh:
        return False, "未能取得 formhash"
    mh = re.search(r"loginhash=(\w+)", r.text)
    action = ("member.php?mod=logging&action=login&loginsubmit=yes&loginhash=" +
              (mh.group(1) if mh else "x"))
    data = {
        "username": username,
        "password": password,
        "formhash": fh,
        "referer": BASE + "/",
        "cookietime": "7776000",
        "loginfield": "username",
        "quickforward": "yes",
    }
    if idhash:
        data["seccodehash"] = idhash
        data["seccodeverify"] = idhash
    if seccode_verify:
        data["seccode"] = seccode_verify
    if answer:
        data["answer"] = answer
    r2 = cl.post("/" + action, data=data,
                 headers={"Referer": BASE + "/member.php?mod=logging&action=login"})
    msg = cl.page_message(r2)
    ok = any((n == "auth" or n.endswith("_auth")) and v
             for n, v, _d, _p in _iter_cookies(cl.s.cookies))
    if not ok and ("欢迎您" in r2.text or "登出" in r2.text):
        ok = True
    return ok, (msg or ("登录成功" if ok else "登录失败（未返回明确提示）"))


def _solve_turnstile(drv, deadline):
    """尝试自动完成 Cloudflare Turnstile：点开验证框、必要时点 iframe 内复选框。"""
    from selenium.webdriver.common.by import By
    # 先点主文档上的“点击验证”
    for sel in ("[id^=grbg] .grcheck", ".grcheck", "[id^=grcontainer] button"):
        try:
            drv.find_element(By.CSS_SELECTOR, sel).click()
            info("已点击验证按钮，等待人机验证…")
            break
        except Exception:
            continue
    while time.time() < deadline:
        try:
            span = drv.find_element(By.CSS_SELECTOR, "[id^=checkseccodeverify]")
            if span.is_displayed():
                return True
        except Exception:
            pass
        frames = drv.find_elements(
            By.CSS_SELECTOR, 'iframe[src*="challenges.cloudflare.com"]')
        if frames:
            try:
                drv.switch_to.default_content()
                drv.switch_to.frame(frames[0])
                for sel in ("input[type=checkbox]", "label", ".cb-lb",
                            "#challenge-stage", "body"):
                    try:
                        el = drv.find_element(By.CSS_SELECTOR, sel)
                        drv.execute_script("arguments[0].click();", el)
                        break
                    except Exception:
                        continue
            except Exception:
                pass
            finally:
                try:
                    drv.switch_to.default_content()
                except Exception:
                    pass
        time.sleep(1.5)
    return False


def login_browser(username, password, timeout=180):
    """用本机 Chrome 完成登录（Turnstile 需人工点一下），返回 cookie 列表。"""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
    except ImportError:
        die("需要 selenium：pip install selenium"
            "（或改用 --cookie 导入浏览器 Cookie）")
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".selenium")
    try:
        os.makedirs(cache, exist_ok=True)
        os.environ.setdefault("SE_CACHE", cache)
    except Exception:
        pass
    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    info("正在打开 Chrome 登录页…请在弹出的窗口里点一下‘点击验证’完成人机验证。")
    drv = webdriver.Chrome(options=opts)
    try:
        drv.get(BASE + "/member.php?mod=logging&action=login")
        time.sleep(2)
        u = drv.find_element(By.NAME, "username")
        u.clear()
        u.send_keys(username)
        p = drv.find_element(By.NAME, "password")
        p.clear()
        p.send_keys(password)
        deadline = time.time() + timeout
        verified = _solve_turnstile(drv, deadline)
        if not verified:
            info("人机验证未自动通过，仍尝试提交（可稍后在浏览器里手动点一下）。")
        try:
            drv.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        except Exception:
            drv.find_element(By.NAME, "loginsubmit").click()
        time.sleep(4)
        cookies = drv.get_cookies()
        html = drv.page_source
        logged = any((c["name"] == "auth" or c["name"].endswith("_auth")) and
                     c.get("value") for c in cookies)
        if not logged and re.search(r"欢迎您|登出", html):
            logged = True
        if not logged:
            return None, "浏览器登录未成功（验证码/账号密码可能有误）"
        return cookies, "登录成功"
    finally:
        try:
            drv.quit()
        except Exception:
            pass


def cmd_login(args, cl):
    """登录账号。"""
    if args.cookie:
        n = import_cookie_text(cl, args.cookie)
        if not n:
            die("Cookie 解析失败，请确认是整行「k=v; k2=v2」格式")
        who = cl.logged_in()
        info("已导入 %d 条 Cookie" % n + ("，当前用户: %s" % who if who else ""))
        return 0 if who else 1

    username = (args.username or get_credential("POJIE_52_ACCOUNT") or
                input("账号: ").strip())
    password = (args.password or get_credential("POJIE_52_PASSWD") or
                getpass.getpass("密码: "))

    if args.browser:
        cookies, msg = login_browser(username, password)
        if not cookies:
            die(msg)
        for c in cookies:
            cl.s.cookies.set(c["name"], c["value"], domain=c.get("domain"),
                             path=c.get("path", "/"))
        cl.save_cookies()
        info(msg)
        return 0

    # 表单登录：需要先通过 Turnstile
    r, fh, idhash = parse_login_page(cl)
    info("formhash=%s idhash=%s" % (fh, idhash))
    if idhash:
        cfg = turnstile_sitekey(cl, idhash)
        info("Turnstile sitekey: %s" % (cfg or {}).get("sitekey"))
        token = args.token
        if not token:
            info("站点启用了 Cloudflare Turnstile 人机验证，任选其一：")
            info("  1) 52pj login --browser --username %s  （自动开 Chrome，点一下验证）" % username)
            info("  2) 在浏览器登录论坛后：52pj login --cookie \"<Cookie 串>\"")
            info("  3) 自备 Turnstile token：52pj login --token <token>")
            return 2
        submit_turnstile_token(cl, idhash, token)
        info("Turnstile token 已提交。")
    ok, msg = login_form(cl, username, password, answer=args.answer)
    info(msg)
    if ok:
        cl.save_cookies()
    return 0 if ok else 1


def cmd_whoami(args, cl):
    """查看当前登录状态。"""
    who = cl.logged_in()
    if getattr(args, "json", False) or _ui.json_mode():
        _ui.json_out({"logged_in": bool(who), "user": who or None,
                      "cookie_file": cl.cookie_file})
        return 0 if who else 1
    if who:
        _ui.out(_ui.c("✓ 已登录", "green", "bold") + "  " + who)
        _ui.out(_ui.c("  cookie: %s" % cl.cookie_file, "grey"))
    else:
        _ui.out(_ui.c("✗ 未登录", "yellow", "bold"))
        _ui.out(_ui.c("  浏览帖子不需要登录；auth 可登录以查看私密内容", "grey"))
    return 0 if who else 1


def cmd_logout(args, cl):
    """清除登录态（只删 cookie，选择与缓存保留）。"""
    n = _store.clear_cookies(cl.db)
    print("已清除登录状态（%d 条 cookie）" % n if n else "本来就没有登录状态")
    return 0




# --------------------------------------------------------------------------- #
# 浏览器登录（auth）：打开本机浏览器，人工登录，工具自动回收 cookie
# --------------------------------------------------------------------------- #
def import_cookie_text(cl, txt):
    """把「a=1; b=2」整行 Cookie 灌进会话并落库。"""
    if txt.lower().startswith("cookie:"):
        txt = txt.split(":", 1)[1]
    host = urllib.parse.urlparse(BASE).hostname
    n = 0
    for part in txt.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        for dom in ("." + host, host):
            try:
                cl.s.cookies.set(k, v, domain=dom, path="/")
            except Exception:
                pass
        n += 1
    if n:
        cl.save_cookies()
    return n


def paste_cookie_login(cl, prompt_hint=True):
    """没有浏览器可用时的登录方式：让用户从浏览器 F12 复制 Cookie 过来。"""
    if prompt_hint:
        info("没有可用浏览器，改用粘贴 Cookie（任何浏览器都行）：")
        info("  1) 用任意浏览器打开 %s 并登录" % BASE)
        info("  2) F12 → 网络(Network) → 刷新页面 → 点任一请求")
        info("  3) 请求头里找到 Cookie，整行复制（形如 htVC_2132_auth=...; ...）")
        info("  4) 粘到下面回车（粘贴时看不到回显是正常的，粘完直接回车）")
    try:
        txt = input("Cookie: ").strip()
    except (EOFError, KeyboardInterrupt):
        txt = ""
    if not txt:
        die("没有收到 Cookie。也可以直接：52pj login --cookie \"<整行 Cookie>\"")
    n = import_cookie_text(cl, txt)
    if not n:
        die("这串 Cookie 解析不出任何键值对，请确认复制的是 Cookie 整行")
    who = cl.logged_in()
    if who:
        info("已保存 %d 条 cookie，登录成功：%s" % (n, who))
        return 0
    info("已保存 %d 条 cookie，但没识别到登录态——请确认复制时已登录，且包含 *_auth。" % n)
    return 1


def cmd_auth(args, cl):
    """打开本机浏览器，人工登录后自动回收 cookie。"""
    try:
        import selenium  # noqa: F401
    except ImportError:
        die("需要 selenium：pip install selenium")

    browsers = _browser_local.find_browsers()
    if getattr(args, "paste", False):
        return paste_cookie_login(cl)
    info("检测方式：注册表 App Paths → 常见安装目录 → PATH，结果：")
    for k, p in browsers:
        info("  [%s] %s" % (k, p))
    if not browsers:
        info("未检测到 Chrome / Edge / Firefox / Brave。")
        return paste_cookie_login(cl)

    chosen = None
    if args.browser:
        for k, p in browsers:
            if k == args.browser:
                chosen = (k, p)
                break
        if not chosen:
            die("未找到指定浏览器：%s" % args.browser)
    else:
        prefer = ["chrome", "edge", "brave", "firefox"]
        for want in prefer:
            for k, p in browsers:
                if k == want:
                    chosen = (k, p)
                    break
            if chosen:
                break
    key, path = chosen
    info("使用浏览器：%s (%s)" % (key, path))

    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".selenium")
    try:
        os.makedirs(cache, exist_ok=True)
        os.environ.setdefault("SE_CACHE", cache)
    except Exception:
        pass
    # 与传输层共用同一 profile，登录态才能被 -b 复用
    profile = browser_profile_dir(cl.home)
    try:
        os.makedirs(profile, exist_ok=True)
    except Exception:
        profile = None

    info("正在打开浏览器登录页，请在窗口里自行完成登录（含人机验证）…")
    drv = _browser_local.make_driver(key, path, profile,
                                    proxy=args.proxy)
    try:
        drv.get(BASE + "/member.php?mod=logging&action=login")
        deadline = time.time() + args.timeout
        auth = None
        while time.time() < deadline:
            time.sleep(2)
            try:
                cookies = drv.get_cookies()
            except Exception:
                continue
            for c in cookies:
                if (c["name"] == "auth" or c["name"].endswith("_auth")) and \
                        c.get("value"):
                    auth = c
                    break
            if auth:
                break
        if not auth:
            die("等待超时（%d 秒）未检测到登录态。可加大 --timeout，"
                "或改用 52pj login --cookie \"<Cookie 串>\" 导入。" % args.timeout)
        for c in drv.get_cookies():
            cl.s.cookies.set(c["name"], c["value"], domain=c.get("domain"),
                             path=c.get("path", "/"))
        try:
            fp = drv.execute_script(
                "var u=navigator.userAgentData;return {ua:navigator.userAgent,"
                "brands:u?u.brands:null,platform:u?u.platform:null,"
                "mobile:u?u.mobile:false,lang:navigator.language};")
        except Exception:
            fp = {}
        cl.save_cookies(ua=fp.get("ua"), fingerprint=fp)
        info("已获取登录态并保存到：%s" % cl.cookie_file)
        if not args.keep_open:
            pass
    finally:
        if not args.keep_open:
            try:
                drv.quit()
            except Exception:
                pass
        else:
            info("浏览器保持打开（--keep-open），按 Ctrl+C 结束。")
    who = cl.logged_in()
    print("登录成功" + ("：%s" % who if who else ""))
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def check_deps(need_bs4=True):
    """检查运行依赖，缺了就提示用 setup 安装。"""
    missing = []
    if need_bs4 and BeautifulSoup is None:
        missing.append("beautifulsoup4")
    if missing:
        die("缺少依赖：%s\n请先运行：pojie.bat setup   "
            "（或手动执行：python -m pip install %s）"
            % ("、".join(missing), " ".join(missing)))


def cmd_setup(args, cl):
    """自动安装依赖：python -m pip install curl_cffi beautifulsoup4"""
    import subprocess
    pkgs = ["curl_cffi", "beautifulsoup4"]
    if getattr(args, "with_selenium", False):
        pkgs.append("selenium")
    mirrors = [("国内镜像", ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]),
               ("官方源", [])]
    for label, extra in mirrors:
        info("尝试从%s安装：%s" % (label, " ".join(pkgs)))
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
               "-q"] + pkgs + extra
        try:
            rc = subprocess.call(cmd)
        except Exception as e:
            info("调用 pip 失败：%s" % e)
            continue
        if rc == 0:
            print("依赖安装完成（%s）：%s" % (label, " ".join(pkgs)))
            return 0
        info("%s 安装失败（返回码 %d）" % (label, rc))
    die("依赖安装失败。请手动执行：\n  python -m pip install curl_cffi "
        "beautifulsoup4")


EXAMPLES = """交互式浏览（选定一次，之后命令都作用于它）：
  52pj select 病毒分析              选定板块（也可写 fid：select 32）
  52pj threads                     直接列该板块的帖子
  52pj select 2137132              选定帖子（也可粘整条网址）
  52pj thread                      直接看这个帖子
  52pj thread --pager              交互式阅读：方向键/PgUp·PgDn 翻阅，读到底自动加载下一页
  52pj thread --next / --prev      翻页（会记住页码）
  52pj status                      看当前选中了两个什么
  52pj select --clear              清除选择

常用例子：
  52pj forums                      列出所有版块
  52pj threads --fid 32            看「病毒分析区」的帖子
  52pj threads -f 水漫金山 --grep 求助   板块名可以直接写，还能过滤
  52pj latest --grep 勒索          全站新帖里找含"勒索"的
  52pj thread 2137132              看帖子正文和各楼回复
  52pj thread https://www.52pojie.cn/thread-2137132-1-1.html   直接粘网址
  52pj threads -f 32 --no-pin      不看置顶，只看真实新帖
  52pj thread 2137132 --op --all   只看楼主（扫全部页）
  52pj search 银狐                 搜索（走 360/Bing）
  52pj auth                        打开浏览器登录，自动收回 cookie
  52pj whoami                      看登录状态

全局开关（放命令前后都行）：
  --json         输出 JSON，便于脚本处理
  --color        开启颜色（默认关闭）
  --width 80     指定输出宽度
  --delay-min/--delay-max  请求间隔区间（默认 0.7~1.3 秒随机）
"""


def normalize_tid(s):
    """从 tid、thread-123-1-1.html 或整条网址里抽出数字 tid。"""
    s = str(s or "").strip()
    if s.isdigit():
        return s
    m = re.search(r"thread-(\d+)", s) or re.search(r"(?:^|[?&])(?:tid|ptid)=(\d+)", s)
    if m:
        return m.group(1)
    digits = re.sub(r"\D", "", s)
    return digits or s


def url_page_hint(s):
    """从 thread-123-4-1.html 里抽出页码（4）；不是这种形式则返回 None。

    Discuz 的 thread-<tid>-<page>-<x> 里第二个数字是页码。
    """
    m = re.search(r"thread-\d+-(\d+)-", str(s or ""))
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if n >= 1 else None


def build_parser():
    p = argparse.ArgumentParser(
        prog="52pj", description="52pojie.cn（吾爱破解）命令行阅读器",
        epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", default=DEFAULT_HOME, help="配置目录（默认 %%USERPROFILE%%/.52pj）")
    p.add_argument("-b", "--browser", action="store_true",
                   help="借道 App 内已登录的 WebView 发请求（默认本地直连）")
    p.add_argument("--delay", type=float, default=None,
                   help="请求间隔基准秒（默认在 %.1f-%.1f 秒间随机取值）"
                        % (DELAY_MIN, DELAY_MAX))
    p.add_argument("--delay-min", type=float, default=DELAY_MIN,
                   help="随机间隔下界（默认 %.1f）" % DELAY_MIN)
    p.add_argument("--delay-max", type=float, default=DELAY_MAX,
                   help="随机间隔上界（默认 %.1f）" % DELAY_MAX)
    p.add_argument("--cookie-file", default=None, help="Cookie 文件路径")
    p.add_argument("--json", action="store_true", help="输出 JSON（便于脚本处理）")
    p.add_argument("--color", action="store_true",
                   help="开启彩色输出（默认关闭，也可设 POJIE_COLOR=1）")
    p.add_argument("--no-color", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--width", type=int, default=None, help="输出宽度（默认取终端宽度）")
    sub = p.add_subparsers(dest="cmd", metavar="<命令>")
    # 下面统一给每个子命令也挂上 -b/--browser（放在子命令后也能用）

    s = sub.add_parser("setup", help="安装/检查依赖包")
    s.add_argument("--with-selenium", action="store_true",
                   help="一并安装 selenium（本地浏览器传输层需要）")

    s = sub.add_parser("forums", help="列出板块")
    s.add_argument("--grep", default=None, help="按名称过滤板块")
    s.add_argument("--refresh", action="store_true",
                   help="强制刷新板块缓存（默认缓存一天）")

    s = sub.add_parser("select", help="选择当前板块/帖子（之后命令默认作用于它）")
    s.add_argument("target", nargs="?", default=None,
                   help="板块 fid/名称，或帖子 TID/网址；不写则显示当前选择")
    s.add_argument("--board", dest="board_only", action="store_true",
                   help="强制按板块解析（即使看起来像 tid）")
    s.add_argument("--thread", dest="thread_only", action="store_true",
                   help="强制按帖子解析")
    s.add_argument("--clear", action="store_true", help="清除选择")
    s.add_argument("--board-only", dest="clear_board", action="store_true",
                   help="配合 --clear：只清板块")
    s.add_argument("--thread-only", dest="clear_thread", action="store_true",
                   help="配合 --clear：只清帖子")

    s = sub.add_parser("status", help="查看当前选择与登录状态")

    s = sub.add_parser("threads", help="列出某板块的帖子")
    s.add_argument("--fid", "-f", default=None,
                   help="板块 fid 或名称；省略则用 select 选中的板块")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--typeid", default=None, help="只看某个主题分类")
    s.add_argument("--grep", default=None, help="按标题/作者本地过滤关键字")
    s.add_argument("--no-pin", action="store_true", help="不显示置顶帖")
    s.add_argument("--pin-only", action="store_true", help="只看置顶帖")
    s.add_argument("--keep", action="store_true",
                   help="不改动 select 的选择（默认会把本次板块记为当前选择）")

    s = sub.add_parser("latest", help="全站新帖导读")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--grep", default=None, help="按标题/作者本地过滤关键字")

    s = sub.add_parser("thread", help="查看帖子（含各楼回复）")
    s.add_argument("tid", nargs="?", default=None,
                   help="帖子 tid 或整条网址；省略则用 select 选中的帖子")
    s.add_argument("--page", "-P", default=None,
                   help="第几页楼层，或写 last 表示最后一页（省略则沿用上次）")
    s.add_argument("--floor", type=int, default=None,
                   help="跳到第几楼（自动定位到所在页，并从该楼开始显示）")
    s.add_argument("--next", dest="next_page", action="store_true", help="下一页")
    s.add_argument("--prev", dest="prev_page", action="store_true", help="上一页")
    s.add_argument("--keep", action="store_true",
                   help="不改动 select 的选择（默认会把本次帖子记为当前选择）")
    s.add_argument("--pager", "-i", action="store_true",
                   help="交互式阅读：方向键/PgUp·PgDn 滚动翻阅，读到底自动加载下一页")
    s.add_argument("--op", "--only-op", dest="only_op", action="store_true",
                   help="只看楼主")
    s.add_argument("--author", default=None, help="只看某个作者（昵称）")
    s.add_argument("--all", "-a", dest="scan_all", action="store_true",
                   help="自动抓全部分页，一次读完整帖（慢，每页间隔 0.7~1.3 秒）")
    s.add_argument("--max-pages", type=int, default=50,
                   help="--all 时最多扫描多少页（默认 50）")

    s = sub.add_parser("search", help="搜索帖子（走 360 / Bing）")
    s.add_argument("--engine", default=None, choices=["360", "bing"],
                   help="指定搜索引擎（默认 360 优先，Bing 兜底）")
    s.add_argument("keyword")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--verbose", action="store_true", help="同时打印链接")

    s = sub.add_parser("login", help="登录账号")
    s.add_argument("--username", "-u", default=None)
    s.add_argument("--password", "-p", default=None)
    s.add_argument("--cookie", default=None, help="直接导入浏览器 Cookie 串")
    s.add_argument("--browser", action="store_true", help="用本机 Chrome 登录（可人工过验证码）")
    s.add_argument("--token", default=None, help="已取得的 Turnstile token")
    s.add_argument("--answer", default="", help="安全提问答案")

    s = sub.add_parser("auth", help="打开本机浏览器人工登录，自动回收 cookie")
    s.add_argument("--browser", default=None,
                   choices=["chrome", "edge", "firefox", "brave"],
                   help="指定浏览器（默认按 chrome→edge→brave→firefox 顺序自动选）")
    s.add_argument("--timeout", type=int, default=600, help="等待登录的超时秒数（默认 600）")
    s.add_argument("--proxy", default=None, help="给浏览器加的代理，如 127.0.0.1:10808")
    s.add_argument("--keep-open", action="store_true", help="登录后不关闭浏览器")
    s.add_argument("--paste", action="store_true",
                   help="不启动浏览器，直接粘贴 Cookie 登录")

    sub.add_parser("whoami", help="查看登录状态")
    sub.add_parser("logout", help="清除本地登录状态")

    for _sp in sub.choices.values():
        # login 子命令已有 --browser（人工浏览器登录），不重复挂
        if any("--browser" in a.option_strings for a in _sp._actions):
            continue
        _sp.add_argument("-b", "--browser", action="store_true",
                         default=argparse.SUPPRESS,
                         help="借道 App 内已登录的 WebView 发请求")

    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # --color 允许写在子命令后面
    _argv = [a for a in argv if a not in ("--color", "--no-color")]
    args = build_parser().parse_args(_argv)
    if "--color" in argv:
        args.color = True
    if not args.cmd:
        st = load_state(args.home)
        fid, bname = get_sel_board(st)
        tid, tpage, ttitle = get_sel_thread(st)
        _ui.out(_ui.c("52pj 命令行阅读器", "bold"))
        _ui.out()
        if fid:
            _ui.out("  板块  " + _ui.c(bname or "", "cyan") + _ui.c("  fid %s" % fid, "grey"))
        if tid:
            _ui.out("  帖子  " + _ui.c((ttitle or "")[:40], "cyan")
                    + _ui.c("  TID %s · 第 %s 页" % (tid, tpage), "grey"))
        if not fid and not tid:
            _ui.out(_ui.c("  尚未选择板块或帖子", "yellow"))
        _ui.out()
        _ui.out(_ui.c("  select 病毒分析    选定板块", "grey"))
        _ui.out(_ui.c("  threads            列出该板块帖子", "grey"))
        _ui.out(_ui.c("  select 2137132     选定帖子", "grey"))
        _ui.out(_ui.c("  thread             看正文（--next/--prev 翻页）", "grey"))
        _ui.out(_ui.c("  status / forums / latest / search / auth", "grey"))
        _ui.out()
        _ui.out(_ui.c("  完整说明：52pj --help", "grey"))
        return 0
    # 全局显示选项
    if getattr(args, "color", False):
        _ui.set_color(True)
    elif getattr(args, "no_color", False):
        _ui.set_color(False)
    if getattr(args, "width", None):
        _ui.set_width(args.width)
    _ui.set_json(getattr(args, "json", False))
    # 允许直接粘帖子网址。归一化留到 cmd_thread 里做，
    # 否则 URL 里的页码（thread-123-4-1.html）会先被丢掉。
    if args.cmd == "thread" and getattr(args, "tid", None):
        if not str(args.tid).strip().startswith("#"):
            args.tid = str(args.tid).strip()
    check_deps()
    cl = Client(home=args.home, delay=args.delay, cookie_file=args.cookie_file,
                delay_min=args.delay_min, delay_max=args.delay_max,
                transport=("browser" if getattr(args, "browser", False)
                           else "curl"))
    if args.cmd == "setup":
        return cmd_setup(args, None)
    fn = {
        "forums": cmd_forums, "threads": cmd_threads, "thread": cmd_thread,
        "latest": cmd_latest, "auth": cmd_auth,
        "search": cmd_search, "login": cmd_login, "whoami": cmd_whoami,
        "logout": cmd_logout, "select": cmd_select, "status": cmd_status,
    }[args.cmd]
    try:
        return fn(args, cl)
    except KeyboardInterrupt:
        info("已中断")
        return 130
    except Exception as e:
        die("网络错误: %s" % e)
    except SystemExit:
        raise


if __name__ == "__main__":
    sys.exit(main())
