import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import heartbeat  # noqa: E402


class X25KnTests(unittest.TestCase):
    def test_signing_vector(self):
        payload = (
            '{"platform":"web","parent_id":9,"area_id":371,"seq_id":1,'
            '"room_id":22632424,"buvid":"TEST-BUVID",'
            '"uuid":"00000000-0000-4000-8000-000000000000",'
            '"ets":1700000000,"time":60,"ts":1700000060000}'
        )

        result = heartbeat._x25kn_sign(
            payload,
            [2, 5, 1, 4],
            "seacasdgyijfhofiuxoannn",
        )

        self.assertEqual(
            result,
            "09159f943eb73570f2f6395b35291397f666444492e0c4e0197fcc7f509f850b"
            "37a06aade2a8d2657e367e400aacc0817d5fc0ca900a1bf33e9b6beb6d8eb91d",
        )

    @patch("heartbeat._now_ms", return_value=1700000060000)
    @patch("heartbeat._x25kn_post")
    def test_x_request_uses_server_interval_and_ruid(self, post, _now):
        post.return_value = {
            "code": 0,
            "data": {
                "timestamp": 1700000060,
                "heartbeat_interval": 60,
                "secret_key": "next-key",
                "secret_rule": [2, 5, 1, 4],
            },
        }

        result = heartbeat.x25kn_heartbeat(
            room_id=22632424,
            parent_id=9,
            area_id=371,
            up_id=672353429,
            seq=1,
            buvid="TEST-BUVID",
            uuid_str="00000000-0000-4000-8000-000000000000",
            ets=1700000000,
            secret_key="seacasdgyijfhofiuxoannn",
            secret_rule=[2, 5, 1, 4],
            heartbeat_interval=60,
            sessdata="secret",
            bili_jct="csrf",
        )

        self.assertEqual(result["secret_key"], "next-key")
        form = post.call_args.args[1]
        self.assertEqual(form["ruid"], 672353429)
        self.assertEqual(form["time"], 60)
        self.assertEqual(json.loads(form["id"]), [9, 371, 1, 22632424])

    @patch("heartbeat.time.sleep")
    @patch("heartbeat.time.monotonic", return_value=112.5)
    def test_wait_subtracts_work_already_spent(self, _monotonic, sleep):
        waited = heartbeat._wait_for_heartbeat_window(100.0, 60)

        self.assertEqual(waited, 47.5)
        sleep.assert_called_once_with(47.5)


class PidAliveTests(unittest.TestCase):
    """锁文件依赖进程存活探测；Windows 上 os.kill(pid, 0) 不可靠。"""

    def test_current_process_is_alive(self):
        import os

        self.assertTrue(heartbeat._pid_alive(os.getpid()))

    def test_dead_process_is_not_alive(self):
        import subprocess

        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        pid = proc.pid
        proc.wait()

        self.assertFalse(heartbeat._pid_alive(pid))

    def test_bogus_and_zero_pid_are_not_alive(self):
        self.assertFalse(heartbeat._pid_alive(0))
        self.assertFalse(heartbeat._pid_alive(999_999_999))

    def test_lock_dir_is_project_local_not_tmp(self):
        lock_dir = str(heartbeat._LOCK_DIR).replace("\\", "/")
        self.assertNotIn("/tmp/", lock_dir)
        self.assertIn(".state/locks", lock_dir)


class FakeClient:
    """顶掉真实网络调用，只记录发出去的动作。"""

    def __init__(self, share_resp=None, danmaku_resp=None):
        self.share_resp = share_resp if share_resp is not None else {"code": 0}
        self.danmaku_resp = danmaku_resp if danmaku_resp is not None else {"code": 0}
        self.share_calls = []
        self.danmaku_calls = []

    def share(self, room):
        self.share_calls.append(room)
        return self.share_resp

    def send_danmaku(self, room, msg):
        self.danmaku_calls.append({"room": room, "msg": msg})
        return self.danmaku_resp


SETTINGS = {
    "danmaku": {"on_live": ["晚好"], "after_offline": ["1"],
                "interval": {"min": 3, "max": 12}},
    "share": {"on_live": True, "after_offline": True},
}

TODAY = "2026-10-01"
ROOM = 281


class GreetingTests(unittest.TestCase):
    """开播问候每晚每房间只发一次——挂机进程崩了重启不能重复问候。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(heartbeat, "_GREETING_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        settings = patch.object(heartbeat, "SETTINGS", json.loads(json.dumps(SETTINGS)))
        settings.start()
        self.addCleanup(settings.stop)
        self.client = FakeClient()
        client_patcher = patch.object(heartbeat, "LiveClient", return_value=self.client)
        client_patcher.start()
        self.addCleanup(client_patcher.stop)

    def greet(self, today=TODAY):
        return heartbeat.open_live_greeting(ROOM, "sessdata", "csrf", today=today)

    def test_first_call_shares_and_sends_danmaku(self):
        self.assertTrue(self.greet())
        self.assertEqual(self.client.share_calls, [ROOM])
        self.assertEqual([c["msg"] for c in self.client.danmaku_calls], ["晚好"])

    def test_restart_same_night_does_not_greet_again(self):
        self.greet()
        self.assertTrue(self.greet())  # 模拟进程重启后又调一次
        self.assertEqual(self.client.share_calls, [ROOM])
        self.assertEqual(len(self.client.danmaku_calls), 1)

    def test_next_day_greets_again(self):
        self.greet()
        self.assertTrue(self.greet(today="2026-10-02"))
        self.assertEqual(len(self.client.danmaku_calls), 2)

    def test_each_room_has_its_own_state(self):
        self.greet()
        self.assertTrue(heartbeat.open_live_greeting(999, "sessdata", "csrf", today=TODAY))
        self.assertEqual(len(self.client.danmaku_calls), 2)

    def test_share_failure_does_not_block_danmaku(self):
        self.client.share_resp = {"code": -400, "message": "boom"}
        self.assertTrue(self.greet())
        self.assertEqual(len(self.client.danmaku_calls), 1)

    def test_share_retried_when_danmaku_failed(self):
        self.client.danmaku_resp = {"code": 10030, "message": "频率过快"}
        self.assertFalse(self.greet())
        self.assertEqual(len(self.client.danmaku_calls), 1)

        self.client.danmaku_resp = {"code": 0}
        self.assertTrue(self.greet())  # 补发弹幕
        self.assertEqual(self.client.share_calls, [ROOM])  # 分享不重复
        self.assertEqual(len(self.client.danmaku_calls), 2)

    def test_gives_up_after_max_attempts(self):
        self.client.danmaku_resp = {"code": 10030, "message": "频率过快"}
        for _ in range(heartbeat.MAX_GREETING_ATTEMPTS):
            self.assertFalse(self.greet())
        attempts = len(self.client.danmaku_calls)

        self.assertFalse(self.greet())  # 第 N+1 次直接放弃，不再请求
        self.assertEqual(len(self.client.danmaku_calls), attempts)

    def test_share_disabled_by_config(self):
        heartbeat.SETTINGS["share"] = {"on_live": False, "after_offline": True}
        self.assertTrue(self.greet())
        self.assertEqual(self.client.share_calls, [])
        self.assertEqual(len(self.client.danmaku_calls), 1)

    def test_falls_back_to_default_when_on_live_missing(self):
        heartbeat.SETTINGS["danmaku"] = {}
        self.assertTrue(self.greet())
        self.assertEqual([c["msg"] for c in self.client.danmaku_calls], ["晚好"])

    def test_corrupt_state_is_treated_as_fresh(self):
        path = Path(self.tmp.name) / f"{ROOM}.json"
        path.write_text("{{{ not json", encoding="utf-8")
        self.assertTrue(self.greet())
        self.assertEqual(len(self.client.danmaku_calls), 1)

    def test_state_survives_minor_vandalism(self):
        path = Path(self.tmp.name) / f"{ROOM}.json"
        path.write_text(json.dumps({"date": TODAY, "attempts": "many"}),
                        encoding="utf-8")
        self.assertTrue(self.greet())
        self.assertEqual(len(self.client.danmaku_calls), 1)


if __name__ == "__main__":
    unittest.main()
