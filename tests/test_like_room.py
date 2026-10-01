"""like_room 的单元测试。所有网络调用都被 FakeClient 顶掉，不发真实请求。"""

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import like_room  # noqa: E402

TODAY = "2026-10-01"

SETTINGS = {
    "danmaku": {"enabled": True, "on_live": ["晚好"], "after_offline": ["1"],
                "interval": {"min": 3, "max": 12}},
    "like": {"enabled": True, "target": 25, "batch": 10,
             "interval": {"min": 1.0, "max": 3.0}},
    "share": {"on_live": True, "after_offline": True},
    "night_light": {"enabled": True},
}

MEMBER = {"name": "枯水", "uid": 699438, "room": 281}


def _settings(**like_overrides):
    """复制一份设置并覆盖 like 段。"""
    s = json.loads(json.dumps(SETTINGS))
    s["like"].update(like_overrides)
    return s


class FakeClient:
    """记录调用并按队列返回响应。队列空了就返回 code=0。"""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.like_calls = []
        self.live = {}

    def like(self, room, anchor_uid, click_time):
        self.like_calls.append({"room": room, "anchor_uid": anchor_uid, "click_time": click_time})
        return self.responses.pop(0) if self.responses else {"code": 0}

    def live_status(self, members):
        return self.live


class _StateFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(like_room, "STATE_DIR", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sleeps = []
        self.rng = random.Random(20261001)

    def run_like(self, client, settings=None, member=None):
        return like_room.like_member(
            client, member or MEMBER, settings or _settings(),
            today=TODAY, sleep=self.sleeps.append, rng=self.rng,
        )


class ProgressStateTests(_StateFixture):
    def test_missing_file_is_zero(self):
        self.assertEqual(like_room.load_progress(281, TODAY), 0)

    def test_roundtrip(self):
        like_room.save_progress(281, TODAY, 30)
        self.assertEqual(like_room.load_progress(281, TODAY), 30)

    def test_other_day_is_zero(self):
        like_room.save_progress(281, "2026-09-30", 30)
        self.assertEqual(like_room.load_progress(281, TODAY), 0)

    def test_corrupt_file_is_zero(self):
        like_room.STATE_DIR.mkdir(parents=True, exist_ok=True)
        (like_room.STATE_DIR / "281.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(like_room.load_progress(281, TODAY), 0)

    def test_invalid_clicked_is_zero(self):
        for bad in (-1, 0, "30", None, True, 1.5):
            with self.subTest(clicked=bad):
                like_room.STATE_DIR.mkdir(parents=True, exist_ok=True)
                (like_room.STATE_DIR / "281.json").write_text(
                    json.dumps({"date": TODAY, "clicked": bad}), encoding="utf-8")
                self.assertEqual(like_room.load_progress(281, TODAY), 0)

    def test_state_file_is_per_room(self):
        like_room.save_progress(281, TODAY, 10)
        like_room.save_progress(999, TODAY, 3)
        self.assertEqual(like_room.load_progress(281, TODAY), 10)
        self.assertEqual(like_room.load_progress(999, TODAY), 3)


class IsDoneTests(_StateFixture):
    """manage 用它决定还要不要拉起点赞进程。"""

    def test_false_when_nothing_clicked(self):
        self.assertFalse(like_room.is_done(281, 25, TODAY))

    def test_false_below_target(self):
        like_room.save_progress(281, TODAY, 20)
        self.assertFalse(like_room.is_done(281, 25, TODAY))

    def test_true_at_target(self):
        like_room.save_progress(281, TODAY, 25)
        self.assertTrue(like_room.is_done(281, 25, TODAY))

    def test_false_again_the_next_day(self):
        like_room.save_progress(281, TODAY, 25)
        self.assertFalse(like_room.is_done(281, 25, "2026-10-02"))


class CreditedCountTests(unittest.TestCase):
    def test_reads_click_time(self):
        self.assertEqual(like_room.credited_count({"data": {"click_time": 7}}, 10), 7)

    def test_reads_add_count(self):
        self.assertEqual(like_room.credited_count({"data": {"add_count": 4}}, 10), 4)

    def test_missing_data_is_none(self):
        for resp in ({}, {"data": None}, {"data": []}, {"data": "x"}):
            with self.subTest(resp=resp):
                self.assertIsNone(like_room.credited_count(resp, 10))

    def test_unknown_fields_are_none(self):
        self.assertIsNone(like_room.credited_count({"data": {"foo": 3}}, 10))

    def test_room_total_like_count_is_not_mistaken_for_credit(self):
        """like_count 是房间总点赞数（可能上千万），绝不能当成这次承认的次数。"""
        self.assertIsNone(like_room.credited_count({"data": {"like_count": 9999999}}, 10))

    def test_out_of_range_is_none(self):
        for value in (-1, 11, True, "5", 1.5):
            with self.subTest(value=value):
                self.assertIsNone(like_room.credited_count({"data": {"click_time": value}}, 10))


class LikeMemberTests(_StateFixture):
    def test_clicks_until_target(self):
        client = FakeClient()
        result = self.run_like(client)  # target 25 / batch 10
        self.assertEqual([c["click_time"] for c in client.like_calls], [10, 10, 5])
        self.assertEqual(result["clicked"], 25)
        self.assertEqual(result["reason"], "已点满")

    def test_passes_room_and_anchor_uid(self):
        client = FakeClient()
        self.run_like(client)
        self.assertEqual(client.like_calls[0]["room"], 281)
        self.assertEqual(client.like_calls[0]["anchor_uid"], 699438)

    def test_sleeps_between_requests_but_not_after_the_last(self):
        client = FakeClient()
        self.run_like(client)
        self.assertEqual(len(client.like_calls), 3)
        self.assertEqual(len(self.sleeps), 2)

    def test_sleep_duration_is_within_configured_range(self):
        client = FakeClient()
        self.run_like(client, _settings(interval={"min": 0.1, "max": 0.4}))
        for value in self.sleeps:
            self.assertTrue(0.1 <= value <= 0.4, value)

    def test_batch_of_one(self):
        client = FakeClient()
        self.run_like(client, _settings(target=3, batch=1))
        self.assertEqual([c["click_time"] for c in client.like_calls], [1, 1, 1])

    def test_already_at_target_makes_no_calls(self):
        like_room.save_progress(281, TODAY, 25)
        client = FakeClient()
        result = self.run_like(client)
        self.assertEqual(client.like_calls, [])
        self.assertEqual(result["clicked"], 25)

    def test_progress_above_target_is_clamped(self):
        """配置调小 target 后，昨天存的大数字不能让它负数往下点。"""
        like_room.save_progress(281, TODAY, 900)
        client = FakeClient()
        result = self.run_like(client)
        self.assertEqual(client.like_calls, [])
        self.assertEqual(result["clicked"], 25)

    def test_resumes_from_saved_progress(self):
        like_room.save_progress(281, TODAY, 20)
        client = FakeClient()
        self.run_like(client)
        self.assertEqual([c["click_time"] for c in client.like_calls], [5])

    def test_previous_day_progress_does_not_carry_over(self):
        like_room.save_progress(281, "2026-09-30", 25)
        client = FakeClient()
        self.run_like(client)
        self.assertEqual(len(client.like_calls), 3)

    def test_saves_after_each_request(self):
        """点到一半进程被杀，已点次数必须已经落盘。"""
        client = FakeClient()
        self.run_like(client, _settings(target=30, batch=10))
        self.assertEqual(like_room.load_progress(281, TODAY), 30)

    def test_progress_is_saved_even_when_stopping_early(self):
        client = FakeClient([{"code": 0}, {"code": -403, "message": "访问权限不足"}])
        self.run_like(client)
        self.assertEqual(like_room.load_progress(281, TODAY), 10)

    def test_stops_on_error_code(self):
        client = FakeClient([{"code": 0}, {"code": -403, "message": "访问权限不足"}])
        result = self.run_like(client)
        self.assertEqual(len(client.like_calls), 2)  # 出错后不再重试
        self.assertEqual(result["clicked"], 10)
        self.assertIn("-403", result["reason"])

    def test_network_failure_code_minus_one_stops(self):
        client = FakeClient([{"code": -1, "message": "URLError: boom"}])
        result = self.run_like(client)
        self.assertEqual(len(client.like_calls), 1)
        self.assertEqual(result["clicked"], 0)
        self.assertIn("boom", result["reason"])

    def test_stops_when_server_credits_fewer_clicks(self):
        client = FakeClient([{"code": 0, "data": {"click_time": 3}}])
        result = self.run_like(client)
        self.assertEqual(len(client.like_calls), 1)
        self.assertEqual(result["clicked"], 3)
        self.assertIn("上限", result["reason"])

    def test_full_credit_keeps_going(self):
        client = FakeClient([{"code": 0, "data": {"click_time": 10}}] * 3)
        result = self.run_like(client)
        self.assertEqual(result["clicked"], 25)
        self.assertEqual(result["reason"], "已点满")

    def test_unknown_response_shape_counts_the_full_request(self):
        client = FakeClient([{"code": 0, "data": {"unexpected": 1}}] * 3)
        result = self.run_like(client)
        self.assertEqual(result["clicked"], 25)

    def test_does_not_sleep_after_hitting_the_cap(self):
        client = FakeClient([{"code": 0, "data": {"click_time": 2}}])
        self.run_like(client)
        self.assertEqual(self.sleeps, [])


class MainTests(_StateFixture):
    """main() 的分支：只对正在直播的房间点赞。"""

    def setUp(self):
        super().setUp()
        # main() 走的是真实的随机间隔，patch 掉免得每个用例真睡 1-3 秒
        sleeper = patch.object(like_room.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _run(self, client, argv=(), settings=None):
        with patch.object(sys, "argv", ["like_room.py", *argv]), \
                patch.object(like_room, "load_members", return_value=[MEMBER, dict(MEMBER, name="甲", room=999)]), \
                patch.object(like_room, "load_settings", return_value=settings or _settings()), \
                patch.object(like_room, "load_cookies", return_value={"SESSDATA": "s", "bili_jct": "j"}), \
                patch.object(like_room, "LiveClient", return_value=client):
            return like_room.main()

    def test_likes_live_rooms_only(self):
        client = FakeClient()
        client.live = {281: {"live_status": 1}, 999: {"live_status": 0}}
        self.assertEqual(self._run(client), 0)
        self.assertEqual([c["room"] for c in client.like_calls], [281] * 3)

    def test_disabled_in_config_makes_no_request(self):
        """like.enabled=false：手动跑也什么都不做。"""
        client = FakeClient()
        client.live = {281: {"live_status": 1}, 999: {"live_status": 0}}
        self.assertEqual(self._run(client, settings=_settings(enabled=False)), 0)
        self.assertEqual(client.like_calls, [])

    def test_no_cookies_is_an_error(self):
        client = FakeClient()
        with patch.object(sys, "argv", ["like_room.py"]), \
                patch.object(like_room, "load_members", return_value=[MEMBER]), \
                patch.object(like_room, "load_settings", return_value=_settings()), \
                patch.object(like_room, "load_cookies", return_value=None):
            self.assertEqual(like_room.main(), 1)

    def test_unknown_member_name_is_filtered_out(self):
        client = FakeClient()
        client.live = {281: {"live_status": 1}}
        self.assertEqual(self._run(client, ["--members", "不存在"]), 1)
        self.assertEqual(client.like_calls, [])

    def test_dry_run_makes_no_requests(self):
        client = FakeClient()
        with patch.object(sys, "argv", ["like_room.py", "--dry-run"]), \
                patch.object(like_room, "load_members", return_value=[MEMBER]), \
                patch.object(like_room, "load_settings", return_value=_settings()), \
                patch.object(like_room, "load_cookies", return_value=None), \
                patch.object(like_room, "LiveClient") as factory:
            self.assertEqual(like_room.main(), 0)
        factory.assert_not_called()
        self.assertEqual(client.like_calls, [])


if __name__ == "__main__":
    unittest.main()
