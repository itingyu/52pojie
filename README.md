# pojie — 52pojie.cn 命令行阅读器

纯 Python（3.8+），零外部依赖即可运行核心逻辑；美化输出、支持 JSON。

## 安装

```bash
python pojie.py setup          # 装依赖：curl_cffi / beautifulsoup4
```

或标准 Python 方式：

```bash
pip install .                  # 装成命令，之后直接用 pojie
```

`pojie.bat` 是给 Windows 的薄壳，内部就是 `python pojie.py %*`。

## 选定上下文（推荐用法）

先选一次，之后命令都作用于它，不用反复传参数：

```bash
pojie select 病毒分析      # 选定板块（也可写 fid：select 32）
pojie threads              # 直接列出该板块帖子
pojie select 2137132       # 选定帖子（也可粘整条网址）
pojie thread               # 直接看正文
pojie thread --next        # 下一页（页码会被记住）
pojie thread --prev        # 上一页
pojie thread --op          # 只看楼主（同样作用于当前帖子）
pojie status               # 看当前选中了什么
pojie select --clear       # 清除选择
```

选择存在 `~/.52pojie/state.json`，跨命令、跨会话保留。

### 交互式阅读器的按键

```bash
pojie thread --pager
```

| 按键 | 作用 |
|---|---|
| ↑ ↓ / j k | 上下滚一行 |
| PgUp PgDn / 空格 | 上下一屏 |
| ← → | 上一楼页 / 下一楼页 |
| n p | 同上（字母键） |
| g G | 跳到开头 / 结尾 |
| q | 退出 |

滚到本页底部会自动加载下一楼页（无需手动 n）。非终端环境（管道、重定向）会自动改为一次性全部打印。

### 两种写法怎么区分（不会串）

| 情况 | 命令 | 用什么 |
|---|---|---|
| 显式给了参数 | `thread 2137132` / `threads -f 32` | **参数优先**，同时把结果记为当前选择 |
| 只临时看一眼 | `thread 123 --keep` / `threads -f 10 --keep` | 参数优先，**不改动选择** |
| 没给参数 | `thread` / `threads` | 用 `select` 的选择；没有就报错提示 |
| 读了一个帖子 | `thread ...` | 板块上下文跟着切到**该帖所属板块** |

每次输出末尾都会打印等价命令，方便复制或记住参数：

```
共 48 条 · thread <TID> 看正文
等价命令  pojie.bat threads -f 10 --no-pin
（已把「『水漫金山』」记为当前选择）
```

输出里会标注来源，一眼能看出这次是谁在起作用：

```
『病毒分析区』
来自 select 的选择          ← 用的是选择
──────────────

📌 吾爱破解论坛精华集2025
   TID 2097399 · 版块 42 · 第 2 页 · 来自 select   ← 同上
```

没有 `来自 select` 字样，就说明这次是你显式传的参数。执行 `pojie` 不带任何命令会打印当前选择和常用命令。

## 命令

| 命令 | 说明 |
|---|---|
| `forums` | 列出所有版块（30 个） |
| `forums --grep 病毒` | 按名称过滤版块 |
| `select <板块/TID>` | 选定当前板块或帖子 |
| `status` | 查看当前选择与登录状态 |
| `threads` | 列出当前选中板块的帖子 |
| `threads --fid 32` | 指定板块（会更新选择） |
| `threads -f 水漫金山` | **板块名可以直接写**，不用记 fid |
| `threads -f 32 --grep 求助` | 列表页本地关键字过滤 |
| `threads -f 32 --no-pin` | 不显示置顶帖 |
| `threads -f 32 --pin-only` | 只看置顶帖 |
| `threads -f 32 --page 2` | 翻页 |
| `latest` | 全站新帖导读 |
| `latest --grep 勒索` | 新帖里过滤 |
| `thread 2137132` | 看帖子正文和各楼回复 |
| `thread https://www.52pojie.cn/thread-2137132-1-1.html` | **直接粘网址** |
| `thread 2137132 --page 2` | 看第 2 页楼层 |
| `thread 2137132 --pager` | **交互式阅读**：方向键/PgUp·PgDn 翻阅，到底自动加载下一页 |
| `thread 2137132 --all` | 一次抓全部分页（脚本/导出用） |
| `thread 2137132 --op` | **只看楼主**（服务端 `authorid` 过滤，等同页面上的"只看该作者"） |
| `thread 2137132 --op --all` | 只看楼主，抓齐全部分页 |
| `thread 2137132 --op --page 2` | 筛选结果里的第 2 页 |
| `thread 2137132 --author 某人` | 只看指定昵称 |
| `search 银狐` | 搜索（走 360 优先，Bing 兜底） |
| `auth` | 打开本机浏览器，你手动登录，工具自动收回 cookie |
| `auth --paste` | 没有浏览器时：粘贴整行 Cookie 登录 |
| `whoami` | 看登录状态 |
| `logout` | 清除本地登录态 |

## 全局开关

```bash
--json          输出 JSON，便于脚本处理
--color         开启彩色输出（默认关闭，等价 POJIE_COLOR=1）
--width 80      指定输出宽度（默认取终端宽度）
--delay-min / --delay-max    请求间隔区间，默认 0.7~1.3 秒随机
--delay 1.0     设基准值，等价 0.75~1.5 秒
--transport browser   借道 Minis App 内已登录的 WebView 发请求（Android）
```

例：

```bash
pojie --json threads -f 32 | jq '.[0].title'
pojie --no-color --width 80 thread 2137132
```

## 显示优化

- **中文宽度对齐**：表格按东亚全角字符 2 列计算，中英混排不再错位。
- **时间归一化**：`2026-1-22 1` → `2026-01-22 16:34`。
- **正文重排**：站点 `<br>` 造成的硬换行按段落规则还原，再按终端宽度折行。
- **楼层标签**：`楼主 · 1楼`、`11楼`，Discuz 楼号由 JS 渲染，工具按 DOM 顺序推算；`--op` 过滤视图里站点会重新编号，此时保留站点原标记。
- **颜色**：默认关闭；`--color` 或 `POJIE_COLOR=1` 开启，`NO_COLOR` 强制关闭，非 tty 不输出颜色。

## 反反爬

每次请求都按真实浏览器发，且间隔随机，不做并发：

- **TLS/JA3 指纹（强制）**：`curl_cffi` 的 `Session(impersonate="chrome")`，握手特征与 Chrome 一致。**不提供 requests 降级**——缺 curl_cffi 直接退出，杜绝裸 TLS 请求被风控识别。
- **请求头全套**：`Accept`、`Accept-Language: zh-CN,zh;q=0.9,en;q=0.8`、`Upgrade-Insecure-Requests`、`Sec-Fetch-Site/Mode/User/Dest`、`Cache-Control: max-age=0`。`User-Agent` 与 `sec-ch-ua` 交给 curl_cffi 按 fingerprint profile 生成，**不手写**，避免 UA 与 TLS 指纹对不上。
- **Referer 自动滚动**：下一次请求带上一页地址做 Referer，`Sec-Fetch-Site` 相应为 `same-origin`；首次请求无 Referer 时为 `none` —— 和真人点链接的轨迹一致。
- **Origin**：仅 POST 时发，值为站点根。
- **随机间隔**：每次请求前在 0.7~1.3 秒间随机取值（含首次），单线程串行，不并发、不压测。
- **429 退避**：被限速等 10 秒重试，最多 3 次。

## 登录与浏览器检测

`pojie auth` 会先找本机浏览器，顺序是：

1. **注册表 App Paths**（`HKCU/HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{chrome,msedge,firefox,brave}.exe`）——装在 D 盘等自定义位置也能找到；
2. **常见安装目录**：`%ProgramFiles%`、`%ProgramFiles(x86)%`、`%LOCALAPPDATA%`、`%LOCALAPPDATA%\Programs` 下的标准相对路径；
3. **PATH** 里的 `chrome` / `msedge` / `firefox` / `brave`。

找到后按 `chrome → edge → brave → firefox` 优先选用，`--browser edge` 可指定。

**没有浏览器时自动改为粘贴 Cookie**，不会报错退出：

```
pojie auth --paste          # 直接走粘贴模式（也可以省略，检测不到会自动进这个模式）
```

会提示你：用任意浏览器登录 → F12 → 网络 → 任一请求 → 复制 Request Headers 里的整行 Cookie → 粘进终端（无回显）→ 回车。工具解析后写入 SQLite，并立刻校验登录态（识别不到会明确告知，而不是假装成功）。

也可以非交互地导入：

```bash
pojie login --cookie "htVC_2132_auth=...; htVC_2132_saltkey=..."
```

## 浏览器传输模式（--transport browser）

在 Minis App（Android）里，可以不导 cookie，直接借用 App 内已登录的 WebView 发请求：

```bash
pojie --transport browser threads -f 10
pojie --transport browser whoami
```

原理与边界：

- 请求交给 App 的浏览器执行（同源 `fetch`），**登录态直接生效**——`htVC_2132_auth` 是 HttpOnly，本地进程读不到，借道浏览器是唯一不需要复制 cookie 的路子；
- 需要 App 处于前台：后台标签会被 WebView 冻结（`fetch` 与定时器一起挂起），传输层会自己开一个前台标签；
- 正文按原始字节取回再本地解码，站点是 GBK 也不会乱码；
- 跨域请求（360/Bing 搜索）同源策略挡不住，自动回退到 curl 指纹会话，此时按游客态处理；
- App 未登录时行为与游客一致（只能看第 1 页、看不到私密版块）。

## 已知限制

- **站内搜索已被站点废弃**：`search.php` 一律 302 到 Bing，且 Bing 对本站几乎无索引，所以 `search` 改走 360/Bing 外链解析。找具体帖子首选 `threads --grep` / `latest --grep` 本地过滤。
- **登录是 Cloudflare Turnstile**：无法纯脚本过验证，所以设计成 `auth` 打开浏览器由你手动登录、工具回收 cookie。也支持 `login --cookie "..."` 直接导入。
- **纯只读**：没有发帖/回帖命令，从源码层面就不存在。

## 数据位置

- 全部状态在 SQLite：`%USERPROFILE%\.52pojie\pojie.db`（可用 `--home` 改）
- 表：`meta`（UA/指纹）、`cookies`、`selection`（当前板块/帖子）、`lists`（序号→ID）、`history`、`cache`
- 板块列表缓存 **一天**，`forums --refresh` 强刷；cookie 长期有效，`logout` 只删 cookie

## 环境变量

账号密码可放 `POJIE_52_ACCOUNT` / `POJIE_52_PASSWD`，`login` 时会自动读取（进程环境 → Windows 用户级注册表 → 交互输入）。