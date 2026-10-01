#!/usr/bin/env python3
"""A-SOUL 自动挂机 —— 开关 / 状态控制台。

用法:
  python asoul_ctl.py status     # 查看状态（任务是否启用、哪些挂机进程在跑）
  python asoul_ctl.py start      # 开启自动挂机（启用计划任务并立即检测一次）
  python asoul_ctl.py stop       # 关闭自动挂机（禁用任务 + 终止正在挂机的进程）
  python asoul_ctl.py run        # 只立即检测一次，不改变任务开关
  python asoul_ctl.py run --ignore-window   # 忽略时段限制，强制跑一次
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import manage_asoul_heartbeat as mgr  # noqa: E402
import like_room  # noqa: E402
from asoul_members import ConfigError, load_config  # noqa: E402

TASK_NAME = "ASOUL_Heartbeat_Manage"


def _schtasks(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, check=False)


def task_state() -> str:
    """返回 enabled / disabled / missing。"""
    result = _schtasks("/Query", "/TN", TASK_NAME, "/FO", "LIST")
    if result.returncode != 0:
        return "missing"
    return "disabled" if "Disabled" in result.stdout else "enabled"


def running_processes() -> list:
    """返回 [(房间号, 成员名或 None, pid, 类型), ...]，类型为 "挂机" 或 "点赞"。

    直接扫描锁目录（而不是遍历成员列表），这样已从配置中删除的成员遗留的进程也能被发现。
    """
    try:
        names = {str(m.get("room")): m["name"] for m in load_config()["members"]}
    except ConfigError:
        names = {}

    running = []
    for lock_dir, kind in ((mgr.LOCK_DIR, "挂机"), (mgr.LIKE_LOCK_DIR, "点赞")):
        if not lock_dir.exists():
            continue
        for lock_file in sorted(lock_dir.glob("*.lock")):
            try:
                pid = int(lock_file.read_text().strip())
            except (OSError, ValueError):
                continue
            if mgr._pid_alive(pid):
                room = lock_file.stem
                running.append((room, names.get(room), pid, kind))
    return running


def cmd_status() -> int:
    hour = mgr.current_hour()
    print(f"计划任务 {TASK_NAME}: {task_state()}")
    print(f"当前本地时间: {hour:02d}:00（系统本地时间，非 TZ 环境变量）")

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"配置错误: {exc}")
        return 1

    start, end = config["active_hours"]["start"], config["active_hours"]["end"]
    active = mgr.in_active_window(hour, start, end)
    print(f"活跃时段: {start:02d}:00 - {end:02d}:00  ->  当前{'【活跃】' if active else '【睡眠】'}")
    print(f"监听成员（{len(config['members'])} 人）: "
          f"{', '.join(m['name'] for m in config['members'])}")

    running = running_processes()
    if running:
        print(f"后台进程 {len(running)} 个:")
        for room, name, pid, kind in running:
            print(f"  - [{kind}] {name or '(未在配置中)'}（房间 {room}，PID {pid}）")
    else:
        print("后台进程: 无")

    today = like_room.local_date()
    target = config["settings"]["like"]["target"]
    done, cached = {}, []
    for member in config["members"]:
        room = member.get("room")
        if room is None:
            continue
        clicked = like_room.load_progress(room, today)
        if clicked >= target:
            done.append(member["name"])
        elif clicked:
            cached.append(f"{member['name']} {clicked}/{target}")
    print(f"今晚点赞: 已点满 {len(done)}/{len(config['members'])} 人"
          + (f"（{', '.join(done)}）" if done else "")
          + (f"；进行中 {', '.join(cached)}" if cached else ""))
    return 0


def cmd_start() -> int:
    if task_state() == "missing":
        print(f"ERROR: 计划任务 {TASK_NAME} 不存在，请先创建。")
        return 1
    _schtasks("/Change", "/TN", TASK_NAME, "/ENABLE")
    _schtasks("/Run", "/TN", TASK_NAME)
    print(f"✅ 已开启：任务 {TASK_NAME} 已启用，并立即触发一次检测。")
    print("   （检测结果见 logs/manage.log）")
    return 0


def cmd_stop() -> int:
    if task_state() != "missing":
        _schtasks("/Change", "/TN", TASK_NAME, "/DISABLE")
    stopped = 0
    for lock_dir in (mgr.LOCK_DIR, mgr.LIKE_LOCK_DIR):
        lock_dir.mkdir(parents=True, exist_ok=True)
        stopped += mgr.stop_locked_members(lock_dir, "手动关闭")
    print(f"🛑 已关闭：计划任务已禁用，终止了 {stopped} 个后台进程。")
    return 0


def cmd_run(ignore_window: bool) -> int:
    cmd = [sys.executable, str(ROOT / "manage_asoul_heartbeat.py")]
    if ignore_window:
        cmd.append("--ignore-window")
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="A-SOUL 自动挂机开关控制台")
    parser.add_argument("action", choices=["status", "start", "stop", "run"])
    parser.add_argument("--ignore-window", action="store_true",
                        help="配合 run 使用，忽略活跃时段限制")
    args = parser.parse_args()

    if args.action == "status":
        return cmd_status()
    if args.action == "start":
        return cmd_start()
    if args.action == "stop":
        return cmd_stop()
    return cmd_run(args.ignore_window)


if __name__ == "__main__":
    raise SystemExit(main())
