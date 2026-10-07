"""log_rotate 的单元测试：隔天的日志要压成 .gz 并清空原文件，过期归档要删掉。"""

import gzip
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import log_rotate  # noqa: E402


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    """本地时区的某个时刻，与 log_rotate 内部的 time.localtime 对齐。"""
    return time.mktime((year, month, day, hour, 0, 0, 0, 0, -1))


NOW = _ts(2026, 10, 8)          # 「今天」
YESTERDAY = _ts(2026, 10, 7)


def _read_gz(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return handle.read()


class RotateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_dir = Path(self._tmp.name)

    def write_log(self, name: str, text: str, when: float) -> Path:
        path = self.log_dir / name
        path.write_text(text, encoding="utf-8")
        os.utime(path, (when, when))
        return path

    # ---- 归档 ----

    def test_yesterday_is_archived_and_truncated(self):
        log = self.write_log("枯水.log", "昨天的挂机\n", YESTERDAY)

        actions = log_rotate.rotate(self.log_dir, now=NOW)

        archive = self.log_dir / "枯水.2026-10-07.log.gz"
        self.assertTrue(archive.exists())
        self.assertEqual(_read_gz(archive), "昨天的挂机\n")
        self.assertTrue(log.exists())                       # 就地清空，不是删掉
        self.assertEqual(log.read_text(encoding="utf-8"), "")
        self.assertEqual(actions, ["归档 枯水.log -> 枯水.2026-10-07.log.gz"])

    def test_today_is_left_alone(self):
        log = self.write_log("枯水.log", "今天的\n", NOW)

        self.assertEqual(log_rotate.rotate(self.log_dir, now=NOW), [])
        self.assertEqual(log.read_text(encoding="utf-8"), "今天的\n")
        self.assertEqual(list(self.log_dir.glob("*.gz")), [])

    def test_empty_log_is_not_archived(self):
        """空文件留档只会攒出一堆 0 字节 .gz。"""
        self.write_log("枯水.log", "", YESTERDAY)

        self.assertEqual(log_rotate.rotate(self.log_dir, now=NOW), [])
        self.assertEqual(list(self.log_dir.glob("*.gz")), [])

    def test_manage_log_is_rotated_too(self):
        """manage.log 由 systemd 追加，同样得能归档——靠的正是 copytruncate。"""
        self.write_log("manage.log", "昨天的巡检\n", YESTERDAY)

        log_rotate.rotate(self.log_dir, now=NOW)

        self.assertEqual(_read_gz(self.log_dir / "manage.2026-10-07.log.gz"),
                         "昨天的巡检\n")

    def test_second_rotation_appends_into_the_same_archive(self):
        """同一天归档两次（重启、改时间）不能把上一段覆盖掉。"""
        log = self.write_log("枯水.log", "第一段\n", YESTERDAY)
        log_rotate.rotate(self.log_dir, now=NOW)
        self.write_log("枯水.log", "第二段\n", YESTERDAY)

        log_rotate.rotate(self.log_dir, now=NOW)

        self.assertEqual(_read_gz(self.log_dir / "枯水.2026-10-07.log.gz"),
                         "第一段\n第二段\n")

    def test_archived_file_is_written_with_the_old_day_in_its_name(self):
        """跨零点后归档，文件名要落在「内容所属的那天」而不是今天。"""
        self.write_log("枯水.log", "跨零点前写的\n", _ts(2026, 10, 7, 23))

        log_rotate.rotate(self.log_dir, now=_ts(2026, 10, 8, 0))

        self.assertTrue((self.log_dir / "枯水.2026-10-07.log.gz").exists())
        self.assertFalse((self.log_dir / "枯水.2026-10-08.log.gz").exists())

    # ---- 过期清理 ----

    def test_archives_older_than_keep_days_are_deleted(self):
        too_old = self.log_dir / "枯水.2026-08-01.log.gz"
        boundary = self.log_dir / "枯水.2026-09-09.log.gz"   # 距今 30 天的边界，含今天
        recent = self.log_dir / "枯水.2026-10-07.log.gz"
        for path in (too_old, boundary, recent):
            path.write_bytes(b"")

        actions = log_rotate.rotate(self.log_dir, now=NOW)

        self.assertFalse(too_old.exists())
        self.assertTrue(boundary.exists())
        self.assertTrue(recent.exists())
        self.assertEqual(actions, ["删除过期归档 枯水.2026-08-01.log.gz"])

    def test_keep_days_is_configurable(self):
        archive = self.log_dir / "枯水.2026-10-05.log.gz"
        archive.write_bytes(b"")

        log_rotate.rotate(self.log_dir, now=NOW, keep_days=2)

        self.assertFalse(archive.exists())

    def test_foreign_gz_files_are_not_touched(self):
        """logs/ 下可能有别人放的压缩包：名字里取不出日期就别动。"""
        stray = self.log_dir / "backup.log.gz"
        stray.write_bytes(b"")

        self.assertEqual(log_rotate.rotate(self.log_dir, now=NOW), [])
        self.assertTrue(stray.exists())

    # ---- 边界 ----

    def test_missing_dir_is_a_noop(self):
        self.assertEqual(log_rotate.rotate(self.log_dir / "nope", now=NOW), [])

    def test_empty_dir_is_a_noop(self):
        self.assertEqual(log_rotate.rotate(self.log_dir, now=NOW), [])

    def test_one_bad_file_does_not_stop_the_rest(self):
        """单个文件出问题不该让整轮归档停下——其余文件照常处理。"""
        self.write_log("枯水.log", "昨天的\n", YESTERDAY)
        self.write_log("向晚.log", "昨天的\n", YESTERDAY)
        real_archive = log_rotate._archive

        def flaky(log_file, day):
            if log_file.name == "枯水.log":
                raise OSError("模拟归档失败")
            return real_archive(log_file, day)

        with patch.object(log_rotate, "_archive", side_effect=flaky):
            actions = log_rotate.rotate(self.log_dir, now=NOW)

        self.assertTrue((self.log_dir / "向晚.2026-10-07.log.gz").exists())
        self.assertEqual(len(actions), 2)
        self.assertTrue(any("失败" in action for action in actions))


if __name__ == "__main__":
    unittest.main()
