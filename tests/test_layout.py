# -*- coding: utf-8 -*-
"""排版回归：表格列宽受终端宽度约束，ANSI 不计入显示宽度。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _ui


def test_dwidth_ignores_ansi():
    # 非 tty 时 c() 不着色，直接用带转义序列的串验证
    plain = _ui.dwidth("置顶")
    colored = _ui.dwidth("\033[35m置顶\033[0m")
    assert plain == colored, (plain, colored)
    print("1) ANSI 不计入宽度: OK (%d)" % plain)


def test_truncate_keeps_ansi():
    s = "\033[35m置顶 \033[0m" + "很长很长很长很长很长很长"
    out = _ui.truncate(s, 10)
    assert _ui.dwidth(out) <= 10, _ui.dwidth(out)
    assert "\033[" in out, "转义序列应保留"
    print("2) 截断保留 ANSI: OK (宽 %d)" % _ui.dwidth(out))


def test_table_fits_width():
    _ui.set_width(60)
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        _ui.table(["序号", "TID", "标题"],
                  [[("#1", None), ("2138234", None),
                    ("很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长", None)]])
    finally:
        sys.stdout = old
    lines = [l for l in buf.getvalue().splitlines() if l.strip()]
    widths = [_ui.dwidth(l) for l in lines]
    assert max(widths) <= 60, widths
    assert any("…" in l for l in lines), "超长单元格应截断"
    print("3) 表格不超终端宽: OK (最宽 %d)" % max(widths))
    _ui.set_width(None)


def test_table_separator_matches_header():
    _ui.set_width(100)
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        _ui.table(["A", "B"], [[("1", None), ("2", None)]])
    finally:
        sys.stdout = old
    lines = [l for l in buf.getvalue().splitlines() if l.strip()]
    assert set(lines[1].strip()) == {"\u2500"}, lines[1]
    assert _ui.dwidth(lines[1]) == _ui.dwidth(lines[0]), (
        _ui.dwidth(lines[1]), _ui.dwidth(lines[0]))
    print("4) 分割线与表头等宽: OK")
    _ui.set_width(None)


if __name__ == "__main__":
    test_dwidth_ignores_ansi()
    test_truncate_keeps_ansi()
    test_table_fits_width()
    test_table_separator_matches_header()
    print("全部通过")
