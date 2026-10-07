import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import manage_asoul_heartbeat as mgr  # noqa: E402
import asoul_members  # noqa: E402  (mgr 已把 scripts/ 放进 sys.path)


def assert_signalled(case: unittest.TestCase, run, kill) -> None:
    """终止挂机进程走的是平台各自的路子：Windows 用 `taskkill`，类 Unix 用 `os.kill`。

    只断言平台对应的那一条。要求两个都被调用会把测试绑死在 Windows 上，
    而这个项目两边都在跑（服务器是 Linux + systemd）。
    """
    if os.name == "nt":
        run.assert_called_once()
    else:
        kill.assert_called_once()


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
                 patch.object(mgr.subprocess, "run") as run, \
                 patch.object(mgr.os, "kill") as kill:
                stopped = mgr.stop_locked_members(lock_dir, "test")
            assert_signalled(self, run, kill)
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
                 patch.object(mgr.subprocess, "run") as run, \
                 patch.object(mgr.os, "kill") as kill:
                stopped = mgr.stop_locked_members(lock_dir, "已不在配置中",
                                                  keep_rooms={"22637261"})
            self.assertEqual(stopped, 1)
            assert_signalled(self, run, kill)
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


class _LockFixture(unittest.TestCase):
    """把两个锁目录和日志目录都指到临时目录，避免污染仓库。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.lock_dir = root / "locks"
        self.like_dir = root / "like_locks"
        self.log_dir = root / "logs"
        for name, value in (("LOCK_DIR", self.lock_dir), ("LIKE_LOCK_DIR", self.like_dir),
                            ("LOG_DIR", self.log_dir)):
            patcher = patch.object(mgr, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_lock(self, directory: Path, room: int, pid) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        lock = directory / f"{room}.lock"
        lock.write_text(str(pid))
        return lock


class LivePidTests(_LockFixture):
    def test_missing_lock_is_none(self):
        self.assertIsNone(mgr._live_pid(self.lock_dir / "281.lock"))

    def test_running_process_returns_pid(self):
        lock = self.write_lock(self.lock_dir, 281, 4321)
        with patch.object(mgr, "_pid_alive", return_value=True):
            self.assertEqual(mgr._live_pid(lock), 4321)
        self.assertTrue(lock.exists())  # 有效的锁必须留着

    def test_dead_process_clears_the_lock(self):
        lock = self.write_lock(self.lock_dir, 281, 4321)
        with patch.object(mgr, "_pid_alive", return_value=False):
            self.assertIsNone(mgr._live_pid(lock))
        self.assertFalse(lock.exists())

    def test_empty_lock_is_cleared(self):
        self.write_lock(self.lock_dir, 281, "")
        self.assertIsNone(mgr._live_pid(self.lock_dir / "281.lock"))
        self.assertFalse((self.lock_dir / "281.lock").exists())

    def test_garbage_lock_is_cleared(self):
        self.write_lock(self.lock_dir, 281, "not-a-pid")
        self.assertIsNone(mgr._live_pid(self.lock_dir / "281.lock"))
        self.assertFalse((self.lock_dir / "281.lock").exists())


class StartLockedTests(_LockFixture):
    def test_spawns_and_records_pid(self):
        lock = self.lock_dir / "281.lock"
        with patch.object(mgr.subprocess, "Popen") as popen:
            popen.return_value.pid = 777
            pid = mgr.start_locked(["python", "x.py"], lock, "枯水")
        self.assertEqual(pid, 777)
        self.assertEqual(lock.read_text(), "777")
        self.assertTrue((self.log_dir / "枯水.log").exists())

    def test_second_start_appends_to_the_same_file(self):
        """挂机与点赞共用 logs/<成员>.log：再启动是追加，不再按时间戳新建文件。"""
        lock = self.lock_dir / "281.lock"
        with patch.object(mgr.subprocess, "Popen") as popen:
            popen.return_value.pid = 777
            mgr.start_locked(["python", "heartbeat.py"], lock, "枯水")
        log = self.log_dir / "枯水.log"
        log.write_text("上一段运行留下的\n", encoding="utf-8")

        with patch.object(mgr.subprocess, "Popen") as popen:
            popen.return_value.pid = 778
            mgr.start_locked(["python", "like_room.py"], lock, "枯水")

        self.assertEqual(list(self.log_dir.glob("*.log")), [log])
        self.assertEqual(log.read_text(encoding="utf-8"), "上一段运行留下的\n")

    def test_member_name_cannot_escape_the_log_dir(self):
        """成员名被直接当文件名用，路径分隔符必须挡掉，否则日志会写到 logs/ 外面。"""
        self.assertEqual(mgr.member_log("../../etc/passwd").parent, self.log_dir)
        self.assertNotIn("/", mgr.member_log("a/b").name)

    def test_blank_member_name_still_gets_a_file(self):
        self.assertEqual(mgr.member_log("   ").name, "unknown.log")


class StartHeartbeatTests(_LockFixture):
    MEMBER = {"name": "枯水", "uid": 699438, "room": 281}

    def test_starts_when_no_lock(self):
        with patch.object(mgr.subprocess, "Popen") as popen:
            popen.return_value.pid = 555
            pid = mgr.start_heartbeat(self.MEMBER)
        self.assertEqual(pid, 555)
        cmd = popen.call_args[0][0]
        self.assertIn("--until-offline", cmd)
        self.assertEqual(cmd[-1], "枯水")

    def test_reuses_running_process(self):
        self.write_lock(self.lock_dir, 281, 555)
        with patch.object(mgr, "_pid_alive", return_value=True), \
             patch.object(mgr.subprocess, "Popen") as popen:
            self.assertEqual(mgr.start_heartbeat(self.MEMBER), 555)
        popen.assert_not_called()


class StartLikeTests(_LockFixture):
    MEMBER = {"name": "枯水", "uid": 699438, "room": 281}
    SETTINGS = {"like": {"enabled": True, "target": 500, "batch": 10,
                         "interval": {"min": 1.0, "max": 3.0}}}

    def test_starts_when_progress_unfinished(self):
        with patch.object(mgr.subprocess, "Popen") as popen:
            popen.return_value.pid = 666
            self.assertEqual(mgr.start_like(self.MEMBER, self.SETTINGS), 666)
        cmd = popen.call_args[0][0]
        self.assertTrue(any("like_room.py" in part for part in cmd))
        self.assertEqual(cmd[-1], "枯水")

    def test_reuses_running_process(self):
        self.write_lock(self.like_dir, 281, 666)
        with patch.object(mgr, "_pid_alive", return_value=True), \
             patch.object(mgr.subprocess, "Popen") as popen:
            self.assertEqual(mgr.start_like(self.MEMBER, self.SETTINGS), 666)
        popen.assert_not_called()

    def test_does_not_respawn_after_target_reached(self):
        """点满之后每 5 分钟白起一个进程是纯粹的浪费，也会刷出一堆日志。"""
        with patch.object(mgr.like_room, "is_done", return_value=True), \
             patch.object(mgr.subprocess, "Popen") as popen:
            self.assertIsNone(mgr.start_like(self.MEMBER, self.SETTINGS))
        popen.assert_not_called()

    def test_spawns_after_daily_reset(self):
        """跨天之后进度清零，必须重新拉起。"""
        with patch.object(mgr.like_room, "is_done", return_value=False), \
             patch.object(mgr.subprocess, "Popen") as popen:
            popen.return_value.pid = 1
            self.assertEqual(mgr.start_like(self.MEMBER, self.SETTINGS), 1)
        popen.assert_called_once()

    def test_disabled_in_config_does_not_spawn(self):
        """like.enabled=false：连查进度都不做，直接不起进程。"""
        settings = json.loads(json.dumps(self.SETTINGS))
        settings["like"]["enabled"] = False
        with patch.object(mgr.like_room, "is_done") as done, \
             patch.object(mgr.subprocess, "Popen") as popen:
            self.assertIsNone(mgr.start_like(self.MEMBER, settings))
        popen.assert_not_called()
        done.assert_not_called()


class RunNightLightTests(unittest.TestCase):
    MEMBERS = [{"name": "枯水", "uid": 699438, "room": 281}]
    SETTINGS = {"night_light": {"enabled": True}}

    def run_night(self, members=None, settings=None, **kwargs):
        return mgr.run_night_light(self.MEMBERS if members is None else members,
                                   settings or self.SETTINGS, **kwargs)

    def test_runs_the_script(self):
        with patch.object(mgr.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(self.run_night(), 0)
        cmd = run.call_args[0][0]
        self.assertTrue(any("night_light.py" in part for part in cmd))

    def test_forwards_member_filter(self):
        with patch.object(mgr.subprocess, "run") as run:
            self.run_night(only_names="枯水")
        self.assertEqual(run.call_args[0][0][-2:], ["--members", "枯水"])

    def test_no_members_is_a_noop(self):
        with patch.object(mgr.subprocess, "run") as run:
            self.assertEqual(self.run_night(members=[]), 0)
        run.assert_not_called()

    def test_child_failure_does_not_fail_the_whole_run(self):
        """点亮是尽力而为的附加功能，不该把整个调度任务标成失败。"""
        with patch.object(mgr.subprocess, "run") as run:
            run.return_value.returncode = 1
            self.assertEqual(self.run_night(), 0)

    def test_disabled_in_config_skips_the_subprocess(self):
        with patch.object(mgr.subprocess, "run") as run:
            self.assertEqual(self.run_night(settings={"night_light": {"enabled": False}}), 0)
        run.assert_not_called()


class ReportDisabledTests(unittest.TestCase):
    """开关拨了却没反应时最容易怀疑程序坏了，所以每轮巡检都要把关掉的行为念一遍。"""

    def _report(self, **overrides):
        settings = json.loads(json.dumps(CONFIG["settings"]))
        settings.update({k: json.loads(json.dumps(v)) for k, v in overrides.items()})
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            mgr.report_disabled(settings)
        return out.getvalue()

    def test_all_on_prints_nothing(self):
        self.assertEqual(self._report(), "")

    def test_lists_each_disabled_behaviour(self):
        out = self._report(
            danmaku={"enabled": False, "on_live": ["晚好"], "after_offline": ["1"],
                     "interval": {"min": 3, "max": 12}},
            like={"enabled": False, "target": 500, "batch": 10,
                  "interval": {"min": 1.0, "max": 3.0}},
            night_light={"enabled": False},
        )
        for word in ("弹幕", "点赞", "下播点亮"):
            self.assertIn(word, out)

    def test_notify_reported_when_off(self):
        """通知缺省是关的，日志里得能一眼看出「不是没跑，是你关了」。"""
        self.assertEqual(self._report(notify={"enabled": False}),
                         "  配置中已关闭：Discord 通知\n")

    def test_share_only_reported_when_both_sides_are_off(self):
        half = self._report(share={"on_live": False, "after_offline": True})
        both = self._report(share={"on_live": False, "after_offline": False})
        self.assertNotIn("分享", half)
        self.assertIn("分享", both)


MEMBER = {"name": "枯水", "uid": 699438, "room": 281}
CONFIG = {
    "members": [MEMBER],
    "active_hours": {"start": 21, "end": 1},
    "settings": {
        "danmaku": {"enabled": True, "on_live": ["晚好"], "after_offline": ["1"],
                    "interval": {"min": 3, "max": 12}},
        "like": {"enabled": True, "target": 500, "batch": 10,
                 "interval": {"min": 1.0, "max": 3.0}},
        "share": {"on_live": True, "after_offline": True},
        "night_light": {"enabled": True, "after_hour": 1},
        "notify": {"enabled": True},
    },
}


class MainWiringTests(_LockFixture):
    """main() 的三条分支各该拉起/放下什么。全程不联网、不起真进程。"""

    def setUp(self):
        super().setUp()
        self.cookie = Path(self._tmp.name) / ".cookies.json"
        self.cookie.write_text("{}")
        patcher = patch.object(mgr, "COOKIE_FILE", self.cookie)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, hour, live=False, argv=(), config=None):
        live_status = {"枯水": MEMBER} if live else {}
        with patch.object(sys, "argv", ["manage_asoul_heartbeat.py", *argv]), \
             patch.object(mgr, "current_hour", return_value=hour), \
             patch.object(mgr, "load_config", return_value=config or CONFIG), \
             patch.object(mgr, "load_members", return_value=[MEMBER]), \
             patch.object(mgr, "get_live_status", return_value=live_status), \
             patch.object(mgr, "start_heartbeat") as hb, \
             patch.object(mgr, "start_like") as like, \
             patch.object(mgr, "run_night_light") as night:
            rc = mgr.main()
        return rc, hb, like, night

    def test_live_member_gets_both_processes(self):
        rc, hb, like, night = self._run(hour=22, live=True)
        self.assertEqual(rc, 0)
        hb.assert_called_once_with(MEMBER)
        like.assert_called_once_with(MEMBER, settings=CONFIG["settings"])
        night.assert_not_called()

    def test_offline_member_gets_nothing(self):
        rc, hb, like, night = self._run(hour=22, live=False)
        self.assertEqual(rc, 0)
        hb.assert_not_called()
        like.assert_not_called()
        night.assert_not_called()

    def test_sleep_window_points_the_night_light(self):
        rc, hb, like, night = self._run(hour=2)
        self.assertEqual(rc, 0)
        hb.assert_not_called()
        like.assert_not_called()
        night.assert_called_once_with([MEMBER], CONFIG["settings"], only_names=None)

    def test_missing_cookie_is_an_error(self):
        self.cookie.unlink()
        rc, hb, like, night = self._run(hour=22, live=True)
        self.assertEqual(rc, 1)
        hb.assert_not_called()
        like.assert_not_called()
        night.assert_not_called()

    def test_ignore_window_forces_the_active_branch(self):
        """--ignore-window 在睡眠时段也要挂机（手动补挂用）。"""
        rc, hb, like, night = self._run(hour=2, live=True, argv=["--ignore-window"])
        self.assertEqual(rc, 0)
        hb.assert_called_once()
        night.assert_not_called()

    def _hangup_config(self, after_hour=1):
        config = json.loads(json.dumps(CONFIG))
        config["active_hours"] = {"start": 19, "end": 4}
        config["settings"]["night_light"]["after_hour"] = after_hour
        return config

    def test_hangup_window_still_lights_after_after_hour(self):
        """回归：挂机 19→4 时 2 点仍在时段内，从前点亮要拖到 4 点才做。"""
        rc, hb, like, night = self._run(hour=2, config=self._hangup_config())
        self.assertEqual(rc, 0)
        night.assert_called_once_with([MEMBER], CONFIG["settings"], only_names=None)

    def test_hangup_window_does_not_light_before_after_hour(self):
        rc, hb, like, night = self._run(hour=2, config=self._hangup_config(after_hour=3))
        self.assertEqual(rc, 0)
        night.assert_not_called()

    def test_all_live_skips_the_night_light_check(self):
        """全员还在播就别起子进程了——night_light 只会一个个跳过。"""
        rc, hb, like, night = self._run(hour=2, live=True, config=self._hangup_config())
        self.assertEqual(rc, 0)
        night.assert_not_called()


if __name__ == "__main__":
    unittest.main()