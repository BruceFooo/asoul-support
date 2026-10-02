"""local_time 的单元测试。重点是 Windows 上不能再依赖 time.localtime()。"""

import ctypes
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import local_time  # noqa: E402


class LocalHourTests(unittest.TestCase):
    def test_returns_hour_in_range(self):
        hour = local_time.local_hour()
        self.assertIsInstance(hour, int)
        self.assertTrue(0 <= hour <= 23, f"hour={hour}")

    @unittest.skipUnless(os.name == "nt", "Windows-only")
    def test_does_not_use_time_localtime(self):
        """Git Bash 把 TZ 设成 UTC，此时 time.localtime() 会差 8 小时。"""
        with patch.object(local_time.time, "localtime",
                          side_effect=AssertionError("不应依赖 time.localtime()")):
            hour = local_time.local_hour()
        self.assertTrue(0 <= hour <= 23)

    @unittest.skipUnless(os.name == "nt", "Windows-only")
    def test_matches_getlocaltime(self):
        class SYSTEMTIME(ctypes.Structure):
            _fields_ = [("wYear", ctypes.c_ushort), ("wMonth", ctypes.c_ushort),
                        ("wDayOfWeek", ctypes.c_ushort), ("wDay", ctypes.c_ushort),
                        ("wHour", ctypes.c_ushort), ("wMinute", ctypes.c_ushort),
                        ("wSecond", ctypes.c_ushort), ("wMilliseconds", ctypes.c_ushort)]

        st = SYSTEMTIME()
        ctypes.windll.kernel32.GetLocalTime(ctypes.byref(st))
        self.assertEqual(local_time.local_hour(), st.wHour)
        self.assertEqual(local_time.local_date(), f"{st.wYear:04d}-{st.wMonth:02d}-{st.wDay:02d}")


class LocalDateTests(unittest.TestCase):
    def test_format_is_iso_like(self):
        self.assertRegex(local_time.local_date(), r"^\d{4}-\d{2}-\d{2}$")

    def test_uses_getlocaltime_on_windows(self):
        """日期不能来自 time.localtime()——TZ=UTC 的 shell 里跨零点会判错一天。"""
        if os.name != "nt":
            self.skipTest("Windows-only")
        with patch.object(local_time.time, "localtime",
                          side_effect=AssertionError("不应依赖 time.localtime()")):
            self.assertRegex(local_time.local_date(), r"^\d{4}-\d{2}-\d{2}$")

    def test_is_stable_within_a_run(self):
        self.assertEqual(local_time.local_date(), local_time.local_date())


class LocalStampTests(unittest.TestCase):
    """日志时间戳同样不能用 time.localtime()，否则 TZ=UTC 的 shell 里会差 8 小时。"""

    def test_format_is_iso_like_to_the_second(self):
        self.assertRegex(local_time.local_stamp(),
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    @unittest.skipUnless(os.name == "nt", "Windows-only")
    def test_does_not_use_time_localtime(self):
        with patch.object(local_time.time, "localtime",
                          side_effect=AssertionError("不应依赖 time.localtime()")):
            stamp = local_time.local_stamp()
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    @unittest.skipUnless(os.name == "nt", "Windows-only")
    def test_starts_with_local_date(self):
        self.assertTrue(local_time.local_stamp().startswith(local_time.local_date()))


class ActiveWindowTests(unittest.TestCase):
    def test_normal_window(self):
        self.assertTrue(local_time.in_active_window(9, 8, 18))
        self.assertFalse(local_time.in_active_window(18, 8, 18))
        self.assertFalse(local_time.in_active_window(7, 8, 18))

    def test_window_crossing_midnight(self):
        for hour in (21, 22, 23, 0):
            self.assertTrue(local_time.in_active_window(hour, 21, 1), f"hour {hour} 应在时段内")
        for hour in (1, 2, 12, 20):
            self.assertFalse(local_time.in_active_window(hour, 21, 1), f"hour {hour} 应在时段外")

    def test_equal_start_end_means_all_day(self):
        self.assertTrue(local_time.in_active_window(0, 5, 5))
        self.assertTrue(local_time.in_active_window(23, 5, 5))

    def test_full_day_window(self):
        for hour in range(24):
            self.assertTrue(local_time.in_active_window(hour, 0, 0))


if __name__ == "__main__":
    unittest.main()
