#!/usr/bin/env python3
"""给脚本输出逐行加秒级时间戳。

计划任务把 stdout / stderr 直接追加进 `logs/manage.log`，原先行里只有内容没有
时间：一晚几百行攒在同一个文件里，事后分不清哪一行属于哪一次巡检、中间隔了多久。

入口脚本在 `__main__` 里调 `install()`，把 stdout / stderr 换成逐行加
`[YYYY-MM-DD HH:MM:SS]` 前缀的包装。时间取 `local_time.local_stamp()`——
不能用 `time.localtime()`，Git Bash 的 TZ=UTC 会让它差 8 小时。

**每个进程各装一次**：子进程（如 manage 调起的 night_light）继承的是文件描述符，
不经过父进程的 Python 层包装，它自己也得装，否则它的行会变成没有前缀的孤儿。
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


_installed = False


def install() -> None:
    """给 stdout / stderr 装时间戳前缀；流为空（pythonw 无重定向）时跳过。重复调用无副作用。"""
    global _installed
    if _installed:
        return
    _installed = True
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is not None:
            setattr(sys, name, _Stamped(stream))
