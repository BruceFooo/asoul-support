<p align="center">
  <img src="assets/asoul-logo.png" width="120" alt="A-SOUL Logo" />
</p>

<h1 align="center">A-SOUL Support</h1>

<p align="center">
  <strong>A-SOUL 粉丝全自动应援工具</strong> — 开播自动挂机涨亲密度 + 点亮粉丝牌 + 视频/动态点赞
</p>

<p align="center">
  <a href="https://clawhub.ai/skills/asoul-support">🦞 ClawHub</a> ·
  <a href="https://github.com/XiaoYiWeio/asoul-support">📦 GitHub</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-4.1.1-blue" alt="version" />
  <img src="https://img.shields.io/badge/python-3.9+-green" alt="python" />
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="license" />
</p>

---

## 🚀 一句话安装

复制下面这句话，发给你的 AI 助手（支持任意 agent 框架），它会帮你搞定一切：

```
帮我安装这个项目并设置 A-SOUL 自动挂机：https://github.com/XiaoYiWeio/asoul-support
```

---

## ✨ 它能做什么？

| 功能 | 使用条件 | 说明 |
|------|----------|------|
| 💓 **心跳挂机涨亲密度** | 需要开播 | X25Kn E/X 协议；结束后记录亲密度前后值和实际增量 |
| 🎉 **开播问候** | 需要开播 | 分享直播间 + 发一条问候弹幕（内容可配置） |
| 👍 **直播间点赞** | 需要开播 | 点满配置的次数后停止，随机间隔模拟手动点击 |
| 🌙 **下播点亮** | 下播后 | 过了 `night_light.after_hour`（默认 1 点），若没在播则分享 + 连发 10 条弹幕，每晚一次 |
| 🏅 **粉丝牌手动点亮** | 需要开播 | `checkin.py --live-only`：发 10 条弹幕，保持 3 天可见 |
| 🪙 **自动投币** | 无 | 给成员视频投币（1 币 = 10 亲密度），需用户明确开启 |
| 👍 **视频自动点赞** | 无 | 自动给成员新视频点赞（默认每周执行，避免风控） |
| 💬 **动态自动点赞** | 无 | 自动给成员新动态点赞（默认关闭，需手动开启） |

> B站亲密度规则：观看直播每分钟少量结算（具体数值由 B 站后端控制）；投币 1 币 = 10 亲密度。粉丝牌点亮（10 条弹幕）只维持牌子可见，不直接计入亲密度；直播间点赞只加热度，**不涨亲密度**。

---

## 📝 更新日志

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| **v4.2** | 2026-10-01 | 按事件重构调度：开播问候（分享 + 1 条弹幕）、开播点赞（点满停）、下播点亮（分享 + 10 条弹幕，每晚一次）；弹幕/点赞/分享全部可在配置里调 |
| **v4.1.1** | 2026-07-27 | 修复 X25Kn 心跳时间漂移和失败链恢复；新增亲密度增量记录与登录预检；GitHub Actions 升级到 Node 24 运行时 |
| **v4.1** | 2026-05-28 | 心跳协议升级为 **X25Kn E/X**（HMAC 链式签名），替代已失效的 `mobileHeartBeat`；自动获取 LIVE_BUVID；GitHub Action 频率降低以减少风控 |
| v4 | 2026-04-01 | （已废弃）`mobileHeartBeat` 协议——B 站后端已停止为该协议结算亲密度 |
| v3 | 2026-03-23 | 新增开播检测 + 心跳挂机 + Discord 通知 |
| v2 | 2026-03-20 | 粉丝牌点亮（10 条弹幕，3 天有效期） |
| v1 | 2026-03 | 视频点赞 + 动态点赞 + GitHub Actions |

---

## 🔬 技术方案

| 项目 | 说明 |
|------|------|
| **心跳协议** | B 站 Web `X25Kn`（`/x25Kn/E` 进入 → `/x25Kn/X` 心跳，每次响应递推 `secret_key/secret_rule/timestamp`） |
| **签名算法** | HMAC 链式签名（rule 索引 0~5 → HMAC-MD5 / SHA1 / SHA256 / SHA224 / SHA512 / SHA384），`secret_key` 作 HMAC key |
| **设备指纹** | 优先使用 `.cookies.json` 中的浏览器 `LIVE_BUVID`；缺失时以 SPI `b_3` 作为兼容回退 |
| **实现语言** | 纯 Python 3.9+，标准库 `hashlib` + `hmac` |
| **外部依赖** | 无（不需要 Node.js / pm2 / Docker / wasm 服务） |
| **运行方式** | 命令行直接执行 或 任意 agent 框架调度 |

## 🔒 安全说明

- Cookie **加密存储**在本地（权限 600）或 GitHub Secrets 中，所有代码**完全开源**
- 只做点赞和弹幕操作，**不会自动投币**（需用户明确开启），不送礼、不关注陌生人
- GitHub Actions 对公开仓库完全免费

---

## 💌 一个魂寄语

做这个工具不是为了让大家不看直播，是因为我自己工作太忙经常错过开播，才写了这个在忙的时候帮我守着。**有时间的话还是去直播间看直播吧**，跟大家一起刷弹幕互动的快乐是工具给不了的。

如果你也关注其他主播，只需要替换脚本里对应的主播 UID 和房间号就可以用。不过……记得先关注[**嘉然今天吃什么**](https://space.bilibili.com/672328094/)哦～

<p align="center">
  <img src="assets/diana-heart.png" width="100" alt="嘉然比心" />
</p>

如果这个项目帮到了你，**请给个 Star ⭐！** 这对我真的很重要，能让更多魂们发现这个工具。也欢迎 **Fork** 到自己账号使用，遇到问题或有好的想法随时提 **Issue**，我都会看。

希望能帮到跟我一样忙碌但心里还惦记着 A-SOUL 的魂们。

---

## 📖 使用教程

### 🤖 OpenClaw / Hermes / QClaw 等 Agent 助手用户

直接把下面这句话发给你的 AI 助手，它会帮你搞定安装、配置和定时任务：

```
帮我安装这个项目并设置 A-SOUL 自动挂机：https://github.com/XiaoYiWeio/asoul-support
```

安装完成后，再告诉它：

```
帮我设置一个定时任务，每 30 分钟检测 A-SOUL 成员是否在直播，在播就帮我挂机涨亲密度并点亮粉丝牌
```

> 支持所有兼容 Python 的 agent 框架，助手会自动处理代码克隆、Cookie 配置和定时调度。

---

<details>
<summary>🐍 纯命令行用户（不使用 Agent 助手，点击展开）</summary>

**环境要求：** Python 3.9+

**第 1 步：获取代码**

```bash
git clone https://github.com/XiaoYiWeio/asoul-support.git
cd asoul-support
```

**第 2 步：配置 Cookie**

```bash
python3 scripts/checkin.py --save-cookie --sessdata "你的SESSDATA" --bili-jct "你的bili_jct"
```

如何获取 B站 Cookie：Chrome 打开 [bilibili.com](https://www.bilibili.com)（确保已登录）→ 按 **F12** → **Application** → **Cookies** → **https://www.bilibili.com**，找到 **SESSDATA** 和 **bili_jct** 复制即可。

> ⚠️ 相当于登录凭证，不要分享。约 6 个月后过期。

**第 3 步：运行**

```bash
# 检测谁在播 + 自动挂机涨亲密度
python3 scripts/heartbeat.py

# 挂机到下播为止（开播时会自动分享 + 发一条问候弹幕）
python3 scripts/heartbeat.py --until-offline

# 给正在直播的房间点赞
python3 scripts/like_room.py

# 发 10 条弹幕点亮粉丝牌
python3 scripts/checkin.py --live-only
```

**第 4 步：设置定时任务（cron）**

```bash
# crontab -e
*/30 * * * * cd /path/to/asoul-support && python3 scripts/heartbeat.py --until-offline
```

</details>

---

## 🔧 GitHub Actions 自动点赞（不需要 OpenClaw）

只需要视频/动态点赞（不涨亲密度）的话，Fork 本仓库 + 配置 Cookie 即可。

<details>
<summary>📋 设置教程（点击展开）</summary>

1. 点击右上角 **Fork** → **Create fork**
2. **Settings** → **Secrets and variables** → **Actions** → 添加 `SESSDATA` 和 `BILI_JCT`
3. **Actions** 标签 → 点击 **I understand my workflows, go ahead and enable them**
4. 验证：**Actions** → **A-SOUL 自动应援** → **Run workflow**

之后每周自动执行（默认周一、周四，可在 `daily.yml` 调整）。动态点赞需编辑 `daily.yml` 将 `ENABLE_DYNAMIC_LIKE` 改为 `'true'`。

> ⚠️ 频率别调太高：B 站会对跨地区高频自动化触发风控、频繁刷新你的 Cookie。每周 1~2 次是相对安全的节奏。如果你的 Cookie 经常一两天就失效，建议用一个不在浏览器/手机日常登录的小号专门做自动化。

</details>

---

## 🌟 默认成员（写在 `.asoul_config.json` 里）

| 成员 | 直播间 | 主页 |
|------|--------|------|
| 嘉然 | [22637261](https://live.bilibili.com/22637261) | [space](https://space.bilibili.com/672328094) |
| 贝拉 | [22632424](https://live.bilibili.com/22632424) | [space](https://space.bilibili.com/672353429) |
| 乃琳 | [22625027](https://live.bilibili.com/22625027) | [space](https://space.bilibili.com/672342685) |
| 心宜 | [30849777](https://live.bilibili.com/30849777) | [space](https://space.bilibili.com/3537115310721181) |
| 思诺 | [30858592](https://live.bilibili.com/30858592) | [space](https://space.bilibili.com/3537115310721781) |

这 5 人只是**默认配置**，不是代码里写死的。想换主播：直接改 `.asoul_config.json`
的 `members` 数组即可，`scripts/` 下所有脚本自动跟着变，无需碰任何 Python 文件。

## ❓ 常见问题

**Q: Cookie 过期了怎么办？** — 重新获取，重跑 `--save-cookie` 命令更新即可。GitHub Actions 失败时会发邮件通知。

**Q: 需要电脑一直开着吗？** — 用服务器/NAS 跑脚本，或用 GitHub Actions（视频/动态点赞部分），都不需要盯着。

**Q: 投币会消耗硬币吗？** — 默认不投币。需要手动开启 `--coin` 参数才会投。

**Q: 需要 Node.js 吗？** — 不需要。v4.0 纯 Python，只需 Python 3.9+。

---

## 🛠 手动命令参考

```bash
# 检测谁在播
python3 scripts/heartbeat.py --check-only

# 挂机指定成员 25 分钟
python3 scripts/heartbeat.py --members 嘉然,贝拉

# 挂机直到下播
python3 scripts/heartbeat.py --until-offline

# 给正在直播的房间点赞（点满配置的次数后停止）
python3 scripts/like_room.py
python3 scripts/like_room.py --dry-run      # 只看今晚进度，不发请求

# 下播后分享 + 连发弹幕（每晚一次；在直播则跳过）
python3 scripts/night_light.py

# 手动发 10 条弹幕点亮粉丝牌
python3 scripts/checkin.py --live-only

# 给最近视频投币+收藏
python3 scripts/videos.py --days 7 --coin --fav
```

## ⚙️ 本机配置（Windows 计划任务版）

本仓库已针对 Windows + 计划任务做过适配，相关文件：

| 文件 | 作用 |
|------|------|
| `.asoul_config.json` | **唯一的数据源**：`members` + `active_hours` + 行为设置 `danmaku` / `like` / `share` / `night_light`（含各自开关）。已纳入 git（内容不含任何密钥） |
| `scripts/asoul_members.py` | 读取并校验上面这个配置的共享模块 |
| `scripts/live_api.py` | 所有直播接口（弹幕 / 点赞 / 分享 / 直播状态）的唯一实现 |
| `scripts/wbi.py` | 点赞接口要用的 WBI 签名 |
| `scripts/like_room.py` | 点赞进程：点满即停 |
| `scripts/night_light.py` | 下播点亮：分享 + 连发弹幕，每晚一次 |
| `run_manage.bat` | 无窗口运行器，由计划任务每 5 分钟调用 |
| `asoul_ctl.py` | 开关 / 状态控制台 |
| `.state/locks/` | 挂机进程锁（运行时生成，已 gitignore） |
| `.state/like_locks/` | 点赞进程锁（运行时生成，已 gitignore） |
| `.state/likes/` | 点赞进度，按天存（运行时生成，已 gitignore） |
| `.state/night_light/` | 下播点亮进度，按天存（运行时生成，已 gitignore） |
| `.state/greetings/` | 开播问候记录，按天存，防止进程重启后重复问候（运行时生成，已 gitignore） |
| `.state/buvid3.txt` | 设备指纹 cookie，自动获取并复用（运行时生成，已 gitignore） |
| `logs/` | 运行日志（已 gitignore） |

### 配置示例

> ⚠️ `.asoul_config.json` 必须是**纯 JSON**，写不了注释（编辑器会标红，其他工具也读不了）。
> 下面这份带注释的仅作说明用，**注释不要抄进配置文件**。

```jsonc
{
  // 要盯的主播。加主播 = 加一条。uid 是空间号(space.bilibili.com/<uid>)，
  // room 是直播间号(live.bilibili.com/<room>)，两者不相等，别填混。
  // room 填地址栏那个短号即可，脚本会自动解析成真实房间号（281 → 49728）。
  "members": [
    { "name": "嘉然", "uid": 672328094, "room": 22637261 },
    { "name": "贝拉", "uid": 672353429, "room": 22632424 }
  ],

  // 活跃时段，支持跨零点。19 → 4 即 19:00-03:59 挂机，其余时间睡眠。
  // 时段内做「挂机 + 点赞」。start == end 表示全天挂机。整段可省略 = 全天。
  "active_hours": { "start": 19, "end": 4 },

  // 弹幕。false = 一条都不发（开播问候、下播点亮都变成只分享）
  "danmaku": {
    "enabled": true,
    "on_live": ["晚好"],              // 开播问候，多条则随机取一条
    "after_offline": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],  // 点亮时按序发
    "interval": { "min": 3, "max": 12 }   // 相邻两条之间随机等待的秒数
  },

  // 点赞。false = 完全不起点赞进程。target 是每晚目标次数，点满即停
  "like": {
    "enabled": true,
    "target": 500,
    "batch": 10,                      // 每次请求汇总上报几次点击，实测 50 以内都接受
    "interval": { "min": 1.0, "max": 3.0 }
  },

  // 分享直播间，两个时机各一个开关
  "share": { "on_live": true, "after_offline": true },

  // 下播点亮。false = 整段不做。只想去掉弹幕、保留分享 → 用上面的 danmaku.enabled
  "night_light": {
    "enabled": true,
    "after_hour": 1      // 几点之后开始查。与 active_hours 解耦：挂机 19→4 时
                         // 1 点一到就查，不必等挂机时段整个结束（4 点）才做
  }
}
```

四段都可以整段省略，用内置默认值；三个 `enabled` 缺省都是 `true`，`after_hour` 缺省 `1`。
配置文件**缺失或格式非法直接报错退出**，不会静默回退到内置名单。

所有开关的状态每轮巡检都会写进日志（`配置中已关闭：弹幕、点赞`），
所以"开了没反应"时先看日志，不用怀疑程序坏了。

> ⚠️ 弹幕有频率限制，实测阈值在 1~3 秒之间：间隔 3 秒能过、1 秒就返回
> `10030 频率过快`。默认 `min: 3` 没有余量，觉得不稳就调到 4。
> 另外**被限流时返回体里照样带 `send_from_me: true` 和弹幕内容**，判成功只能看 `code`。

> ⚠️ 点赞成功时返回的 `data` 是空的，**服务端不回报实际计入几次**。所以
> 「点满 500」只代表发够了这么多请求；触顶或风控时接口返回非 0，脚本据此停止。

### 开关与状态

```bash
python asoul_ctl.py status   # 任务是否启用 / 当前是否活跃时段 / 后台进程 / 今晚点赞进度
python asoul_ctl.py start    # 开启：启用计划任务 + 立即检测一次
python asoul_ctl.py stop     # 关闭：禁用任务 + 终止正在跑的后台进程
python asoul_ctl.py run      # 只立即检测一次，不改开关
python asoul_ctl.py run --ignore-window   # 忽略时段限制强制跑一次
```

### 后台进程是怎么跑的

计划任务 `ASOUL_Heartbeat_Manage` 每 5 分钟执行一次 `run_manage.bat` → `pythonw.exe manage_asoul_heartbeat.py`。
管理脚本本身**不会常驻**，它只负责按事件拉起 / 放下别的进程：

1. 检查 `.cookies.json` 在不在，读配置、判断是否在活跃时段；
2. **时段外（睡眠）**：停掉仍在跑的挂机与点赞进程，跑一次 `night_light.py`
   （它先看今晚是否所有房间都已有结论，是就直接返回、连状态接口都不打）；
3. **时段内**：清理已不在配置里的孤儿进程 → `heartbeat.py --check-only --json` 查谁在播
   → 对**在播**成员各拉起两个独立进程，PID 写进锁文件、输出重定向到日志：

   | 进程 | 锁 | 日志 |
   |------|-----|------|
   | `heartbeat.py --until-offline --members <成员>` | `.state/locks/<房间号>.lock` | `logs/heartbeat_<成员>_<时间戳>.log` |
   | `like_room.py --members <成员>` | `.state/like_locks/<房间号>.lock` | `logs/like_<成员>_<时间戳>.log` |

   已点满的房间不会重复拉起点赞进程；**没在播**的成员则两个进程都杀掉并删锁；
4. **过了 `night_light.after_hour`**，不管在不在时段内都再查一次下播点亮——
   挂了机也照查，只要有成员没在播。全员还在播就跳过，不起子进程。

这些后台进程**独立于计划任务存活**（挂机到下播、点赞到点满），所以每 5 分钟是**巡检频率**而不是执行间隔。锁文件防重复启动，`MultipleInstancesPolicy=IgnoreNew` 防任务自身叠加。

#### 三个事件分别做什么

| 事件 | 触发时机 | 动作 |
|------|----------|------|
| **开播问候** | `heartbeat.py` 确认开播时 | 分享（`share.on_live`）+ 发一条 `danmaku.on_live` |
| **开播点赞** | `manage` 拉起 `like_room.py` | 随机间隔点赞，点满 `like.target` 即停；返回非 0（触顶/风控）也停 |
| **下播点亮** | `night_light.after_hour` 之后房间**没在播**时 | 分享（`share.after_offline`）+ 按序发 `danmaku.after_offline` |

下播点亮与挂机时段**互不影响**：`after_hour` 一到就开始查，挂机继续跑到时段结束。
在直播的房间永远跳过，这条 `--force` 也不破例。

后两个都是**每晚一次**的语义，进度按天存盘（`.state/night_light/`、`.state/greetings/`），
中途被杀会接着做而不是从头再来。问候之所以也要存盘：挂机进程崩了会被重新拉起，
而那时主播往往**还在播**，没有记录就会每次重启都重发一遍。

> ⚠️ **点赞必须带 `buvid3`（设备指纹 cookie）**，否则一律被风控拦下、返回 `-352`。
> `.cookies.json` 里通常只有 `SESSDATA` 和 `bili_jct`，所以脚本会自己去 B 站公开的
> `x/frontend/finger/spi` 取一个，缓存到 `.state/buvid3.txt` 跨进程复用（每次换新的
> 反而更像异常客户端）。取不到只是不带这个 cookie，不影响其他功能。

> ℹ️ 实测**未开播的直播间也能发弹幕、也能分享**，所以下播点亮在离线房间能正常工作。

> ⚠️ 本任务 `LogonType=Interactive`：**只在当前用户登录状态下运行**，注销后不再触发。

## License

MIT
