# -*- coding: utf-8 -*-
"""粘网址时要保留 URL 里的页码。"""
import os, sys

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)
import pojie as P


def test_url_page_hint():
    assert P.url_page_hint("https://www.52pojie.cn/thread-2137132-1-1.html") == 1
    assert P.url_page_hint("https://www.52pojie.cn/thread-2137132-4-1.html") == 4
    assert P.url_page_hint("2137132") is None
    assert P.url_page_hint(None) is None
    print("1) URL 页码解析: OK")


def test_normalize_tid():
    assert P.normalize_tid("2137132") == "2137132"
    assert P.normalize_tid("thread-2137132-1-1.html") == "2137132"
    assert P.normalize_tid(
        "https://www.52pojie.cn/thread-2137132-1-1.html") == "2137132"
    print("2) TID 归一化: OK")


if __name__ == "__main__":
    test_url_page_hint()
    test_normalize_tid()
    print("全部通过")
