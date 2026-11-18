# 52pj — 52pojie.cn 命令行阅读器

纯 Python（3.8+），只读浏览 52pojie.cn；美化输出、支持 JSON。

仓库：`github.com/itingyu/52pojie`（私有）。

设计文档：[架构设计.md](docs/架构设计.md) · [功能设计.md](docs/功能设计.md)

必需依赖三个，缺任何一个都会直接退出（不降级、不静默跳过）：

- `curl_cffi` —— TLS 指纹，所有请求都走它的 Chrome 指纹
- `beautifulsoup4` —— 页面解析
- `playwright` —— 驱动本机浏览器（`--local` 后端用它）

## 安装

```bash
python pojie.py setup    # 一次装齐：curl_cffi / beautifulsoup4 / playwright
```

或标准 Python 方式：

```bash
pip install .                  # 装成命令，之后直接用 52pj
```

`52pj.bat` 是给 Windows 的薄壳，内部就是 `python pojie.py %*`。

> **国内网络提示**：`pip install .` 会联网拉构建依赖（setuptools），默认源连不上时
> 换镜像：`pip install . -i https://pypi.tuna.tsinghua.edu.cn/simple`。

## 终端编码

输出编码自动适配，不用手工设置：

- 重定向到文件或管道 → 写**纯 UTF-8，不带 BOM**（`utf-8` 而非 `utf-8-sig`）；
- 交互终端 → 自动把控制台切到 65001（UTF-8），切不动就退回系统编码（GBK）；
- 任何情况下都不会因编码问题崩溃（`errors="replace"` 兜底）。

需要强制时用环境变量：

```bash
52PJ_ENCODING=utf-8  52pj forums   # 强制 UTF-8
52PJ_ENCODING=native 52pj forums   # 强制跟随系统编码
52PJ_ENCODING=gbk    52pj forums   # 强制 GBK
```

## 选定上下文（推荐用法）

先选一次，之后命令都作用于它，不用反复传参数：

```bash
52pj select 病毒分析      # 选定板块（也可写 fid：select 32）
52pj threads              # 直接列出该板块帖子
52pj select 2137132       # 选定帖子（也可粘整条网址）
52pj thread               # 直接看正文
52pj thread --next        # 下一页（页码会被记住）
52pj thread --prev        # 上一页
52pj thread --op          # 只看楼主（同样作用于当前帖子）
52pj status               # 看当前选中了什么
52pj select --clear       # 清除选择
```

选择存在 `~/.52pj/state.json`，跨命令、跨会话保留。

### 交互式阅读器的按键

```bash
52pj thread --pager
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
共 48 条 · select #<序号> 选中 · thread #<序号> 直接读
等价命令  52pj threads -f 10 --no-pin        ← Windows 上是 52pj.bat
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

没有 `来自 select` 字样，就说明这次是你显式传的参数。执行 `52pj` 不带任何命令会打印当前选择和常用命令。

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
| `setup` | 装 / 检查依赖包（curl_cffi / beautifulsoup4 / playwright） |
| `auth` | 打开本机浏览器，你手动登录，工具自动收回 cookie |
| `auth --paste` | 没有浏览器时：粘贴整行 Cookie 登录 |
| `login -u 账号 -p 密码` | 账号密码登录（站点要 Turnstile 时会失败） |
| `login --cookie "k=v; k2=v2"` | 直接导入整行浏览器 Cookie |
| `login --browser` | 用本机浏览器登录（可人工过验证码） |
| `whoami` | 看登录状态 |
| `logout` | 清除本地登录态 |
| `sign` | **每日签到**，领取论坛币（唯一的写操作） |
| `sign` | **每日签到**，领取论坛币（唯一的写操作） |

## 全局开关

```bash
-b / --browser  借道浏览器发请求（自动选后端）
-W / --webview  强制用 Minis App 内已登录的 WebView
-L / --local    强制用本机默认浏览器（Playwright 驱动）
--json          输出 JSON，便于脚本处理
--color         开启彩色输出（默认关闭，等价 POJIE_COLOR=1）
--width 80      指定输出宽度（默认取终端宽度）
--delay-min / --delay-max    请求间隔区间，默认 0.7~1.3 秒随机
--delay 1.0     设基准值，等价 0.75~1.5 秒
-b, --browser   借道 Minis App 内已登录的 WebView 发请求（可放在子命令前后）
```

例：

```bash
52pj --json threads -f 32 | jq '.[0].title'
52pj --no-color --width 80 thread 2137132
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

`52pj auth` 用 **Playwright** 驱动本机已安装的浏览器（不下载浏览器、不需要
chromedriver，也不往代码目录里写任何驱动文件）。

**先认「系统默认浏览器」**：读注册表 `UserChoice` 的 ProgId，再顺着
`HKCR\<ProgId>\shell\open\command` 找到那个 exe。这台机器上装了多个 Chrome
时（不同盘、不同版本），只有走这一层才能拿到你真正在用的那个。

然后按下面的顺序补齐候选：

1. **注册表 App Paths**（`HKCU/HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{chrome,msedge,firefox,brave}.exe`）——装在 D 盘等自定义位置也能找到；
2. **常见安装目录**：`%ProgramFiles%`、`%ProgramFiles(x86)%`、`%LOCALAPPDATA%`、`%LOCALAPPDATA%\Programs` 下的标准相对路径；
3. **PATH** 里的 `chrome` / `msedge` / `firefox` / `brave`。

优先级：系统默认浏览器 → `chrome` → `edge` → `brave` → `firefox`，
`--browser edge` 可指定。

**没有浏览器时自动改为粘贴 Cookie**，不会报错退出：

```
52pj auth --paste          # 直接走粘贴模式（也可以省略，检测不到会自动进这个模式）
```

会提示你：用任意浏览器登录 → F12 → 网络 → 任一请求 → 复制 Request Headers 里的整行 Cookie → 粘进终端（无回显）→ 回车。工具解析后写入 SQLite，并立刻校验登录态（识别不到会明确告知，而不是假装成功）。

也可以非交互地导入：

```bash
52pj login --cookie "htVC_2132_auth=...; htVC_2132_saltkey=..."
```

## 浏览器传输模式（-b）

在 Minis App（Android）里，可以不导 cookie，直接借用 App 内已登录的 WebView 发请求：

```bash
52pj -b threads -f 10
52pj -b whoami
52pj whoami -b          # 放在子命令后也行
```

不加 `-b` 就是默认的本地直连（curl_cffi 指纹）。

**两种浏览器后端，可显式指定：**

| 写法 | 后端 | 登录态来自 | 可用环境 |
|---|---|---|---|
| `52pj -b forums` | 自动选 | — | 通用 |
| `52pj --webview forums`（`-W`） | Minis App 内的 WebView | App 的 cookie（HttpOnly） | App / 沙箱内 |
| `52pj --local forums`（`-L`） | 本机默认浏览器（Playwright 驱动） | 本机浏览器 profile | 桌面宿主 |

自动选：有 `minis-browser-use` 通道就用 App 的 WebView，否则用本机浏览器。
强制指定后若当前环境不具备该条件，会直接报错说明原因，不会静默换用别的后端。

原理与边界：

- 请求交给 App 的浏览器执行（同源 `fetch`），**登录态直接生效**——`htVC_2132_auth` 是 HttpOnly，本地进程读不到，借道浏览器是唯一不需要复制 cookie 的路子；
- 需要 App 处于前台：后台标签会被 WebView 冻结（`fetch` 与定时器一起挂起），传输层会自己开一个前台标签；
- 正文按原始字节取回再本地解码，站点是 GBK 也不会乱码；
- 跨域请求（360/Bing 搜索）同源策略挡不住，自动回退到 curl 指纹会话，此时按游客态处理；
- App 未登录时行为与游客一致（只能看第 1 页、看不到私密版块）。

### 桌面端（Windows / macOS / Linux）

没有 Minis App 的 WebView 可借时，`-b` 自动改用**本机浏览器**：Playwright 驱动
Chrome / Edge / Brave / Firefox（系统默认浏览器优先），在页内执行同一段 fetch 脚本，
登录态由浏览器自己的 profile 携带。

```bash
52pj auth                      # 打开本机浏览器人工登录（含人机验证）
52pj -b threads -f 10          # 复用同一 profile 的登录态
```

- `auth` 与 `-b` 共用 `~/.52pj/browser-profile`，登录一次长期有效；
- 浏览器选择顺序：系统默认浏览器 → Chrome → Edge → Brave → Firefox；
- **用系统已安装的浏览器**（读注册表 UserChoice 的 ProgId，再顺着
  `HKCR\<ProgId>\shell\open\command` 找到真实 exe），不下载浏览器、不需要
  chromedriver，也不往代码目录里写任何东西；
- 跨域请求（搜索引擎）仍回退到 curl 指纹会话。

> **为什么不用 Selenium**：Selenium 需要 chromedriver，且驱动大版本必须与浏览器
> 一致；Selenium Manager 要联网去 `googlechromelabs.github.io` 抓版本，国内基本
> 连不上，失败后还会把驱动下载到当前工作目录，污染代码仓库。Playwright 直接用
> `executable_path` 指向已装的浏览器，绕开了这一整条链路。

> **验证状态**：该路径的逻辑（探测、profile 复用、回执解析、跨域回退）有单元测试覆盖
> （`tests/test_browser_local.py`，14 项全过），且**已在真实 Windows 桌面环境跑通端到端**——
> `-b whoami` / `-b forums` / `-b threads` 均正常，`auth` 人工登录后 cookie 能被 `-b` 复用。

## 已知限制

- **站内搜索已被站点废弃**：`search.php` 一律 302 到 Bing，且 Bing 对本站几乎无索引，所以 `search` 改走 360/Bing 外链解析。找具体帖子首选 `threads --grep` / `latest --grep` 本地过滤。
- **登录是 Cloudflare Turnstile**：无法纯脚本过验证，所以设计成 `auth` 打开浏览器由你手动登录、工具回收 cookie。也支持 `login --cookie "..."` 直接导入。
- **游客态的能力边界**：非私密帖的第 1 页可读；第 2 页起标题与楼层都会缺失（页面返回的是登录提示页）；私密版块直接被拦。登录后这些都正常。
- **纯只读**：没有发帖/回帖命令，从源码层面就不存在。

## 数据位置

- 全部状态在 SQLite：`%USERPROFILE%\.52pj\52pj.db`（可用 `--home` 改）
- 表：`meta`（UA/指纹）、`cookies`、`selection`（当前板块/帖子）、`lists`（序号→ID）、`history`、`cache`
- 板块列表缓存 **一天**，`forums --refresh` 强刷；cookie 长期有效，`logout` 只删 cookie

## 环境变量

| 变量 | 作用 |
|---|---|
| `52PJ_ENCODING` | 强制输出编码：`utf-8` / `native` / `gbk`（默认自动适配） |

| 变量 | 作用 |
|---|---|
| `52PJ_ENCODING` | 强制输出编码：`utf-8` / `native` / `gbk`（默认自动适配） |
| `NO_COLOR` | 存在即关闭彩色输出 |
| `POJIE_COLOR` | 设为 `1` / `true` / `yes` / `on` 开启彩色输出 |
| `POJIE_IMPERSONATE` | curl_cffi  impersonate profile，默认 `chrome` |
| `POJIE_52_ACCOUNT` | 账号（`login -u` 省略时读取） |
| `POJIE_52_PASSWD` | 密码（`login -p` 省略时读取） |

账号密码读取顺序：进程环境 → Windows 用户级注册表 → 交互输入。
