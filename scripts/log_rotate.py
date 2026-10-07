#!/usr/bin/env python3
"""日志归档：把隔天的日志压成 .gz，只保留最近 N 天。

一个成员只有一个 `logs/<成员>.log`，天天写下去会无限长大，所以由 manage 每轮
巡检顺手滚一次：跨过零点后，凡是最后修改时间还在昨天的 `.log` 就归档掉。

**用 copytruncate，不能用 rename。** `logs/manage.log` 的 fd 握在 systemd 手里，
成员日志的 fd 握在挂机 / 点赞子进程手里；改名之后它们会继续写进那个已改名的
inode，新建的同名文件永远是空的。所以先把内容抄进 .gz，再把原文件就地清空——
O_APPEND 的写入端不受影响，接着往下写就行。

代价是抄写与清空之间那一瞬写入的行可能丢。日志而已，认了。

不依赖 logrotate / cron，纯标准库，Windows 计划任务下同样能跑。
"""

import gzip
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

ARCHIVE_SUFFIX = ".log.gz"
_ARCHIVE_RE = re.compile(r"\.(\d{4}-\d{2}-\d{2})\.log\.gz$")


def _day(ts: float) -> str:
    """时间戳 -> 本地日期 `YYYY-MM-DD`。归档按本地日期分，跨零点即翻篇。"""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _archive_day(archive: Path) -> Optional[str]:
    """从归档文件名里取回它属于哪一天；取不到返回 None。"""
    match = _ARCHIVE_RE.search(archive.name)
    return match.group(1) if match else None


def _archive_path(log_file: Path, day: str) -> Path:
    """`logs/枯水.log` + 2026-10-08 -> `logs/枯水.2026-10-08.log.gz`"""
    return log_file.with_name(f"{log_file.stem}.{day}{ARCHIVE_SUFFIX}")


def _archive(log_file: Path, day: str) -> Path:
    """把日志内容追加进当天的 .gz 并就地清空原文件，返回归档路径。

    以 `ab` 打开：目标已存在时压成「多成员 gzip」，gunzip / gzip.open 读回来
    仍是完整内容，不会像覆盖那样把同一天的上一段丢掉。
    """
    target = _archive_path(log_file, day)
    with open(log_file, "rb") as src, gzip.open(target, "ab") as dst:
        shutil.copyfileobj(src, dst)
    with open(log_file, "wb"):
        pass  # 就地清空：保住 inode，写入端不用重新打开
    return target


def rotate(log_dir: Path, keep_days: int = 30,
           now: Optional[float] = None) -> List[str]:
    """归档非今天的日志，删掉超过 keep_days 天的归档。

    返回做过的事（一行一条），交给调用方打印——出问题时能从日志里看出是没跑
    还是没得跑。单个文件出错不影响其余文件。
    """
    moment = time.time() if now is None else now
    today = _day(moment)
    cutoff = datetime.strptime(today, "%Y-%m-%d").date() - timedelta(days=keep_days - 1)

    actions: List[str] = []
    if not log_dir.is_dir():
        return actions

    for log_file in sorted(log_dir.glob("*.log")):
        try:
            modified = log_file.stat().st_mtime
            if log_file.stat().st_size == 0:
                continue  # 空文件不必留档，省得攒一堆 0 字节 .gz
            day = _day(modified)
            if day >= today:
                continue  # 今天还在写，留着
            target = _archive(log_file, day)
            actions.append(f"归档 {log_file.name} -> {target.name}")
        except OSError as exc:
            actions.append(f"归档 {log_file.name} 失败：{type(exc).__name__}: {exc}")

    for archive in sorted(log_dir.glob(f"*{ARCHIVE_SUFFIX}")):
        day = _archive_day(archive)
        if day is None:
            continue  # 不是本模块产出的，不碰
        try:
            if datetime.strptime(day, "%Y-%m-%d").date() < cutoff:
                archive.unlink()
                actions.append(f"删除过期归档 {archive.name}")
        except (OSError, ValueError) as exc:
            actions.append(f"删除 {archive.name} 失败：{type(exc).__name__}: {exc}")

    return actions


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="归档 A-SOUL Support 日志")
    parser.add_argument("--log-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "logs")
    parser.add_argument("--keep-days", type=int, default=30)
    args = parser.parse_args()

    actions = rotate(args.log_dir, keep_days=args.keep_days)
    for action in actions:
        print(action)
    print(f"归档完成：{len(actions)} 项操作，保留最近 {args.keep_days} 天。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
