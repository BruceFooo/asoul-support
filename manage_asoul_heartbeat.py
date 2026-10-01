#!/usr/bin/env python3
"""
A-SOUL Support Process Manager
Checks live status and manages heartbeat processes with proper locking.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

# Change to the asoul-support directory
asoul_support_dir = Path(__file__).parent.resolve()
os.chdir(asoul_support_dir)

# 共享配置模块在 scripts/ 下（与 check_auth.py 同级），项目根不在默认搜索路径里
sys.path.insert(0, str(asoul_support_dir / "scripts"))
from asoul_members import ConfigError, load_config, load_members  # noqa: E402
from local_time import in_active_window, local_hour  # noqa: E402
import like_room  # noqa: E402
from night_light import night_light_due  # noqa: E402


def current_hour() -> int:
    """取系统本地时间的小时（0-23）。实现见 local_time（避开 Git Bash 的 TZ=UTC）。"""
    return local_hour()


def _stop_lock(lock_file: Path, reason: str) -> bool:
    """终止一个锁文件对应的挂机进程并删除锁。返回是否真的杀到了进程。"""
    pid_str = lock_file.read_text().strip()
    killed = bool(pid_str) and _pid_alive(int(pid_str))
    if killed:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", pid_str, "/T", "/F"],
                           capture_output=True, check=False)
        else:
            try:
                os.kill(int(pid_str), signal.SIGTERM)
            except OSError:
                pass
        print(f"  房间 {lock_file.stem}: {reason}，已终止挂机进程 {pid_str}")
    lock_file.unlink(missing_ok=True)
    return killed


def stop_locked_members(lock_dir: Path, reason: str,
                        keep_rooms: Optional[set] = None) -> int:
    """终止锁目录下的挂机进程并清理锁文件。

    直接扫描锁目录而不是遍历成员列表——这样即使某成员已被从配置中删除，
    它遗留的挂机进程也能被正确终止。

    keep_rooms=None（默认）：全部终止，用于离开活跃时段 / 手动关闭。
    keep_rooms 给定时：只终止房间号不在其中的锁，用于“配置里已经没有这个成员了”。
    """
    if not lock_dir.exists():
        return 0

    stopped = 0
    for lock_file in sorted(lock_dir.glob("*.lock")):
        if keep_rooms is not None and lock_file.stem in keep_rooms:
            continue
        try:
            if _stop_lock(lock_file, reason):
                stopped += 1
        except (OSError, ValueError) as exc:
            print(f"  {lock_file.name}: 终止挂机时出错 {type(exc).__name__}: {exc}")
            lock_file.unlink(missing_ok=True)
    return stopped

def _live_pid(lock_file: Path) -> Optional[int]:
    """锁里记录的 PID，且该进程确实还在跑；否则返回 None 并清掉这个无效的锁。"""
    if not lock_file.exists():
        return None
    try:
        pid_str = lock_file.read_text().strip()
        pid = int(pid_str)
        if pid_str and _pid_alive(pid):
            return pid
        print(f"  房间 {lock_file.stem}: 锁文件里的进程 {pid_str or '(空)'} 已不在 -> 清理锁")
    except (OSError, ValueError):
        print(f"  房间 {lock_file.stem}: 锁文件内容非法 -> 清理锁")
    lock_file.unlink(missing_ok=True)
    return None


def start_locked(cmd: List[str], lock_file: Path, log_stem: str) -> int:
    """在锁的保护下启动一个后台脚本，已在跑就复用。返回进程 PID。"""
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{log_stem}_{int(time.time())}.log"
    with open(log_file, "w") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    lock_file.write_text(str(proc.pid))
    print(f"    日志 -> {log_file}")
    return proc.pid


# Function to get live status using the heartbeat script's --check-only --json
def get_live_status():
    cmd = [sys.executable, 'scripts/heartbeat.py', '--check-only', '--json']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: Failed to get live status: {result.stderr}")
        return {}
    try:
        data = json.loads(result.stdout)
        live_members = data.get('live', [])
        live_dict = {member['name']: member for member in live_members}
        return live_dict
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse JSON output: {e}")
        print(f"Output was: {result.stdout[:200]}")
        return {}

# Lock directory
LOCK_DIR = asoul_support_dir / ".state" / "locks"
LIKE_LOCK_DIR = asoul_support_dir / ".state" / "like_locks"
LOG_DIR = asoul_support_dir / "logs"
COOKIE_FILE = asoul_support_dir / ".cookies.json"
NIGHT_LIGHT_SCRIPT = "scripts/night_light.py"
LIKE_SCRIPT = "scripts/like_room.py"


def _pid_alive(pid: int) -> bool:
    """跨平台判断进程是否存活（Windows 上 os.kill(pid, 0) 不能用于探测）。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, ValueError):
        return False

def start_heartbeat(member: dict) -> Optional[int]:
    """保证该成员有一个挂机进程在跑（X25Kn 心跳直到下播）。"""
    name, room = member["name"], member["room"]
    lock_file = LOCK_DIR / f"{room}.lock"

    pid = _live_pid(lock_file)
    if pid:
        print(f"  {name}: 挂机进程已在运行（PID {pid}）")
        return pid

    cmd = [sys.executable, "scripts/heartbeat.py", "--until-offline", "--members", name]
    pid = start_locked(cmd, lock_file, f"heartbeat_{name}")
    print(f"  {name}: 启动挂机进程，PID {pid}")
    return pid


def start_like(member: dict, settings: dict) -> Optional[int]:
    """保证该成员有一个点赞进程在跑。

    点赞进程点满 target 后自行退出。这里先查一次进度，避免点满之后每 5 分钟
    白起一个进程（每次都会打一次直播状态接口）。
    """
    name, room = member["name"], member["room"]
    if not settings["like"]["enabled"]:
        return None
    target = settings["like"]["target"]
    lock_file = LIKE_LOCK_DIR / f"{room}.lock"

    pid = _live_pid(lock_file)
    if pid:
        print(f"  {name}: 点赞进程已在运行（PID {pid}）")
        return pid

    if like_room.is_done(room, target):
        print(f"  {name}: 今晚已点满 {target} 次，不再拉起点赞进程")
        return None

    cmd = [sys.executable, LIKE_SCRIPT, "--members", name]
    pid = start_locked(cmd, lock_file, f"like_{name}")
    print(f"  {name}: 启动点赞进程，PID {pid}")
    return pid


def run_night_light(targets: List[dict], settings: dict,
                    only_names: Optional[str] = None) -> int:
    """睡眠时段的下播点亮：同步跑一次 night_light。

    同步而不是后台：最长也就 10 条弹幕 × 12 秒，远小于 5 分钟的调度间隔，
    而且同步能让输出直接落在 logs/manage.log 里，不必再引入一把锁。
    在直播的房间由 night_light 自己跳过，所以每 5 分钟跑一次就是「一直等，下播就发」。
    """
    if not targets:
        return 0
    if not settings["night_light"]["enabled"]:
        print("  🌙 下播点亮已在配置中关闭，跳过。")
        return 0
    cmd = [sys.executable, NIGHT_LIGHT_SCRIPT]
    if only_names:
        cmd += ["--members", only_names]
    print(f"  🌙 下播点亮检查：{', '.join(m['name'] for m in targets)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"  ⚠️  下播点亮退出码 {result.returncode}，详见上面的输出")
    return 0


def report_disabled(settings: dict) -> None:
    """把配置里关掉的行为报一遍。

    开关拨了却没反应时，最容易怀疑是程序坏了。在每轮巡检的开头明说一句，
    日志里就能直接看出「不是没跑，是你关了」。
    """
    off = []
    if not settings["danmaku"]["enabled"]:
        off.append("弹幕")
    if not settings["like"]["enabled"]:
        off.append("点赞")
    if not settings["night_light"]["enabled"]:
        off.append("下播点亮")
    if not settings["share"]["on_live"] and not settings["share"]["after_offline"]:
        off.append("分享")
    if not settings["notify"]["enabled"]:
        off.append("Discord 通知")
    if off:
        print(f"  配置中已关闭：{'、'.join(off)}")


def parse_args():
    parser = argparse.ArgumentParser(description="A-SOUL 挂机进程管理（含活跃时段控制）")
    parser.add_argument("--members", help="临时覆盖监听成员（逗号分隔），默认读配置")
    parser.add_argument("--ignore-window", action="store_true",
                        help="忽略 active_hours 时段限制，强制检测/挂机")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not COOKIE_FILE.exists():
        print("ERROR: .cookies.json not found. Exiting.")
        return 1

    try:
        config = load_config()
        all_members = load_members(require_room=True)
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1

    targets = all_members
    if args.members:
        names = {n.strip() for n in args.members.split(",") if n.strip()}
        targets = [m for m in all_members if m["name"] in names]
        unknown = names - {m["name"] for m in all_members}
        if unknown:
            print(f"WARN: 忽略未知成员 {sorted(unknown)}")
    if not targets:
        print("ERROR: 没有匹配到任何成员，退出。")
        return 1

    LOCK_DIR.mkdir(parents=True, exist_ok=True)

    hour = current_hour()
    start, end = config["active_hours"]["start"], config["active_hours"]["end"]
    active = args.ignore_window or in_active_window(hour, start, end)

    if not active:
        # 睡眠时段：挂机与点赞都该停了，然后做当晚的「下播点亮」
        print(f"当前 {hour:02d}:00 不在活跃时段 {start:02d}:00-{end:02d}:00，进入睡眠。")
        stop_locked_members(LOCK_DIR, "离开活跃时段")
        stop_locked_members(LIKE_LOCK_DIR, "离开活跃时段")
        run_night_light(targets, config["settings"], only_names=args.members)
        return 0

    print(f"活跃时段 {start:02d}:00-{end:02d}:00（当前 {hour:02d}:00），"
          f"监听成员：{', '.join(m['name'] for m in targets)}")
    report_disabled(config["settings"])

    # 配置是唯一数据源：成员被删除 / 房间号被改动后，旧房间的挂机进程不该继续跑。
    # 比较的是全量配置 all_members 而不是本轮的 targets——--members 只是临时筛选，
    # 不能因此把其他成员的挂机一起杀掉。
    known_rooms = {str(m["room"]) for m in all_members}
    orphans = stop_locked_members(LOCK_DIR, "已不在配置中", keep_rooms=known_rooms)
    orphans += stop_locked_members(LIKE_LOCK_DIR, "已不在配置中", keep_rooms=known_rooms)
    if orphans:
        print(f"  已停止 {orphans} 个不在配置中的后台进程。")

    live_status = get_live_status()
    print(f"Current live members: {[m['name'] for m in live_status.values()]}")

    # For each member, check lock and start if needed
    for member in targets:
        name = member['name']
        room_id = member['room']

        if name in live_status:
            start_heartbeat(member)
            start_like(member, settings=config["settings"])
        else:
            # 主播没开播：残留的后台进程已经没有意义。
            # 注意必须连进程一起杀掉再删锁——只删锁会让进程变成没有锁的“幽灵”，
            # 下轮开播时 manage 看不到锁就会再起一个，同房间出现两个心跳进程。
            for lock_dir, label in ((LOCK_DIR, "挂机"), (LIKE_LOCK_DIR, "点赞")):
                if (lock_dir / f"{room_id}.lock").exists():
                    _stop_lock(lock_dir / f"{room_id}.lock", f"主播未开播，停止{label}")
                else:
                    print(f"  {name}: 未开播，没有{label}进程")

    # 过了 night_light.after_hour 就不再受挂机时段约束：挂机照跑到时段结束，
    # 但每轮也顺带查一次点亮，免得像从前那样非等到挂机时段整个结束才做。
    # 全员还在播就不必跑了——night_light 只会一个个跳过，白打一次接口。
    due = night_light_due(hour, start, end, config["settings"]["night_light"]["after_hour"])
    if due and any(m["name"] not in live_status for m in targets):
        run_night_light(targets, config["settings"], only_names=args.members)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())