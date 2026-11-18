import subprocess
import sys
import os

env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"

cases = [
    ["forums"],                          # 本地直连
    ["-b", "forums"],                    # 自动
    ["--local", "forums"],               # 强制本机浏览器
    ["--webview", "forums"],             # 强制 App WebView
    ["-L", "whoami"],                    # 短选项
    ["-W", "whoami"],                    # 短选项
    ["--webview", "--local", "forums"],  # 互斥检查
]

for a in cases:
    try:
        p = subprocess.run([sys.executable, "pojie.py"] + a,
                           capture_output=True, env=env, timeout=240)
    except subprocess.TimeoutExpired:
        print("%-34s TIMEOUT" % " ".join(a))
        continue
    out = p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
    lines = [l for l in out.split("\n") if l.strip()]
    head = lines[0][:46] if lines else "(空)"
    print("%-34s rc=%d  %s" % (" ".join(a), p.returncode, head))
