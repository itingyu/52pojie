---
name: 52pj
description: 用 52pj 命令行读取 52pojie.cn（吾爱破解）论坛内容——列版块、列帖子、读帖子正文与楼层、站内搜索、登录后看私密版块、每日签到。当用户要查吾爱破解/52pojie 的帖子、版块列表、某主题的回复内容、需要以命令行走论坛，或要签到领吾爱币时使用。
---

# 52pj —— 52pojie.cn 命令行阅读器

浏览 52pojie.cn 的命令行工具（以读为主，仅 `sign` 一个签到写操作）。仓库：`github.com/itingyu/52pojie`。

## 安装

```bash
git clone https://github.com/itingyu/52pojie.git
cd 52pj
pip install .
52pj setup          # 一次装齐：curl_cffi / beautifulsoup4 / playwright
```

三个都是硬依赖，缺了直接退出：
`curl_cffi`（所有请求走它的 Chrome TLS 指纹，不提供 requests 降级）、
`beautifulsoup4`（解析）、`playwright`（驱动本机浏览器，`--local` 后端要用）。

国内网络 pip 连不上默认源时换镜像：
`pip install . -i https://pypi.tuna.tsinghua.edu.cn/simple`

## 基本用法

```bash
52pj forums                      # 列出版块（序号 + FID + 名称）
52pj threads -f 24               # 列某版块的帖子
52pj thread 2138234              # 读某帖（默认第 1 页）
52pj thread 2138234 --page 3     # 读第 3 页回复
52pj search "关键词"              # 搜索（走 360/Bing，索引不全）
```

`threads` 的 `-f` 是版块 FID，可用 `52pj forums` 查。`--page` 对 `threads` 和 `thread` 都适用。

## 上下文（省 token）

```bash
52pj select 24      # 记住当前版块，之后 52pj threads 不用带 -f
52pj select 10      # 记住某帖，之后 52pj thread 不用带 TID
52pj status         # 看当前选中了什么
```

`select` 的参数既可以是版块序号也可以是帖子 TID（按当前模式区分），`status` 会打印等价命令。

## 登录

游客态能看第 1 页，第 2 页起内容会缺失（标题和楼层都拿不到），私密版块直接被拦。两种登录方式：

```bash
52pj auth                        # 打开浏览器人工登录（含人机验证），cookie 存本地库
52pj login -u 用户名 -p 密码       # 直接登录，站点要求 Turnstile 时会失败
52pj login --cookie "htVC_2132_auth=...; htVC_2132_saltkey=..."   # 贴已有 cookie
52pj whoami                      # 查登录状态
52pj logout                      # 清掉本地 cookie
```

cookie 存在 `~/.52pj/52pj.db`（SQLite，明文）。

## 浏览器传输层（`-b`）

`-b` 让请求借道浏览器发出，用浏览器自带的登录态：

```bash
52pj -b threads -f 10            # 子命令前后都行
52pj --webview threads -f 10     # 强制用 App 内已登录的 WebView（-W）
52pj --local threads -f 10       # 强制用本机默认浏览器（-L，Playwright 驱动）
```

`-b` 不带后端参数时自动选：有 `minis-browser-use` 通道就用 App 的 WebView，
否则用本机浏览器。`--webview` / `--local` 可显式指定，条件不具备时直接报错。

- Android（Minis App 内）：借 App 里已登录的 WebView，App 的 HttpOnly cookie 自动带上。
  **App 未登录时 `-b` 也是游客态**，跟不加 `-b` 没区别。
- 桌面端：**Playwright** 驱动本机浏览器（Chrome/Edge/Brave/Firefox），`52pj auth` 登录一次即可复用。
- 桌面端默认**无头**（不弹窗），加 `--headed` 才显示窗口；`auth` 始终有头（要人工过验证码）。
- 无头时不改变 UA：会按浏览器主版本重建正常 UA 覆盖，避免暴露 `HeadlessChrome`。
  浏览器取**系统默认浏览器**的真实 exe：读注册表 `UserChoice` 的 ProgId，再顺着 `HKCR\<ProgId>\shell\open\command` 定位——同机装多个 Chrome 时只有走这一层才对。
  不下载浏览器、不需要 chromedriver、不往代码目录写任何驱动文件。
  这条路径已在真实 Windows 桌面环境端到端验证过（`-b whoami` / `-b forums` / `-b threads` 均正常）。

不加 `-b` 就是默认的本地直连（curl 指纹，只带本地 cookie 库里的 cookie）。

## 全局开关

| 开关 | 作用 |
|---|---|
| `--json` | 输出 JSON，便于程序处理 |
| `-b` / `--browser` | 借道浏览器发请求 |
| `--home DIR` | 换配置目录（默认 `~/.52pj`） |
| `--width N` | 排版宽度，默认取终端宽度 |
| `--delay 1.0` | 请求间隔基准值，实际是基准 ± 抖动 |
| `--cookie-file FILE` | 换 cookie 库文件 |
| `--no-color` | 关颜色 |

## JSON 输出

```bash
52pj --json forums      # [{"fid": 2, "name": "原创发布区"}, ...]
52pj --json threads -f 24
52pj --json thread 2138234    # {"tid":..., "title":..., "posts":[{pid,author,floor,time,content}]}
```

## 排版

表格列宽受终端宽度约束，超长标题会截断加 `…`；`--width` 可手动指定。窄终端（50 列）下表格会收窄但不会折行。

## 编码

输出编码自动适配，无需手工设置：

- 重定向到文件/管道 → 纯 UTF-8，**不带 BOM**；
- 交互终端 → 自动把控制台切到 65001（UTF-8），切不动退回系统编码；
- `52PJ_ENCODING=utf-8|native|gbk` 可强制。

## 签到

```bash
52pj sign            # 每日签到，领取论坛币
52pj sign --webview  # 借 App 的 WebView 签到（App 已登录时）
```

**这是本工具唯一的写操作**，其余命令全部只读。
签到入口是积分页上的「领取今日签到奖励」，由服务端按是否已签到决定是否渲染：
未签到 → 页面有 `mod=task&do=apply` 链接，访问即完成；已签到 → 直接告知今天签过。
未登录会直接报错。

## 限制

- 除 `sign` 外全部只读：不能发帖、回帖、点赞
- 游客态：私密版块被拦；非私密帖的第 1 页可读，第 2 页起标题与楼层缺失
- 搜索依赖第三方引擎，站内索引不全，搜不到就翻版块列表
- 站点是 GBK 编码，内容已正确解码，直接读输出即可
