# -*- coding: utf-8 -*-
"""sign（每日签到）的逻辑测试：不真发请求，用假响应覆盖三种状态。"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pojie  # noqa: E402


class FakeResp:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("gbk", "replace")
        self.status_code = 200


class FakeClient:
    """记录请求路径，按预设脚本返回页面。"""

    def __init__(self, pages, logged="iting"):
        self.pages = pages
        self.logged = logged
        self.paths = []

    def logged_in(self):
        return self.logged

    def get(self, path, **kw):
        self.paths.append(path)
        if callable(self.pages):
            return FakeResp(self.pages(path))
        return FakeResp(self.pages.get(path, ""))


TASK = "/home.php?mod=spacecp&ac=credit&showcredit&type=task"

NOT_SIGNED = (
    '<a href="home.php?mod=task&do=apply&id=2&amp;referer=%2Fhome"&gt;'
    '领取今日签到奖励</a>'
)
ALREADY = "<div>今日已签到，暂无新任务</div>"


def test_already_signed():
    """已签到：页面没有签到链接 -> 提示已签过，rc=0。"""
    cl = FakeClient({TASK: ALREADY})
    rc = pojie.cmd_sign(types.SimpleNamespace(), cl)
    assert rc == 0, rc
    assert cl.paths == [TASK], cl.paths
    print("1) 已签到: OK")


def test_not_signed():
    """未签到：页面有 do=apply 链接 -> 访问它，再确认链接消失。"""
    state = {"done": False}

    def pages(path):
        if "do=apply" in path or "do=draw" in path:
            state["done"] = True
            return "<div id=\"messagetext\">签到成功，获得 1 吾爱币</div>"
        return NOT_SIGNED if not state["done"] else ALREADY

    cl = FakeClient(pages)
    rc = pojie.cmd_sign(types.SimpleNamespace(), cl)
    assert rc == 0, rc
    assert state["done"], "签到入口没有被访问"
    assert len(cl.paths) >= 2, cl.paths
    print("2) 未签到 -> 完成签到: OK")


def test_not_logged_in():
    """未登录：直接报错，rc=1。"""
    cl = FakeClient({TASK: ALREADY}, logged=None)
    try:
        pojie.cmd_sign(types.SimpleNamespace(), cl)
    except SystemExit as e:
        assert e.code == 1, e.code
        print("3) 未登录: OK")
        return
    raise AssertionError("未登录时应当退出")


if __name__ == "__main__":
    test_already_signed()
    test_not_signed()
    test_not_logged_in()
