"""交互式翻页阅读器：方向键 / PgUp·PgDn 滚动，n·p 换楼页，读到底自动加载下一页。"""
import os
import re
import shutil
import sys

import _ui

ALT_ON = "\x1b[?1049h"
ALT_OFF = "\x1b[?1049l"
CLR = "\x1b[H\x1b[2J"


def _enable_vt():
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        k.GetConsoleMode(h, ctypes.byref(mode))
        k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


_ARROWS = {"H": "up", "P": "down", "K": "left", "M": "right",
           "I": "pgup", "Q": "pgdn", "G": "home", "O": "end"}


def read_key():
    """读一个按键，返回语义名。"""
    if not sys.stdin.isatty():
        ch = sys.stdin.read(1)
        return ch or "quit"
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return _ARROWS.get(msvcrt.getwch(), "")
        if ch == "\r":
            return "down"
        if ch == "\x1b":
            return "quit"
        if ch == "\x03":
            return "quit"
        return ch
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        b = os.read(fd, 1)
        if b == b"\x1b":
            b2 = os.read(fd, 1)
            if b2 != b"[":
                return "quit"
            seq = b""
            while True:
                c = os.read(fd, 1)
                seq += c
                if c.isalpha() or c == b"~":
                    break
            return {b"A": "up", b"B": "down", b"C": "right", b"D": "left",
                    b"5~": "pgup", b"6~": "pgdn", b"H": "home",
                    b"F": "end", b"1~": "home", b"4~": "end"}.get(seq, "")
        if b in (b"q", b"Q", b"\x03"):
            return "quit"
        if b == b" ":
            return "pgdn"
        if b == b"\r":
            return "down"
        return b.decode("utf-8", "ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


class Pager:
    """lines 是已经排好版（含颜色码）的行；fetch(page) 负责取新的一楼页。"""

    def __init__(self, lines, fetch=None, page=1, total_pages=1, title=""):
        self.lines = lines
        self.fetch = fetch
        self.page = page
        self.total_pages = total_pages
        self.title = title
        self.pos = 0
        self.loading = False

    # ---------- 显示 ----------
    def _size(self):
        sz = shutil.get_terminal_size((80, 24))
        return max(40, sz.columns), max(6, sz.lines)

    def _bar(self, w):
        left = "  %s  " % (self.title or "")[:max(10, w - 40)]
        right = " %d/%d 楼页 · %d%% " % (
            self.page, max(self.total_pages, self.page),
            int(100 * self.pos / max(1, len(self.lines) - 1)))
        pad = w - _ui.dwidth(left) - _ui.dwidth(right)
        return _ui.c(left + " " * max(0, pad) + right, "reverse")

    def draw(self):
        w, h = self._size()
        body_h = h - 2
        vis = self.lines[self.pos:self.pos + body_h]
        buf = [CLR, self._bar(w)]
        buf.extend(vis)
        while len(buf) < h - 1:
            buf.append("")
        hint = " ↑↓/PgUp·PgDn 滚动   ←→/n·p 换楼页   g/G 顶·底   q 退出 "
        buf.append(_ui.c(hint[:w], "grey"))
        sys.stdout.write("\n".join(buf))
        sys.stdout.flush()

    # ---------- 数据 ----------
    def _append_next(self):
        if not self.fetch or self.loading or self.page >= self.total_pages:
            return False
        self.loading = True
        try:
            got = self.fetch(self.page + 1)
        finally:
            self.loading = False
        if not got:
            self.total_pages = self.page
            return False
        self.page += 1
        self.lines.append("")
        self.lines.append(_ui.c("── 第 %d 页 ──" % self.page, "magenta"))
        self.lines.extend(got)
        return True

    def _load_prev(self):
        if not self.fetch or self.page <= 1:
            return False
        got = self.fetch(self.page - 1)
        if not got:
            return False
        self.page -= 1
        self.lines = got + ["", _ui.c("── 第 %d 页 ──" % self.page, "magenta")] + self.lines
        return True

    # ---------- 主循环 ----------
    def run(self):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            sys.stdout.write("\n".join(self.lines) + "\n")
            return
        _enable_vt()
        _ui.set_color(True)
        sys.stdout.write(ALT_ON)
        try:
            while True:
                w, h = self._size()
                body_h = h - 2
                self.draw()
                k = read_key()
                maxpos = max(0, len(self.lines) - body_h)
                if k in ("quit", "q", "Q"):
                    return
                if k == "down":
                    self.pos += 1
                elif k == "up":
                    self.pos -= 1
                elif k in ("pgdn", " "):
                    self.pos += body_h
                elif k in ("pgup",):
                    self.pos -= body_h
                elif k == "home":
                    self.pos = 0
                elif k == "end":
                    self.pos = 10 ** 9
                elif k == "right":
                    if self.pos + body_h >= len(self.lines) - 1:
                        self._append_next()
                    self.pos += body_h
                elif k == "left":
                    self.pos -= body_h
                elif k == "n":
                    self._append_next()
                    self.pos = 10 ** 9
                elif k == "p":
                    self._load_prev()
                    self.pos = 0
                # 滚到底自动续下一页
                if self.pos > maxpos and self.fetch and self.page < self.total_pages:
                    if self._append_next():
                        maxpos = max(0, len(self.lines) - body_h)
                self.pos = max(0, min(self.pos, maxpos))
        finally:
            sys.stdout.write(ALT_OFF)
            sys.stdout.flush()


def build_lines(posts, filtered=False):
    """把楼层渲染成行列表（已按终端宽度折行）。"""
    width = max(40, _ui.term_width() - 6)
    out = []
    for p in posts:
        label = (p.get("floor") or "").strip() or "楼层"
        head = "%s  %s  %s" % (_ui.c(label, "cyan", "bold"),
                               _ui.c(p.get("author") or "匿名", "yellow"),
                               _ui.c(_ui.short_time(p.get("time") or ""), "grey"))
        out.append("")
        out.append(head)
        for para in (p.get("content") or "").split("\n"):
            if not para.strip():
                out.append("")
                continue
            for seg in _ui.wrap(para.strip(), width):
                out.append("  " + seg)
    return out