# Linux / systemd 部署

Windows 那边靠计划任务 `ASOUL_Heartbeat_Manage` 调 `run_manage.bat`；
Linux 这边等价物是 **`asoul-heartbeat.service`（oneshot）+ `asoul-heartbeat.timer`（每 5 分钟）**。

## 安装

```bash
# 先把项目放好（目录里有 .cookies.json，权限 600）
sudo bash deploy/install.sh /projects/bilibili_helper
```

不带参数就用默认目录 `/projects/bilibili_helper`。装完手动跑一轮看看：

```bash
systemctl start asoul-heartbeat.service
tail -30 /projects/bilibili_helper/logs/manage.log
```

## 开关

| 操作 | 命令 |
|------|------|
| 开启（启用定时器 + 立即生效） | `systemctl enable --now asoul-heartbeat.timer` |
| 关闭 | `systemctl disable --now asoul-heartbeat.timer` |
| 只跑一次，不改开关 | `systemctl start asoul-heartbeat.service` |
| 看排期 | `systemctl list-timers asoul-heartbeat.timer` |
| 看日志 | `tail -f /projects/bilibili_helper/logs/manage.log` |

`asoul_ctl.py`（`status` / `start` / `stop` / `run`）是 **Windows 专用的**，它调的是 `schtasks`，
在 Linux 上不可用——用上面的 systemctl 代替。

## 两个必须知道的坑

**1. `KillMode=process` 不能删。** manage 用 `Popen` 起挂机 / 点赞子进程，并让它们活过
manage 自身退出（挂机要到下播、点赞要到点满）。systemd 默认的 `KillMode=control-group`
会在 oneshot 结束时把整个 cgroup 的子进程一起收掉——表现是"挂机刚起来就没了"，
而 `manage.log` 里那几行看起来完全正常。

**2. `heartbeat.py --check-only --json` 的 stdout 是数据通道。**
manage 靠它的 stdout 判断谁在播（`json.loads`）。任何时候都不要给这个 stdout 加
时间戳前缀之类的包装，否则解析失败 → 在播名单恒为空 → **挂机永远不会被拉起来**，
日志表面却只像"没人开播"。入口脚本用 `log_stamp.install(stdout=False)` 来避开它。

## 为什么不加别的依赖

定时、归档都由 Python 标准库完成（归档见 `scripts/log_rotate.py`），
不依赖 logrotate / cron。这样同一套代码在 Windows 计划任务下也能原样跑。
