# -*- coding: utf-8 -*-
"""防回归：登录相关的函数必须都在（曾被批量删除误伤）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pojie


def test_login_functions_present():
    for name in ("import_cookie_text", "paste_cookie_login", "login_form",
                 "login_browser", "parse_login_page", "cmd_login",
                 "cmd_auth", "cmd_logout"):
        assert hasattr(pojie, name), "缺少函数: %s" % name
    print("1) 登录相关函数齐全: OK")


def test_cookie_import_works(tmp_home="/tmp/pj_test_login"):
    cl = pojie.Client(home=tmp_home)
    n = pojie.import_cookie_text(
        cl, "htVC_2132_auth=abc; htVC_2132_saltkey=xyz")
    assert n == 2, n
    # 每个 cookie 同时写 .host 与 host 两个 domain，复合主键下各算一条
    rows = list(cl.db.execute("SELECT name, domain FROM cookies"))
    assert len(rows) == 4, rows
    names = {r["name"] for r in rows}
    assert names == {"htVC_2132_auth", "htVC_2132_saltkey"}, names
    print("2) cookie 串可导入: OK (%d 条 → 落库 %d 条)" % (n, len(rows)))
    cl.db.close()


if __name__ == "__main__":
    test_login_functions_present()
    test_cookie_import_works()
    print("全部通过")

