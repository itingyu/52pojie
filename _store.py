"""pojie 的本地存储：统一用 SQLite（配置 / cookie / 选择 / 列表缓存）。

旧版是 cookies.json + state.json 两个 JSON 文件；首次运行时自动迁移，
迁移完把旧文件改名为 .bak，避免重复迁移。
"""
import json
import os
import sqlite3
import time

DB_NAME = "52pj.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS cookies (
    name     TEXT,
    domain   TEXT,
    value    TEXT,
    path     TEXT,
    expires  INTEGER,
    secure   INTEGER,
    http_only INTEGER,
    PRIMARY KEY (name, domain)
);
CREATE TABLE IF NOT EXISTS selection (
    kind  TEXT PRIMARY KEY,      -- board / thread
    id    TEXT,
    title TEXT,
    page  INTEGER DEFAULT 1,
    ts    INTEGER
);
CREATE TABLE IF NOT EXISTS lists (
    kind  TEXT,                   -- boards / threads / search
    seq   INTEGER,                -- 序号（1 起）
    id    TEXT,
    label TEXT,
    ts    INTEGER,
    PRIMARY KEY (kind, seq)
);
CREATE TABLE IF NOT EXISTS history (
    ts    INTEGER,
    cmd   TEXT
);
CREATE TABLE IF NOT EXISTS cache (
    key   TEXT PRIMARY KEY,
    value TEXT,
    ts    INTEGER
);
"""

CACHE_TTL = 86400          # 默认缓存一天


def cache_get(conn, key, ttl=CACHE_TTL):
    """取缓存；过期或不存在返回 None。"""
    row = conn.execute("SELECT value, ts FROM cache WHERE key=?",
                       (key,)).fetchone()
    if not row:
        return None
    if ttl and time.time() - int(row["ts"] or 0) > ttl:
        return None
    return row["value"]


def cache_set(conn, key, value):
    conn.execute(
        "INSERT INTO cache(key,value,ts) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
        (key, value, int(time.time())))
    conn.commit()


def cache_age(conn, key):
    row = conn.execute("SELECT ts FROM cache WHERE key=?", (key,)).fetchone()
    return int(time.time() - int(row["ts"])) if row else None


def db_path(home, custom=None):
    return custom or os.path.join(home, DB_NAME)


def connect(home, custom=None):
    path = db_path(home, custom)
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
        try:
            os.chmod(d, 0o700)      # 配置目录只给自己看
        except OSError:
            pass
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    try:
        os.chmod(path, 0o600)       # cookie 是明文，权限收紧
    except OSError:
        pass
    migrate_cookie_pk(conn)
    migrate_json(home, conn)
    return conn


def migrate_cookie_pk(conn):
    """cookies 主键由 name 升级为 (name, domain)，避免跨域同名互相覆盖。"""
    pk = [r["name"] for r in conn.execute("PRAGMA table_info(cookies)")
          if r["pk"]]
    if pk == ["name", "domain"]:
        return
    rows = [dict(r) for r in conn.execute("SELECT * FROM cookies")]
    conn.execute("ALTER TABLE cookies RENAME TO cookies_old")
    conn.execute("""CREATE TABLE cookies (
        name TEXT, domain TEXT, value TEXT, path TEXT,
        expires INTEGER, secure INTEGER, http_only INTEGER,
        PRIMARY KEY (name, domain))""")
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO cookies"
            "(name,domain,value,path,expires,secure,http_only) "
            "VALUES(?,?,?,?,?,?,?)",
            (r.get("name"), r.get("domain") or "", r.get("value"),
             r.get("path") or "/", int(r.get("expires") or 0),
             int(r.get("secure") or 0), int(r.get("http_only") or 0)))
    conn.execute("DROP TABLE cookies_old")
    conn.commit()


# ---------- 迁移旧 JSON ----------
def migrate_json(home, conn):
    done = get_meta(conn, "migrated_v1")
    if done:
        return
    cp = os.path.join(home, "cookies.json")
    sp = os.path.join(home, "state.json")
    if os.path.exists(cp):
        try:
            with open(cp, "r", encoding="utf-8") as f:
                data = json.load(f)
            for c in data.get("cookies") or []:
                if not c.get("name"):
                    continue
                set_cookie(conn, c)
            if data.get("ua"):
                set_meta(conn, "ua", data["ua"])
            if data.get("fingerprint"):
                set_meta(conn, "fingerprint",
                         json.dumps(data["fingerprint"], ensure_ascii=False))
            os.replace(cp, cp + ".bak")
        except Exception:
            pass
    if os.path.exists(sp):
        try:
            with open(sp, "r", encoding="utf-8") as f:
                st = json.load(f)
            for kind in ("board", "thread"):
                v = st.get(kind)
                if v:
                    set_selection(conn, kind, v.get("fid") or v.get("tid"),
                                  v.get("name") or v.get("title"),
                                  int(v.get("page") or 1))
            for kind, items in (st.get("lists") or {}).items():
                save_list(conn, kind, items)
            os.replace(sp, sp + ".bak")
        except Exception:
            pass
    set_meta(conn, "migrated_v1", "1")
    conn.commit()


# ---------- meta（配置） ----------
def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, None if value is None else str(value)))
    conn.commit()


def all_meta(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM meta")}


# ---------- cookies ----------
def set_cookie(conn, c):
    conn.execute(
        "INSERT INTO cookies(name,value,domain,path,expires,secure,http_only) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(name,domain) DO UPDATE SET "
        "value=excluded.value, domain=excluded.domain, path=excluded.path, "
        "expires=excluded.expires, secure=excluded.secure, "
        "http_only=excluded.http_only",
        (c.get("name"), c.get("value"), c.get("domain") or "",
         c.get("path") or "/", int(c.get("expires") or 0),
         1 if c.get("secure") else 0, 1 if c.get("http_only") else 0))
    conn.commit()


def get_cookies(conn):
    out = []
    for r in conn.execute("SELECT * FROM cookies"):
        out.append({"name": r["name"], "value": r["value"],
                    "domain": r["domain"], "path": r["path"],
                    "expires": r["expires"], "secure": bool(r["secure"]),
                    "http_only": bool(r["http_only"])})
    return out


def clear_cookies(conn):
    n = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
    conn.execute("DELETE FROM cookies")
    conn.commit()
    return n


# ---------- 选择 ----------
def set_selection(conn, kind, sid, title="", page=1):
    conn.execute(
        "INSERT INTO selection(kind,id,title,page,ts) VALUES(?,?,?,?,?) "
        "ON CONFLICT(kind) DO UPDATE SET id=excluded.id, title=excluded.title, "
        "page=excluded.page, ts=excluded.ts",
        (kind, str(sid) if sid is not None else "", title or "", int(page or 1),
         int(time.time())))
    conn.commit()


def get_selection(conn):
    return {r["kind"]: dict(r) for r in conn.execute("SELECT * FROM selection")}


def clear_selection(conn, kind=None):
    if kind:
        conn.execute("DELETE FROM selection WHERE kind=?", (kind,))
    else:
        conn.execute("DELETE FROM selection")
    conn.commit()


def set_selection_page(conn, kind, page):
    conn.execute("UPDATE selection SET page=? WHERE kind=?", (int(page), kind))
    conn.commit()


# ---------- 列表（序号 -> id） ----------
def save_list(conn, kind, items):
    conn.execute("DELETE FROM lists WHERE kind=?", (kind,))
    now = int(time.time())
    conn.executemany(
        "INSERT INTO lists(kind,seq,id,label,ts) VALUES(?,?,?,?,?)",
        [(kind, i + 1, str(it.get("id")), it.get("label") or "", now)
         for i, it in enumerate(items)])
    conn.commit()


def get_list(conn, kind):
    return [dict(r) for r in
            conn.execute("SELECT seq,id,label FROM lists WHERE kind=? "
                         "ORDER BY seq", (kind,))]


# ---------- 历史 ----------
def add_history(conn, cmd):
    conn.execute("INSERT INTO history(ts,cmd) VALUES(?,?)",
                 (int(time.time()), cmd))
    conn.commit()