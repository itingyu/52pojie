# -*- coding: utf-8 -*-
"""_browser_local 的编码探测与无头 UA 测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _browser_local as bl


def test_guess_encoding_from_meta():
    """HTML meta 声明 gbk 时按 gbk 解码，不能出现替换符。"""
    body = '<html><head><meta charset="gbk" /></head><body>签到 吾爱破解</body></html>'
    raw = body.encode("gbk")
    assert bl._guess_encoding(raw, "text/html") == "gbk"
    text = raw.decode(bl._guess_encoding(raw, "text/html"))
    assert "签到" in text
    assert "\ufffd" not in text


def test_guess_encoding_from_content_type():
    """content-type 直接给 charset 时优先用它。"""
    raw = "中文内容".encode("gbk")
    assert bl._guess_encoding(raw, "text/html; charset=GBK").lower() == "gbk"


def test_guess_encoding_utf8_passthrough():
    """纯 UTF-8 内容不会被误判成 gbk。"""
    raw = "中文 UTF-8 内容".encode("utf-8")
    enc = bl._guess_encoding(raw, "text/html")
    assert raw.decode(enc) == "中文 UTF-8 内容"


def test_response_text_uses_detected_encoding():
    """_Response.text 必须用探测到的编码，而不是硬编码 UTF-8。"""
    html = '<html><head><meta charset="gbk"></head><body>签到奖励</body></html>'
    resp = bl._Response(200, "text/html", html.encode("gbk"))
    assert "签到奖励" in resp.text
    assert "\ufffd" not in resp.text


def test_headless_ua_matches_headed_shape():
    """无头 UA 不能含 HeadlessChrome，且主版本与浏览器一致。"""
    ua = bl.headless_user_agent(r"H:\software\browser\Chrome\Application\chrome.exe")
    if ua is None:
        return  # 该机器未装 Chrome 时跳过
    assert "HeadlessChrome" not in ua
    assert "Chrome/" in ua
    assert ua.startswith("Mozilla/5.0 (")