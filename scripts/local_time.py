#!/usr/bin/env python3
"""系统本地时间。

Git Bash / MSYS 等环境会把 TZ 设成 UTC，此时 `time.localtime()` 会偏离系统真实
本地时间（本机实测差 8 小时）。Windows 上直接用 `GetLocalTime` 取系统时间，
绕开 TZ 环境变量。

活跃时段判断与「每晚一次」的日期比较都必须走这里，否则会出现
「半夜 1 点被判成下午 5 点」这类错位。
"""

import os
import time
from typing import Tuple


def _windows_now() -> Tuple[int, int, int, int, int, int]:
    """返回 (年, 月, 日, 时, 分, 秒)，取 Windows 系统本地时间。"""
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
    return (now.wYear, now.wMonth, now.wDay,
            now.wHour, now.wMinute, now.wSecond)


def local_hour() -> int:
    """当前本地小时（0-23）。"""
    if os.name == "nt":
        return _windows_now()[3]
    return time.localtime().tm_hour


def local_date() -> str:
    """当前本地日期，`YYYY-MM-DD`。用于「每晚一次」的防重比较。"""
    if os.name == "nt":
        year, month, day = _windows_now()[:3]
    else:
        now = time.localtime()
        year, month, day = now.tm_year, now.tm_mon, now.tm_mday
    return f"{year:04d}-{month:02d}-{day:02d}"


def local_stamp() -> str:
    """当前本地时间，`YYYY-MM-DD HH:MM:SS`。用于给日志逐行打时间戳。"""
    if os.name == "nt":
        year, month, day, hour, minute, second = _windows_now()
    else:
        now = time.localtime()
        year, month, day = now.tm_year, now.tm_mon, now.tm_mday
        hour, minute, second = now.tm_hour, now.tm_min, now.tm_sec
    return (f"{year:04d}-{month:02d}-{day:02d} "
            f"{hour:02d}:{minute:02d}:{second:02d}")


def in_active_window(now_hour: int, start: int, end: int) -> bool:
    """判断当前小时是否落在活跃时段内，支持跨零点（如 21 → 1）。"""
    if start == end:
        return True  # start == end 表示全天活跃
    if start < end:
        return start <= now_hour < end
    return now_hour >= start or now_hour < end  # 跨零点
