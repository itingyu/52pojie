"""终端显示与交互增强层。

提供：颜色、中文宽度对齐、终端宽度自适应、表格渲染、JSON 输出。
"""
import json
import os
import re
import shutil
import sys
import unicodedata

# --------------------------------------------------------------------------- #
# 颜色
# --------------------------------------------------------------------------- #
_CODES = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m",
    "grey": "\033[90m", "bred": "\033[91m", "bgreen": "\033[92m",
    "byellow": "\033[93m", "bcyan": "\033[96m", "bwhite": "\033[97m",
}

_COLOR = None


def set_color(enabled):
    global _COLOR
    _COLOR = enabled


_WIDTH = [None]
_JSON = [False]


def set_color(enabled):
    global _COLOR
    _COLOR = bool(enabled)


def set_width(w):
    _WIDTH[0] = int(w) if w else None


def set_json(enabled):
    _JSON[0] = bool(enabled)


def json_mode():
    return _JSON[0]


def color_enabled():
    """默认关闭；--color / POJIE_COLOR=1 才开。"""
    if _COLOR is not None:
        return _COLOR
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("POJIE_COLOR") not in ("1", "true", "yes", "on"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def c(text, *styles):
    """给文本着色。styles 传颜色名，如 c('hi', 'green', 'bold')。"""
    if not styles or not color_enabled():
        return text
    prefix = "".join(_CODES.get(s, "") for s in styles)
    return prefix + text + _CODES["reset"]


# --------------------------------------------------------------------------- #
# 宽度计算（中文按 2 列）
# --------------------------------------------------------------------------- #
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(s):
    """去掉 ANSI 转义序列，只留可见字符。"""
    return _ANSI_RE.sub("", str(s))


def dwidth(s):
    """显示宽度：东亚全角字符算 2 列，忽略 ANSI 转义序列。"""
    w = 0
    for ch in strip_ansi(s):
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad(s, width, align="<"):
    """按显示宽度补空格。"""
    s = str(s)
    gap = max(0, width - dwidth(s))
    if align == ">":
        return " " * gap + s
    if align == "^":
        left = gap // 2
        return " " * left + s + " " * (gap - left)
    return s + " " * gap


def truncate(s, width, ellipsis="…"):
    """按显示宽度截断；ANSI 转义序列不占宽度，会原样保留。"""
    s = str(s)
    if dwidth(s) <= width:
        return s
    out = []
    used = 0
    i = 0
    n = len(s)
    while i < n:
        m = _ANSI_RE.match(s, i)
        if m:                       # 转义序列零宽，原样带上
            out.append(m.group())
            i = m.end()
            continue
        ch = s[i]
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + cw > width - 1:
            break
        out.append(ch)
        used += cw
        i += 1
    return "".join(out) + ellipsis


def term_width(default=100):
    if _WIDTH[0]:
        return max(40, _WIDTH[0])
    try:
        w = shutil.get_terminal_size((default, 24)).columns
    except Exception:
        w = default
    return max(60, min(w, 160))


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def out(line=""):
    sys.stdout.write(line + "\n")


def table(headers, rows, aligns=None, styles=None, gap=2):
    """渲染一个对齐表格。

    headers: 列名列表
    rows:    行数据（元素可为 str 或 (str, style) 元组）
    aligns:  每列对齐 '<' '>' '^'
    styles:  每列的着色样式名
    """
    if not rows:
        return
    aligns = aligns or ["<"] * len(headers)
    styles = styles or [None] * len(headers)
    cells = []
    for r in rows:
        row = []
        for i, cell in enumerate(r):
            txt = cell[0] if isinstance(cell, tuple) else cell
            sty = cell[1] if isinstance(cell, tuple) else styles[i]
            row.append((str(txt), sty))
        cells.append(row)
    widths = [dwidth(h) for h in headers]
    for row in cells:
        for i, (txt, _s) in enumerate(row):
            widths[i] = max(widths[i], dwidth(txt))
    # 列宽不能撑破终端：超宽时从最宽的列开始收，收到刚好放得下
    limit = term_width()
    # 每列的收缩下限：至少留 16 列，标题列才不至于被压成没法看
    minw = [max(4, min(widths[i], 16)) for i in range(len(widths))]
    def total():
        return sum(widths) + gap * (len(widths) - 1)
    while total() > limit:
        # 找还能收的列里最宽的那列
        cand = [i for i in range(len(widths)) if widths[i] > minw[i]]
        if not cand:
            break
        i = max(cand, key=lambda k: widths[k])
        widths[i] -= 1
    # 表头
    head = " ".join(pad(h, widths[i], aligns[i]) for i, h in enumerate(headers))
    out(c(head, "bold"))
    # 分割线与表头等宽，不再画到终端边缘
    out(c("─" * dwidth(head), "grey"))
    for row in cells:
        parts = []
        for i, (txt, sty) in enumerate(row):
            txt = truncate(txt, widths[i])
            parts.append(c(pad(txt, widths[i], aligns[i]), sty) if sty
                         else pad(txt, widths[i], aligns[i]))
        out(" ".join(parts).rstrip())


def kv(pairs, indent=2, key_style="grey"):
    """输出 key: value 形式的信息块。"""
    if not pairs:
        return
    kw = max(dwidth(str(k)) for k, _v in pairs)
    for k, v in pairs:
        if v is None:
            continue
        out("%s%s  %s" % (" " * indent,
                          c(pad(str(k), kw), key_style),
                          v))


def rule(char="─", width=None):
    out(c(char * (width or term_width()), "grey"))


def json_out(obj):
    out(json.dumps(obj, ensure_ascii=False, indent=2))


def human_int(n):
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 10000:
        return "%.1f万" % (n / 10000.0)
    return str(n)


def rel_time(s):
    """把 '2026-11-16 18:39' 变成 '今天 18:39' / '11-16' 之类。"""
    import datetime
    s = (s or "").strip()
    m = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            m = datetime.datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if not m:
        return s
    now = datetime.datetime.now()
    delta = now - m
    if delta.total_seconds() < 60:
        return "刚刚"
    if delta.total_seconds() < 3600:
        return "%d分钟前" % (delta.total_seconds() // 60)
    if m.date() == now.date():
        return "今天 %02d:%02d" % (m.hour, m.minute)
    if m.date() == now.date() - datetime.timedelta(days=1):
        return "昨天 %02d:%02d" % (m.hour, m.minute)
    if m.year == now.year:
        return "%02d-%02d" % (m.month, m.day)
    return s[:10]


def heading(text, sub=None):
    """小节标题：粗体 + 下划线。"""
    out(c(text, "bold"))
    if sub:
        out(c(sub, "grey"))
    out(c("─" * min(dwidth(text), term_width()), "grey"))


def post_title(title, tid=None, fid=None, note=None):
    """帖子标题区。"""
    out()
    out(c("📌 " + (title or "(无标题)"), "bold"))
    meta = []
    if tid:
        meta.append("TID %s" % tid)
    if fid:
        meta.append("版块 %s" % fid)
    if note:
        meta.append(note)
    if meta:
        out(c("   " + "  ·  ".join(meta), "grey"))
    out(c("─" * min(term_width(), 60), "grey"))


def post_floor(label, author, when):
    """楼层分隔行。"""
    out()
    head = c(label, "cyan", "bold")
    out("%s  %s  %s" % (head, c(author, "yellow"),
                       c(short_time(when), "grey")))


_TERM_PUNCT = "。！？；：…）”』】》)!?;:"


def _reflow(lines):
    """把 <br> 造成的硬换行还原成自然段。

    规则：行尾没有终止标点、且下一行不像列表/表格项时，与下一行合并。
    """
    paras, buf = [], ""
    for raw in lines:
        ln = raw.strip()
        if not ln:
            if buf:
                paras.append(buf)
                buf = ""
            paras.append("")
            continue
        if not buf:
            buf = ln
            continue
        is_heading = re.match(
            r"^([-*·•]|\d+[.、)]|[一二三四五六七八九十]+[、.]|表\s*\d|图\s*\d|第[一二三四五六七八九十]+)",
            ln)
        # 只有两行都足够长、且不像标题/列表时才合并（避免把标题吞进正文）
        if (buf[-1] not in _TERM_PUNCT and dwidth(buf) >= 20
                and dwidth(ln) >= 20 and not is_heading):
            if buf[-1].isascii() and buf[-1].isalnum() and ln[0].isascii() and ln[0].isalnum():
                buf += " " + ln
            else:
                buf += ln
        else:
            paras.append(buf)
            buf = ln
    if buf:
        paras.append(buf)
    return paras


def body(text, indent=2):
    """正文：智能重排 + 按终端宽度折行 + 缩进。"""
    text = (text or "").replace("\r", "")
    width = max(40, term_width() - indent - 2)
    for para in _reflow(text.split("\n")):
        if not para.strip():
            out()
            continue
        for seg in wrap(para, width):
            out(" " * indent + seg)


def wrap(text, width):
    """按显示宽度折行（中文按 2 列算）。"""
    if width <= 0:
        return [text]
    lines, cur, cur_w = [], [], 0
    for ch in text:
        w = dwidth(ch)
        if cur_w + w > width and cur:
            lines.append("".join(cur))
            cur, cur_w = [], 0
        cur.append(ch)
        cur_w += w
    if cur:
        lines.append("".join(cur))
    return lines
def short_time(s):
    """把 '2026-1-22 12:34' 补零成 '2026-01-22 12:34'；异常值原样返回。"""
    s = (s or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{1,2}:\d{2})?", s)
    if not m:
        return s[:16]
    y, mo, d, hm = m.groups()
    out_s = "%s-%02d-%02d" % (y, int(mo), int(d))
    if hm:
        hh, mm = hm.split(":")
        out_s += " %02d:%s" % (int(hh), mm)
    return out_s