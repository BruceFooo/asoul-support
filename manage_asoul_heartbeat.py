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

# Change to the asoul-support directory
asoul_support_dir = Path(__file__).parent.resolve()
os.chdir(asoul_support_dir)

# 共享配置模块在 scripts/ 下（与 check_auth.py 同级），项目根不在默认搜索路径里
sys.path.insert(0, str(asoul_support_dir / "scripts"))
from asoul_members import ConfigError, load_config, load_members  # noqa: E402


def current_hour() -> int:
    """取系统本地时间的“小时”（0-23）。

    注意：Git Bash / MSYS 等环境会把 TZ 设成 UTC，此时 time.localtime() 会偏离
    系统真实本地时间（实测差 8 小时）。Windows 上直接用 GetLocalTime 取系统时间，
    绕开 TZ 环境变量。
    """
    if os.name == "nt":
        import ctypes

        class SYSTEMTIME(ctypes.Structure):
            _fields_ = [
                ("wYear", ctypes.c_ushort), ("wMonth", ctypes.c_ushort),
                ("wDayOfWeek", ctypes.c_ushort), ("wDay", ctypes.c_ushort),
                ("wHour", ctypes.c_ushort), ("wMinute", ctypes.c_ushort),
                ("wSecond", ctypes.c_ushort), ("wMilliseconds", ctypes.c_ushort),
            ]

        now = SYSTEMTIME()
        ctypes.windll.kernel32.GetLocalTime(ctypes.byref(now))
        return now.wHour
    return time.localtime().tm_hour


def in_active_window(now_hour: int, start: int, end: int) -> bool:
    """判断当前小时是否落在活跃时段内，支持跨零点（如 21 → 1）。"""
    if start == end:
        return True  # 24 小时活跃
    if start < end:
        return start <= now_hour < end
    return now_hour >= start or now_hour < end  # 跨零点


def stop_locked_members(lock_dir: Path, reason: str) -> int:
    """终止所有仍在运行的挂机进程并清理锁文件（用于离开活跃时段 / 手动关闭）。

    直接扫描锁目录而不是遍历成员列表——这样即使某成员已被从配置中删除，
    它遗留的挂机进程也能被正确终止。
    """
    if not lock_dir.exists():
        return 0

    stopped = 0
    for lock_file in sorted(lock_dir.glob("*.lock")):
        try:
            pid_str = lock_file.read_text().strip()
            if pid_str and _pid_alive(int(pid_str)):
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", pid_str, "/T", "/F"],
                                   capture_output=True, check=False)
                else:
                    try:
                        os.kill(int(pid_str), signal.SIGTERM)
                    except OSError:
                        pass
                print(f"  房间 {lock_file.stem}: {reason}，已终止挂机进程 {pid_str}")
                stopped += 1
            lock_file.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            print(f"  {lock_file.name}: 终止挂机时出错 {type(exc).__name__}: {exc}")
            lock_file.unlink(missing_ok=True)
    return stopped

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

def parse_args():
    parser = argparse.ArgumentParser(description="A-SOUL 挂机进程管理（含活跃时段控制）")
    parser.add_argument("--members", help="临时覆盖监听成员（逗号分隔），默认读配置")
    parser.add_argument("--ignore-window", action="store_true",
                        help="忽略 active_hours 时段限制，强制检测/挂机")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not Path(".cookies.json").exists():
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
        # 睡眠时段：停掉仍在运行的挂机进程，本次直接退出
        print(f"当前 {hour:02d}:00 不在活跃时段 {start:02d}:00-{end:02d}:00，进入睡眠。")
        stop_locked_members(LOCK_DIR, "离开活跃时段")
        return 0

    print(f"活跃时段 {start:02d}:00-{end:02d}:00（当前 {hour:02d}:00），"
          f"监听成员：{', '.join(m['name'] for m in targets)}")

    live_status = get_live_status()
    print(f"Current live members: {[m['name'] for m in live_status.values()]}")

    # For each member, check lock and start if needed
    for member in targets:
        name = member['name']
        room_id = member['room']
        lock_file = LOCK_DIR / f"{room_id}.lock"

        # Check if lock file exists and if the process is still running
        lock_valid = False
        if lock_file.exists():
            try:
                pid_str = lock_file.read_text().strip()
                if pid_str:
                    pid = int(pid_str)
                    if _pid_alive(pid):
                        lock_valid = True
                        print(f"  {name}: Lock exists with PID {pid} (process running)")
                    else:
                        print(f"  {name}: Lock file exists but process {pid} not running -> removing")
                        lock_file.unlink(missing_ok=True)
                else:
                    print(f"  {name}: Lock file exists but empty -> removing")
                    lock_file.unlink()
            except (OSError, ValueError):
                print(f"  {name}: Lock file invalid -> removing")
                lock_file.unlink(missing_ok=True)

        # If member is live and no valid lock, start the heartbeat script
        if name in live_status:
            if not lock_valid:
                print(f"  {name}: Starting heartbeat process...")
                log_dir = Path('logs')
                log_dir.mkdir(exist_ok=True)
                log_file = log_dir / f"heartbeat_{name}_{int(time.time())}.log"
                cmd = [sys.executable, 'scripts/heartbeat.py',
                       '--until-offline', '--members', name]
                with open(log_file, 'w') as f:
                    proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
                lock_file.write_text(str(proc.pid))
                print(f"  {name}: Started heartbeat process with PID {proc.pid}, logging to {log_file}")
            else:
                print(f"  {name}: Heartbeat process already running (PID from lock file)")
        else:
            # Member is not live
            if lock_file.exists():
                print(f"  {name}: Member is not live, but lock file exists -> removing")
                lock_file.unlink()
            else:
                print(f"  {name}: Member is not live, no lock file")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())