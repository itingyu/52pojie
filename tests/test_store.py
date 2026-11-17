import os, sqlite3, sys, tempfile, time, importlib.util
from http.cookiejar import Cookie

SRC = "/var/minis/shared/code/pojie"
sys.path.insert(0, SRC)
spec = importlib.util.spec_from_file_location("store", os.path.join(SRC, "_store.py"))
store = importlib.util.module_from_spec(spec); spec.loader.exec_module(store)

tmp = tempfile.mkdtemp(prefix="pj_")
home = os.path.join(tmp, "home")

conn = store.connect(home)
store.set_cookie(conn, {"name": "auth", "value": "www-v", "domain": "www.x.cn"})
store.set_cookie(conn, {"name": "auth", "value": "root-v", "domain": ".x.cn",
                        "expires": 1893456000, "secure": True, "http_only": True})
rows = {r["domain"]: r for r in store.get_cookies(conn)}
print("1) 跨域同名保留:", len(rows) == 2, "| 属性:", rows[".x.cn"]["expires"],
      rows[".x.cn"]["secure"], rows[".x.cn"]["http_only"])
conn.close()

old = os.path.join(tmp, "old.db")
c = sqlite3.connect(old)
c.execute("CREATE TABLE cookies(name TEXT PRIMARY KEY,value TEXT,domain TEXT,"
          "path TEXT,expires INTEGER,secure INTEGER,http_only INTEGER)")
c.execute("INSERT INTO cookies VALUES('auth','oldv','www.x.cn','/',0,0,0)")
c.commit(); c.close()
conn = store.connect(home, old)
print("2) 主键升级:", [r["name"] for r in conn.execute("PRAGMA table_info(cookies)")
                      if r["pk"]] == ["name", "domain"],
      "| 旧数据保留:", store.get_cookies(conn)[0]["value"] == "oldv")
conn.close()

print("3) 权限 db=%o dir=%o" % (os.stat(store.db_path(home)).st_mode & 0o777,
                                os.stat(home).st_mode & 0o777))

import pojie
cl = pojie.Client(home=home, cookie_file=os.path.join(tmp, "custom.db"))
print("4) cookie_file 生效:", cl.cookie_file.endswith("custom.db"))

ck = Cookie(0, "k", "v", None, False, "www.x.cn", True, False, "/", True,
            True, int(time.time()) + 3600, False, None, None,
            {"HttpOnly": None}, False)
cl.s.cookies.jar.set_cookie(ck)
expired = Cookie(0, "dead", "x", None, False, "www.x.cn", True, False, "/",
                 True, False, int(time.time()) - 10, False, None, None, {}, False)
cl.s.cookies.jar.set_cookie(expired)
cl.save_cookies()
row = [r for r in store.get_cookies(cl.db) if r["name"] == "k"][0]
print("5) 落库属性:", row["expires"] > 0, row["secure"], row["http_only"])

cl2 = pojie.Client(home=home, cookie_file=os.path.join(tmp, "custom.db"))
names = {c.name for c in cl2.s.cookies.jar}
k = [c for c in cl2.s.cookies.jar if c.name == "k"][0]
print("6) 回读属性:", k.secure, k.expires > 0,
      "HttpOnly" in (k._rest or {}), "| 过期项跳过:", "dead" not in names)