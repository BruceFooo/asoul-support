import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import manage_asoul_heartbeat as mgr  # noqa: E402
import asoul_members  # noqa: E402  (mgr 已把 scripts/ 放进 sys.path)


class ActiveWindowTests(unittest.TestCase):
    def test_normal_window(self):
        self.assertTrue(mgr.in_active_window(9, 8, 18))
        self.assertFalse(mgr.in_active_window(18, 8, 18))
        self.assertFalse(mgr.in_active_window(7, 8, 18))

    def test_window_crossing_midnight(self):
        # 21:00 → 次日 01:00
        for hour in (21, 22, 23, 0):
            self.assertTrue(mgr.in_active_window(hour, 21, 1), f"hour {hour} 应在时段内")
        for hour in (1, 2, 12, 20):
            self.assertFalse(mgr.in_active_window(hour, 21, 1), f"hour {hour} 应在时段外")

    def test_equal_start_end_means_all_day(self):
        self.assertTrue(mgr.in_active_window(0, 5, 5))
        self.assertTrue(mgr.in_active_window(23, 5, 5))


class CurrentHourTests(unittest.TestCase):
    def test_returns_hour_in_range(self):
        hour = mgr.current_hour()
        self.assertIsInstance(hour, int)
        self.assertTrue(0 <= hour <= 23, f"hour={hour}")

    @unittest.skipUnless(mgr.os.name == "nt", "Windows-only")
    def test_windows_path_does_not_use_time_localtime(self):
        """TZ=UTC 的 shell 里 time.localtime() 会差 8 小时，Windows 必须走 GetLocalTime。"""
        with patch.object(mgr.time, "localtime",
                          side_effect=AssertionError("不应依赖 time.localtime()")):
            hour = mgr.current_hour()
        self.assertTrue(0 <= hour <= 23)

    @unittest.skipUnless(mgr.os.name == "nt", "Windows-only")
    def test_matches_system_local_time_not_utc(self):
        """系统时区非 UTC 时，本地小时应与 UTC 小时不同（本项目机器为 UTC+8）。"""
        import ctypes

        class SYSTEMTIME(ctypes.Structure):
            _fields_ = [("wYear", ctypes.c_ushort), ("wMonth", ctypes.c_ushort),
                        ("wDayOfWeek", ctypes.c_ushort), ("wDay", ctypes.c_ushort),
                        ("wHour", ctypes.c_ushort), ("wMinute", ctypes.c_ushort),
                        ("wSecond", ctypes.c_ushort), ("wMilliseconds", ctypes.c_ushort)]

        st = SYSTEMTIME()
        ctypes.windll.kernel32.GetLocalTime(ctypes.byref(st))
        self.assertEqual(mgr.current_hour(), st.wHour)


class ConfigTests(unittest.TestCase):
    """管理器不再自带成员默认值——配置读取完全委托给 scripts/asoul_members.py。"""

    def test_missing_config_raises(self):
        with patch.object(asoul_members, "CONFIG_PATH",
                          Path(tempfile.gettempdir()) / "no-such-config.json"):
            with self.assertRaises(asoul_members.ConfigError):
                mgr.load_config()

    def test_reads_members_from_config(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".asoul_config.json"
            path.write_text(json.dumps({
                "members": [{"name": "嘉然", "uid": 672328094, "room": 22637261}],
                "active_hours": {"start": 20, "end": 23},
            }), encoding="utf-8")
            with patch.object(asoul_members, "CONFIG_PATH", path):
                cfg = mgr.load_config()
        self.assertEqual([m["name"] for m in cfg["members"]], ["嘉然"])
        self.assertEqual(cfg["members"][0]["room"], 22637261)
        self.assertEqual(cfg["active_hours"], {"start": 20, "end": 23})

    def test_broken_config_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".asoul_config.json"
            path.write_text("{ not json", encoding="utf-8")
            with patch.object(asoul_members, "CONFIG_PATH", path):
                with self.assertRaises(asoul_members.ConfigError):
                    mgr.load_config()


class StopMemberTests(unittest.TestCase):
    def test_stale_lock_removed_without_killing(self):
        with tempfile.TemporaryDirectory() as d:
            lock_dir = Path(d)
            (lock_dir / "22637261.lock").write_text("999999999")
            with patch.object(mgr, "_pid_alive", return_value=False), \
                 patch.object(mgr.subprocess, "run") as run:
                stopped = mgr.stop_locked_members(lock_dir, "test")
            run.assert_not_called()
            self.assertEqual(stopped, 0)
            self.assertFalse((lock_dir / "22637261.lock").exists())

    def test_live_lock_kills_process(self):
        with tempfile.TemporaryDirectory() as d:
            lock_dir = Path(d)
            (lock_dir / "22637261.lock").write_text("12345")
            with patch.object(mgr, "_pid_alive", return_value=True), \
                 patch.object(mgr.subprocess, "run") as run:
                stopped = mgr.stop_locked_members(lock_dir, "test")
            run.assert_called_once()
            self.assertEqual(stopped, 1)
            self.assertFalse((lock_dir / "22637261.lock").exists())

    def test_kills_orphan_lock_from_removed_member(self):
        """成员被从配置删除后遗留的锁（不在任何成员列表里）也必须能杀掉。"""
        with tempfile.TemporaryDirectory() as d:
            lock_dir = Path(d)
            (lock_dir / "22637261.lock").write_text("111")
            (lock_dir / "99999999.lock").write_text("222")  # 配置里没有这个房间
            with patch.object(mgr, "_pid_alive", return_value=True), \
                 patch.object(mgr.subprocess, "run"):
                stopped = mgr.stop_locked_members(lock_dir, "test")
            self.assertEqual(stopped, 2)
            self.assertEqual(list(lock_dir.glob("*.lock")), [])

    def test_keep_rooms_spares_current_members(self):
        """成员被删掉后，只有它的挂机进程该停，其余成员照常跑。"""
        with tempfile.TemporaryDirectory() as d:
            lock_dir = Path(d)
            (lock_dir / "22637261.lock").write_text("111")  # 仍在配置里
            (lock_dir / "99999999.lock").write_text("222")  # 已从配置删除
            with patch.object(mgr, "_pid_alive", return_value=True), \
                 patch.object(mgr.subprocess, "run") as run:
                stopped = mgr.stop_locked_members(lock_dir, "已不在配置中",
                                                  keep_rooms={"22637261"})
            self.assertEqual(stopped, 1)
            run.assert_called_once()
            self.assertEqual([p.name for p in lock_dir.glob("*.lock")], ["22637261.lock"])

    def test_keep_rooms_none_kills_everything(self):
        with tempfile.TemporaryDirectory() as d:
            lock_dir = Path(d)
            (lock_dir / "22637261.lock").write_text("111")
            (lock_dir / "99999999.lock").write_text("222")
            with patch.object(mgr, "_pid_alive", return_value=True), \
                 patch.object(mgr.subprocess, "run"):
                stopped = mgr.stop_locked_members(lock_dir, "手动关闭")
            self.assertEqual(stopped, 2)
            self.assertEqual(list(lock_dir.glob("*.lock")), [])

    def test_missing_lock_dir_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(mgr.stop_locked_members(Path(d) / "nope", "test"), 0)


if __name__ == "__main__":
    unittest.main()