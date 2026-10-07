#!/usr/bin/env python3
"""给脚本输出逐行加秒级时间戳。

计划任务把 stdout / stderr 直接追加进 `logs/manage.log`，原先行里只有内容没有
时间：一晚几百行攒在同一个文件里，事后分不清哪一行属于哪一次巡检、中间隔了多久。

入口脚本在 `__main__` 里调 `install()`，把 stdout / stderr 换成逐行加
`[YYYY-MM-DD HH:MM:SS]` 前缀的包装。时间取 `local_time.local_stamp()`——
不能用 `time.localtime()`，Git Bash 的 TZ=UTC 会让它差 8 小时。

**每个进程各装一次**：子进程（如 manage 调起的 night_light）继承的是文件描述符，
不经过父进程的 Python 层包装，它自己也得装，否则它的行会变成没有前缀的孤儿。

顺带把流改成行缓冲——重定向到文件时 Python 默认按 8KB 块缓冲，长跑的挂机进程
要攒满一整块才落盘，日志会长时间停在旧内容上。
"""

import sys

from local_time import local_stamp


class _Stamped:
    """给写入的每一行开头加 `[时间] `。行首之外的位置原样透传。"""

    def __init__(self, stream):
        self._stream = stream
        self._at_line_start = True

    def write(self, text: str) -> int:
        if not text:
            return 0
        out = []
        for index, piece in enumerate(text.split("\n")):
            if index:  # 上一段以换行结尾，这里就是新的一行的开头
                out.append("\n")
                self._at_line_start = True
            if piece:
                if self._at_line_start:
                    out.append(f"[{local_stamp()}] ")
                    self._at_line_start = False
                out.append(piece)
        self._stream.write("".join(out))
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name):
        # encoding / fileno / buffer 之类的属性仍然透传，别把它们弄丢
        return getattr(self._stream, name)


def _line_buffer(stream) -> None:
    """让输出逐行落盘。

    重定向到文件时 Python 按块缓冲（8KB）：心跳每 60 秒打一行，却要攒满一整块才
    真正写出，日志看着就像挂机没在跑。改成行缓冲后一行一次 write，配合 O_APPEND，
    manage 与它拉起的子进程同写一个 `logs/<成员>.log` 也不会互相覆盖。
    """
    try:
        stream.reconfigure(line_buffering=True)
    except (AttributeError, ValueError, OSError):
        pass  # pythonw 无重定向，或已经是包装过的流：保持原样


_installed = False


def install(stdout: bool = True, stderr: bool = True) -> None:
    """给 stdout / stderr 装行缓冲与时间戳前缀；流为空（pythonw 无重定向）时跳过。

    `stdout=False` 留给「stdout 是机器可读数据」的脚本——比如 heartbeat 的
    `--json`：manage 靠 `json.loads` 读它，加了 `[时间] ` 前缀就解析不了。

    这是「本进程只装一次」的一次性开关：先 `install()` 再 `install(stdout=False)`
    不会把已经装上的前缀摘下来。
    """
    global _installed
    if _installed:
        return
    _installed = True
    for name, wanted in (("stdout", stdout), ("stderr", stderr)):
        if not wanted:
            continue
        stream = getattr(sys, name)
        if stream is not None:
            _line_buffer(stream)
            setattr(sys, name, _Stamped(stream))
