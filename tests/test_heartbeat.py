import json
import sys
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


if __name__ == "__main__":
    unittest.main()
