# -*- coding: utf-8 -*-
"""终端编码自适应：让输出在 UTF-8 / GBK 终端下都不乱码。

背景：Windows 上 Python 重定向到文件/管道时，stdout 默认跟随系统 ANSI
代码页（zh-CN 是 cp936/GBK），在真正支持 UTF-8 的终端（Windows Terminal、
SSH、Git Bash）里中文会显示成乱码。

策略：
1. stdout 已是 UTF-8（Python 3.6+ 直连控制台时就是）就原样不动。
2. 重定向到文件/管道：统一写纯 UTF-8，不加 BOM。
3. 兜底：任何情况都不因编码问题抛 UnicodeEncodeError —— errors="replace"。
"""

import os
import sys


def _is_tty(stream):
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _console_code_page():
    """Windows 控制台当前输出代码页（GBK=936，UTF-8=65001）。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetConsoleOutputCP())
    except Exception:
        return None


def _set_console_code_page(cp):
    """尝试把控制台切到指定代码页，返回是否成功。

    只影响当前控制台窗口，不写系统注册表、也不影响其它终端。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetConsoleOutputCP(cp))
    except Exception:
        return False


def setup(force=None, stream=None):
    """配置 stdout/stderr 编码，返回最终生效的编码名。

    force: 'utf-8' 强制 UTF-8，'native' 跟随系统编码，None 自动判断。
    """
    out = stream or sys.stdout
    if force == "native":
        return out.encoding or "?"

    enc = (out.encoding or "").lower()
    # 已经是 UTF-8（含 Python 3.6+ 直连控制台的情况）就别动
    if "utf-8" in enc or "utf8" in enc:
        return out.encoding

    if force == "utf-8":
        target = "utf-8"
    elif _is_tty(out):
        # 老式 cmd：切不了 65001 就用系统编码（GBK 在那里反而是对的）
        if _set_console_code_page(65001):
            target = "utf-8"
        else:
            target = "gbk" if "gb" in enc else (out.encoding or "utf-8")
    else:
        # 重定向到文件/管道：写纯 UTF-8（无 BOM）
        target = "utf-8"

    try:
        out.reconfigure(encoding=target, errors="replace")
    except Exception:
        try:
            import io
            out = io.TextIOWrapper(out.buffer, encoding=target,
                                   errors="replace", line_buffering=True)
            sys.stdout = out
        except Exception:
            return out.encoding or "?"
    return out.encoding or target
