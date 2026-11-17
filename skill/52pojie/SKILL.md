---
name: 52pojie
description: 用 52pojie 命令行读取 52pojie.cn（吾爱破解）论坛内容——列版块、列帖子、读帖子正文与楼层、站内搜索、登录后看私密版块。当用户要查吾爱破解/52pojie 的帖子、版块列表、某主题的回复内容，或需要以命令行走论坛时使用。
---

# 52pojie —— 52pojie.cn 命令行阅读器

只读浏览 52pojie.cn 的命令行工具。仓库：`github.com/itingyu/52pojie`。

## 安装

```bash
git clone https://github.com/itingyu/52pojie.git
cd 52pojie
pip install -e .
52pojie setup          # 装 curl_cffi、beautifulsoup4
```

`curl_cffi` 是硬依赖，缺了直接退出——所有请求都走它的 Chrome TLS 指纹，不提供 requests 降级。

## 基本用法

```bash
52pojie forums                      # 列出版块（序号 + FID + 名称）
52pojie threads -f 24               # 列某版块的帖子
52pojie thread 2138234              # 读某帖（默认第 1 页）
52pojie thread 2138234 --page 3     # 读第 3 页回复
52pojie search "关键词"              # 搜索（走 360/Bing，索引不全）
```

`threads` 的 `-f` 是版块 FID，可用 `52pojie forums` 查。`--page` 对 `threads` 和 `thread` 都适用。

## 上下文（省 token）

```bash
52pojie select 24      # 记住当前版块，之后 52pojie threads 不用带 -f
52pojie select 10      # 记住某帖，之后 52pojie thread 不用带 TID
52pojie status         # 看当前选中了什么
```

`select` 的参数既可以是版块序号也可以是帖子 TID（按当前模式区分），`status` 会打印等价命令。

## 登录

游客态只能看第 1 页、看不到私密版块。两种登录方式：

```bash
52pojie auth                        # 打开浏览器人工登录（含人机验证），cookie 存本地库
52pojie login -u 用户名 -p 密码       # 直接登录，站点要求 Turnstile 时会失败
52pojie login --cookie "htVC_2132_auth=...; htVC_2132_saltkey=..."   # 贴已有 cookie
52pojie whoami                      # 查登录状态
52pojie logout                      # 清掉本地 cookie
```

cookie 存在 `~/.52pojie/pojie.db`（SQLite，明文）。

## 浏览器传输层（`-b`）

`-b` 让请求借道浏览器发出，用浏览器自带的登录态：

```bash
52pojie -b threads -f 10            # 子命令前后都行
```

- Android（Minis App 内）：借 App 里已登录的 WebView，App 的 HttpOnly cookie 自动带上
- 桌面端：Selenium 驱动本机浏览器（Chrome/Edge/Brave/Firefox），`52pojie setup --with-selenium` 装依赖，`52pojie auth` 登录一次即可复用

不加 `-b` 就是默认的本地直连（curl 指纹，只带本地 cookie 库里的 cookie）。

## 全局开关

| 开关 | 作用 |
|---|---|
| `--json` | 输出 JSON，便于程序处理 |
| `-b` / `--browser` | 借道浏览器发请求 |
| `--home DIR` | 换配置目录（默认 `~/.52pojie`） |
| `--width N` | 排版宽度，默认取终端宽度 |
| `--delay 1.0` | 请求间隔基准值，实际是基准 ± 抖动 |
| `--cookie-file FILE` | 换 cookie 库文件 |
| `--no-color` | 关颜色 |

## JSON 输出

```bash
52pojie --json forums      # [{"fid": 2, "name": "原创发布区"}, ...]
52pojie --json threads -f 24
52pojie --json thread 2138234    # {"tid":..., "title":..., "posts":[{pid,author,floor,time,content}]}
```

## 排版

表格列宽受终端宽度约束，超长标题会截断加 `…`；`--width` 可手动指定。窄终端（50 列）下表格会收窄但不会折行。

## 限制

- 只读：不能发帖、回帖、点赞
- 游客态看不到私密版块和第 2 页之后的内容
- 搜索依赖第三方引擎，站内索引不全，搜不到就翻版块列表
- 站点是 GBK 编码，内容已正确解码，直接读输出即可
