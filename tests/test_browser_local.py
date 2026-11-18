# -*- coding: utf-8 -*-
"""本地浏览器后端的逻辑测试（不真启动浏览器）。

用假 driver 验证：脚本拼装、回执解析、跨域回退、profile 目录共享。
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _browser_local as bl   # noqa: E402


class FakePage:
    """模拟 playwright page：记录脚本，按脚本里的 url 返回预置回执。"""

    def __init__(self, payload=b"hello", status=200, ctype="text/html"):
        self.payload = payload
        self.status = status
        self.ctype = ctype
        self.calls = []
        self.pages = []

    def goto(self, url, **kw):
        self.pages.append(url)

    def evaluate(self, script, *args):
        self.calls.append(script)
        b64 = base64.b64encode(self.payload).decode()
        return "%d\n%s\n%s" % (self.status, self.ctype, b64)

    def close(self):
        pass


def test_response_parsing():
    s = bl.LocalBrowserSession("https://www.52pojie.cn")
    fake = FakePage("中文页面内容".encode("gbk"), 200,
                      "text/html; charset=gbk")
    s._page = fake
    s._at_origin = True
    r = s.get("/forum-10-1.html")
    assert r.status_code == 200, r.status_code
    assert r.content.decode("gbk") == "中文页面内容"
    assert r.headers.get("content-type").startswith("text/html")
    print("1) 回执解析: OK")


def test_origin_navigation():
    """请求前必须先停在本站，否则同源 cookie 带不上。"""
    s = bl.LocalBrowserSession("https://www.52pojie.cn")
    fake = FakePage()
    s._page = fake
    s.get("/forum-10-1.html")
    assert fake.pages and fake.pages[0].startswith("https://www.52pojie.cn"), fake.pages
    print("2) 先落本站: OK")


def test_params_merged():
    s = bl.LocalBrowserSession("https://www.52pojie.cn")
    fake = FakePage()
    s._page = fake
    s._at_origin = True
    s.get("/forum.php", params={"mod": "forumdisplay", "fid": "10"})
    assert "mod=forumdisplay" in fake.calls[0], fake.calls[0][:200]
    assert "fid=10" in fake.calls[0]
    print("3) 查询参数拼进脚本: OK")


def test_cross_host_fallback():
    """跨域请求不能走页内 fetch，应回退 curl 会话。"""
    s = bl.LocalBrowserSession("https://www.52pojie.cn")
    fake = FakePage()
    s._page = fake
    s._at_origin = True
    called = {}

    class FakeCurl:
        def request(self, method, url, **kw):
            called["url"] = url
            return "curl-response"

    s._curl = FakeCurl()
    out = s.get("https://www.so.com/s?q=abc")
    assert out == "curl-response", out
    assert "so.com" in called["url"]
    assert not fake.calls, "跨域不该执行页内脚本"
    print("4) 跨域回退 curl: OK")


def test_profile_shared_with_auth():
    """auth 与传输层必须用同一个 profile，登录态才能传递。"""
    import pojie
    d = pojie.browser_profile_dir("/tmp/home-x")
    assert d.endswith(os.path.join("home-x", "browser-profile")), d
    assert os.path.join(d, "x") == os.path.join(
        pojie.browser_profile_dir("/tmp/home-x"), "x")
    print("5) profile 目录共享: OK")


def test_browser_detection():
    found = bl.find_browsers()
    assert isinstance(found, list)
    for key, path in found:
        assert os.path.exists(path), path
    pref = bl._default_browser_key()
    if pref and found:
        assert found[0][0] == pref or any(k == pref for k, _ in found)
    print("6) 浏览器探测: %s（默认 %s）"
          % ([k for k, _ in found] or ["无"], pref or "未知"))


if __name__ == "__main__":
    test_response_parsing()
    test_origin_navigation()
    test_params_merged()
    test_cross_host_fallback()
    test_profile_shared_with_auth()
    test_browser_detection()
    print("全部通过")
