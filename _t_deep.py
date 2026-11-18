import subprocess
import sys
import os
import json

env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"

MODE = sys.argv[1] if len(sys.argv) > 1 else ""

CASES = [
    (["forums"],                     "版块列表"),
    (["forums", "--grep", "病毒"],   "版块过滤"),
    (["threads", "-f", "32"],        "列帖子"),
    (["threads", "-f", "32", "--no-pin"], "排除置顶"),
    (["thread", "2097399"],          "读帖子正文"),
    (["thread", "2097399", "--page", "2"], "读第2页"),
    (["thread", "2097399", "--op"],  "只看楼主"),
    (["thread", "2097399", "--author", "Hmily"], "只看指定作者"),
    (["latest", "--grep", "勒索"],    "新帖过滤"),
    (["search", "银狐"],             "搜索"),
    (["--json", "forums"],          "JSON 输出"),
    (["--json", "threads", "-f", "32"], "JSON 帖子列表"),
    (["whoami"],                    "登录态"),
    (["status"],                    "当前选择"),
]

if MODE:
    CASES = [([MODE] + a, t) for a, t in CASES]

for a, label in CASES:
    try:
        p = subprocess.run([sys.executable, "pojie.py"] + a,
                           capture_output=True, env=env, timeout=300)
    except subprocess.TimeoutExpired:
        print("%-22s TIMEOUT" % label)
        continue
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    lines = [l for l in out.split("\n") if l.strip()]
    if p.returncode != 0:
        msg = (err or out).strip().split("\n")[0][:52]
        print("%-22s rc=%d  ! %s" % (label, p.returncode, msg))
        continue
    # 额外校验：JSON 必须能解析
    note = ""
    if a and a[0] == "--json":
        try:
            json.loads(out)
            note = " [json ok]"
        except Exception as e:
            note = " [JSON PARSE FAIL: %s]" % str(e)[:30]
    head = lines[0][:44] if lines else "(空)"
    print("%-22s rc=%d  %-46s 行数%-4d%s" % (label, p.returncode, head, len(lines), note))
