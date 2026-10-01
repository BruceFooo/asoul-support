---
name: asoul-support
description: "A-SOUL 粉丝应援工具 — 检测开播自动点亮粉丝牌+移动端心跳挂机涨亲密度、视频点赞/投币/收藏、动态点赞。纯Python实现，零外部依赖。触发词：A-SOUL、asoul、签到、点赞、三连、应援、动态、点亮、粉丝牌、心跳、挂机、直播、嘉然、贝拉、乃琳、心宜、思诺。"
---

# A-SOUL Support

A-SOUL 粉丝自动应援工具 — 开播检测 + 粉丝牌点亮 + 移动端心跳挂机涨亲密度 + 视频/动态互动。

纯 Python 实现，零外部依赖（不需要 Node.js 签名服务）。

## 触发规则

| 模式 | 示例 |
|------|------|
| 包含 `A-SOUL` / `asoul` + `签到` / `点亮` | "帮我给asoul签到" |
| 包含 `A-SOUL` / `asoul` + `心跳` / `挂机` | "给asoul直播间挂机" |
| 包含 `A-SOUL` / `asoul` + `点赞` / `三连` | "给asoul视频点赞" |
| 包含 `A-SOUL` / `asoul` + `动态` | "给asoul动态点赞" |
| 包含成员名 + `签到` / `点赞` / `挂机` | "给嘉然签到" |
| 包含 `应援` | "A-SOUL每日应援" |

## 默认成员（来自 `.asoul_config.json`）

| 成员 | UID | 直播间 |
|------|-----|--------|
| 嘉然 | 672328094 | 22637261 |
| 贝拉 | 672353429 | 22632424 |
| 乃琳 | 672342685 | 22625027 |
| 心宜 | 3537115310721181 | 30849777 |
| 思诺 | 3537115310721781 | 30858592 |

上表只是项目自带配置的默认内容。成员表的唯一数据源是项目根的 `.asoul_config.json`，
所有脚本通过 `scripts/asoul_members.py` 读取；增删成员只改该文件，配置缺失即报错退出。

## 功能 1 — 心跳挂机（涨亲密度，需开播）

使用 X25Kn E/X 心跳协议（HMAC 链式签名），纯 Python，零外部依赖。

检测成员是否在播 → 自动佩戴粉丝牌 → 分享直播间 + 发一条问候弹幕 → 心跳挂机涨亲密度。

```bash
python3 {baseDir}/scripts/heartbeat.py
python3 {baseDir}/scripts/heartbeat.py --members 嘉然,贝拉
python3 {baseDir}/scripts/heartbeat.py --check-only
python3 {baseDir}/scripts/heartbeat.py --duration 30
python3 {baseDir}/scripts/heartbeat.py --until-offline
```

## 功能 2 — 开播问候 / 点赞 / 下播点亮

三个动作的内容与开关都写在本项目根目录的 `.asoul_config.json` 里
（`danmaku` / `like` / `share` 三段，全部可选，缺省用内置默认值）。
开播/下播的 Discord 通知另有一段 `notify.enabled`，**缺省关闭**——
通知要调外部的 `openclaw` CLI，没装的环境不该白起进程。

| 动作 | 触发 | 说明 |
|------|------|------|
| 开播问候 | 确认开播时（由 `heartbeat.py` 做） | 分享直播间 + 随机发一条 `danmaku.on_live` |
| 开播点赞 | 开播后（由 `manage_asoul_heartbeat.py` 拉起） | 点满 `like.target` 即停，触到服务端上限也停 |
| 下播点亮 | 活跃时段结束后且**没在播** | 分享 + 按序发 `danmaku.after_offline`，随机间隔，每晚一次 |

```bash
python3 {baseDir}/scripts/like_room.py
python3 {baseDir}/scripts/like_room.py --dry-run          # 只看今晚进度，不发请求
python3 {baseDir}/scripts/night_light.py                  # 时段内会拒绝，加 --force 可强制
python3 {baseDir}/scripts/night_light.py --members 嘉然
```

**在直播时绝不发下播弹幕**——这条是硬规则，`--force` 也不会绕过。

## 功能 3 — 粉丝牌点亮（需开播）

发 10 条弹幕点亮牌子（保持 3 天可见）。**需要成员正在直播时才能点亮。**

```bash
python3 {baseDir}/scripts/checkin.py --live-only
python3 {baseDir}/scripts/checkin.py --live-only --members 嘉然,贝拉
python3 {baseDir}/scripts/checkin.py --live-only --msg 签到 --msg 加油
```

## 功能 4 — 视频点赞/投币/收藏（不需要开播）

给成员新发布的视频批量互动。默认仅点赞，投币和收藏需明确指定。

```bash
python3 {baseDir}/scripts/videos.py --month 3
python3 {baseDir}/scripts/videos.py --days 7 --coin --fav
python3 {baseDir}/scripts/videos.py --month 3 --members 嘉然 --coin --fav
```

## 功能 5 — 动态点赞（不需要开播）

```bash
python3 {baseDir}/scripts/dynamics.py --month 3
python3 {baseDir}/scripts/dynamics.py --days 7
python3 {baseDir}/scripts/dynamics.py --days 7 --members 嘉然,贝拉
```

## 推荐 OpenClaw 定时任务

### 简单定时任务（推荐用于轻量使用）

```
每 30 分钟检测一次开播，开播了就自动弹幕点亮+挂机涨亲密度：
openclaw cron add --name "A-SOUL开播挂机" --cron "*/30 * * * *" \\
  --message "帮我检测A-SOUL成员是否在直播，在播的话先挂机涨亲密度，再发弹幕点亮牌子" \\
  --timeout-seconds 21600
```

### 高级进程管理定时任务（推荐用于长期稳定运行）

对于需要进程锁定、自动重启和更稳定通知的场景，使用专门的进程管理脚本：

```
每 5 分钟运行一次进程管理：
openclaw cron add --name "A-SOUL进程管理" --cron "*/5 * * * *" \\
  --message "cd /path/to/asoul-support && python3 manage_asoul_heartbeat.py" \\
  --timeout-seconds 300
```

**优势：**
- 进程锁定防止重复启动
- 自动检测已死进程并清理锁文件
- 仅在真正开播/下播时发送 Discord 通知（`notify.enabled=true` 才发，缺省关）
- 详细日志记录到 logs/ 目录
- 自动处理成员状态变化

视频和动态由 GitHub Actions 自动处理（每 2 天），无需额外配置。

## Cookie 设置

与 `bilibili-live-checkin` 共用 Cookie。如果已在那个 skill 设置过，无需重复操作。

手动设置：
```bash
python3 {baseDir}/scripts/checkin.py --save-cookie --sessdata "{SESSDATA}" --bili-jct "{bili_jct}"
```
