"""night_light 的单元测试。所有网络调用都被 FakeClient 顶掉，不发真实请求。"""

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import night_light  # noqa: E402

TODAY = "2026-10-01"
MESSAGES = ["1", "2", "3"]

SETTINGS = {
    "danmaku": {"enabled": True, "on_live": ["晚好"], "after_offline": MESSAGES,
                "interval": {"min": 3, "max": 12}},
    "like": {"enabled": True, "target": 500, "batch": 10,
             "interval": {"min": 1.0, "max": 3.0}},
    "share": {"on_live": True, "after_offline": True},
    "night_light": {"enabled": True},
}

MEMBER = {"name": "枯水", "uid": 699438, "room": 281}

CONFIG = {"members": [MEMBER], "active_hours": {"start": 21, "end": 1}, "settings": SETTINGS}


def _settings(share=None, messages=None, interval=None,
              danmaku_enabled=None, night_light_enabled=None):
    s = json.loads(json.dumps(SETTINGS))
    if share is not None:
        s["share"] = share
    if messages is not None:
        s["danmaku"]["after_offline"] = messages
    if interval is not None:
        s["danmaku"]["interval"] = interval
    if danmaku_enabled is not None:
        s["danmaku"]["enabled"] = danmaku_enabled
    if night_light_enabled is not None:
        s["night_light"]["enabled"] = night_light_enabled
    return s


class FakeClient:
    def __init__(self, share_resp=None, danmaku_responses=None):
        self.share_resp = share_resp if share_resp is not None else {"code": 0}
        self.danmaku_responses = list(danmaku_responses or [])
        self.share_calls = []
        self.danmaku_calls = []
        self.live = {}

    def share(self, room):
        self.share_calls.append(room)
        return self.share_resp

    def send_danmaku(self, room, msg):
        self.danmaku_calls.append({"room": room, "msg": msg})
        return self.danmaku_responses.pop(0) if self.danmaku_responses else {"code": 0}

    def live_status(self, members):
        return self.live


class _StateFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(night_light, "STATE_DIR", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sleeps = []
        self.rng = random.Random(20261001)

    def run_light(self, client, settings=None, member=None):
        return night_light.light_member(
            client, member or MEMBER, settings or _settings(),
            today=TODAY, sleep=self.sleeps.append, rng=self.rng,
        )

    def save(self, room, **fields):
        night_light.STATE_DIR.mkdir(parents=True, exist_ok=True)
        state = {"date": TODAY, "shared": False, "sent": 0, "attempts": 0, "done": False}
        state.update(fields)
        state.setdefault("date", TODAY)
        (night_light.STATE_DIR / f"{room}.json").write_text(
            json.dumps(state), encoding="utf-8")


class StateTests(_StateFixture):
    def test_missing_file_is_fresh(self):
        self.assertEqual(night_light.load_state(281, TODAY),
                         {"date": TODAY, "shared": False, "sent": 0, "attempts": 0, "done": False})

    def test_other_day_is_fresh(self):
        self.save(281, sent=3, done=True)
        self.assertEqual(night_light.load_state(281, "2026-10-02")["done"], False)

    def test_other_day_resets_attempts(self):
        self.save(281, attempts=3)
        self.assertEqual(night_light.load_state(281, "2026-10-02")["attempts"], 0)

    def test_corrupt_file_is_fresh(self):
        night_light.STATE_DIR.mkdir(parents=True, exist_ok=True)
        (night_light.STATE_DIR / "281.json").write_text("nope", encoding="utf-8")
        self.assertEqual(night_light.load_state(281, TODAY)["sent"], 0)

    def test_roundtrip(self):
        state = night_light.load_state(281, TODAY)
        state.update({"shared": True, "sent": 2, "attempts": 1})
        night_light.save_state(281, state)
        self.assertEqual(night_light.load_state(281, TODAY),
                         {"date": TODAY, "shared": True, "sent": 2, "attempts": 1, "done": False})

    def test_coerces_bad_field_types(self):
        self.save(281, sent="2", attempts=None, done="yes", shared=1)
        state = night_light.load_state(281, TODAY)
        self.assertEqual(state["sent"], 0)
        self.assertEqual(state["attempts"], 0)
        self.assertIs(state["done"], False)
        self.assertIs(state["shared"], False)


class LightMemberTests(_StateFixture):
    def test_shares_then_sends_every_message_in_order(self):
        client = FakeClient()
        result = self.run_light(client)
        self.assertEqual(client.share_calls, [281])
        self.assertEqual([c["msg"] for c in client.danmaku_calls], MESSAGES)
        self.assertEqual([c["room"] for c in client.danmaku_calls], [281] * 3)
        self.assertEqual(result["sent"], 3)
        self.assertTrue(result["done"])
        self.assertEqual(result["reason"], "已发送完毕")

    def test_sleeps_between_messages_but_not_after_the_last(self):
        client = FakeClient()
        self.run_light(client)
        self.assertEqual(len(self.sleeps), 2)

    def test_sleep_duration_is_within_configured_range(self):
        client = FakeClient()
        self.run_light(client, _settings(interval={"min": 0.5, "max": 0.8}))
        for value in self.sleeps:
            self.assertTrue(0.5 <= value <= 0.8, value)

    def test_skips_when_already_done_tonight(self):
        self.save(281, sent=3, shared=True, done=True)
        client = FakeClient()
        result = self.run_light(client)
        self.assertEqual(client.danmaku_calls, [])
        self.assertEqual(client.share_calls, [])
        self.assertIn("已点亮", result["reason"])

    def test_skips_after_max_attempts(self):
        self.save(281, attempts=night_light.MAX_ATTEMPTS)
        client = FakeClient()
        result = self.run_light(client)
        self.assertEqual(client.danmaku_calls, [])
        self.assertIn("放弃", result["reason"])

    def test_share_can_be_turned_off(self):
        client = FakeClient()
        result = self.run_light(client, _settings(share={"on_live": True, "after_offline": False}))
        self.assertEqual(client.share_calls, [])
        self.assertEqual(len(client.danmaku_calls), 3)
        self.assertFalse(result["shared"])

    def test_share_happens_only_once_across_restarts(self):
        self.save(281, shared=True)
        client = FakeClient()
        self.run_light(client)
        self.assertEqual(client.share_calls, [])

    def test_share_failure_counts_an_attempt_and_aborts(self):
        client = FakeClient(share_resp={"code": -101, "message": "账号未登录"})
        result = self.run_light(client)
        self.assertEqual(client.danmaku_calls, [])
        self.assertEqual(result["sent"], 0)
        self.assertIn("分享失败", result["reason"])
        self.assertEqual(night_light.load_state(281, TODAY)["attempts"], 1)

    def test_share_failure_does_not_mark_done(self):
        client = FakeClient(share_resp={"code": -101, "message": "x"})
        self.run_light(client)
        self.assertFalse(night_light.load_state(281, TODAY)["done"])

    def test_danmaku_failure_aborts_and_keeps_progress(self):
        client = FakeClient(danmaku_responses=[{"code": 0}, {"code": 1003212, "message": "超出限制"}])
        result = self.run_light(client)
        self.assertEqual(result["sent"], 1)  # 第一条已发出去
        self.assertIn("第 2 条", result["reason"])
        client2 = FakeClient()
        self.run_light(client2)  # 重试时从第 2 条接着发
        self.assertEqual([c["msg"] for c in client2.danmaku_calls], ["2", "3"])

    def test_resumes_from_partial_progress(self):
        self.save(281, sent=2, shared=True)
        client = FakeClient()
        self.run_light(client)
        self.assertEqual([c["msg"] for c in client.danmaku_calls], ["3"])

    def test_previous_day_does_not_block_tonight(self):
        self.save(281, date="2026-09-30", sent=3, shared=True, done=True)
        client = FakeClient()
        self.run_light(client)
        self.assertEqual(len(client.danmaku_calls), 3)  # 状态是新一天的
        self.assertEqual(client.share_calls, [281])

    def test_progress_above_message_count_is_handled(self):
        """配置把弹幕条数调少之后，旧的 sent 不能变成负数下标。"""
        self.save(281, sent=99, shared=True)
        client = FakeClient()
        result = self.run_light(client)
        self.assertEqual(client.danmaku_calls, [])
        self.assertTrue(result["done"])

    def test_custom_messages(self):
        client = FakeClient()
        self.run_light(client, _settings(messages=["晚安"]))
        self.assertEqual([c["msg"] for c in client.danmaku_calls], ["晚安"])
        self.assertEqual(self.sleeps, [])

    def test_danmaku_disabled_share_only(self):
        """danmaku.enabled=false：只分享，且照样收尾成 done，免得每 5 分钟重来。"""
        client = FakeClient()
        result = self.run_light(client, _settings(danmaku_enabled=False))

        self.assertEqual(client.share_calls, [281])
        self.assertEqual(client.danmaku_calls, [])
        self.assertTrue(result["done"])
        self.assertEqual(result["reason"], "弹幕已关闭，只分享")
        self.assertTrue(night_light.load_state(281, TODAY)["done"])


class MainTests(_StateFixture):
    def setUp(self):
        super().setUp()
        # main() 走的是真实的随机间隔，patch 掉免得每个用例真睡 3-12 秒
        sleeper = patch.object(night_light.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _run(self, client, config=None, argv=(), hour=2):
        with patch.object(sys, "argv", ["night_light.py", *argv]), \
                patch.object(night_light, "load_config", return_value=config or CONFIG), \
                patch.object(night_light, "load_members", return_value=[MEMBER]), \
                patch.object(night_light, "load_cookies", return_value={"SESSDATA": "s", "bili_jct": "j"}), \
                patch.object(night_light, "local_hour", return_value=hour), \
                patch.object(night_light, "LiveClient", return_value=client):
            return night_light.main()

    def test_sends_when_room_is_offline(self):
        client = FakeClient()
        client.live = {281: {"live_status": 0}}
        self.assertEqual(self._run(client), 0)
        self.assertEqual(len(client.danmaku_calls), 3)

    def test_disabled_in_config_makes_no_request(self):
        """night_light.enabled=false：整段不做，连直播状态都不查。"""
        client = FakeClient()
        config = json.loads(json.dumps(CONFIG))
        config["settings"]["night_light"]["enabled"] = False
        self.assertEqual(self._run(client, config=config), 0)
        self.assertEqual(client.danmaku_calls, [])
        self.assertEqual(client.share_calls, [])

    def test_skips_while_still_live(self):
        """硬规则：在直播就什么都不发，也不会被记成一次失败。"""
        client = FakeClient()
        client.live = {281: {"live_status": 1, "title": "直播中"}}
        self.assertEqual(self._run(client), 0)
        self.assertEqual(client.danmaku_calls, [])
        self.assertEqual(client.share_calls, [])
        self.assertEqual(night_light.load_state(281, TODAY)["attempts"], 0)

    def test_refuses_during_active_window(self):
        client = FakeClient()
        client.live = {281: {"live_status": 0}}
        self.assertEqual(self._run(client, hour=22), 0)
        self.assertEqual(client.danmaku_calls, [])

    def test_force_overrides_the_window(self):
        client = FakeClient()
        client.live = {281: {"live_status": 0}}
        self.assertEqual(self._run(client, argv=["--force"], hour=22), 0)
        self.assertEqual(len(client.danmaku_calls), 3)

    def test_force_still_respects_the_live_rule(self):
        client = FakeClient()
        client.live = {281: {"live_status": 1}}
        self.assertEqual(self._run(client, argv=["--force"], hour=22), 0)
        self.assertEqual(client.danmaku_calls, [])

    def test_skips_without_any_request_when_all_settled(self):
        """睡眠时段每 5 分钟跑一次；全好了就不该再为了一无所获去打接口。"""
        # main() 用的是真实当天日期，状态文件也必须按它写
        self.save(281, date=night_light.local_date(), sent=99, shared=True, done=True)
        client = FakeClient()
        with patch.object(night_light, "LiveClient") as factory:
            self.assertEqual(self._run(client), 0)
        factory.assert_not_called()
        self.assertEqual(client.danmaku_calls, [])

    def test_still_works_when_one_room_is_unsettled(self):
        client = FakeClient()
        client.live = {281: {"live_status": 0}, 999: {"live_status": 1}}
        with patch.object(night_light, "load_members",
                          return_value=[MEMBER, {"name": "甲", "uid": 1, "room": 999}]):
            with patch.object(sys, "argv", ["night_light.py"]), \
                    patch.object(night_light, "load_config", return_value=CONFIG), \
                    patch.object(night_light, "load_cookies",
                                 return_value={"SESSDATA": "s", "bili_jct": "j"}), \
                    patch.object(night_light, "local_hour", return_value=2), \
                    patch.object(night_light, "LiveClient", return_value=client):
                self.assertEqual(night_light.main(), 0)
        self.assertEqual([c["room"] for c in client.danmaku_calls], [281] * 3)

    def test_no_cookies_is_an_error(self):
        client = FakeClient()
        client.live = {281: {"live_status": 0}}
        with patch.object(sys, "argv", ["night_light.py"]), \
                patch.object(night_light, "load_config", return_value=CONFIG), \
                patch.object(night_light, "load_members", return_value=[MEMBER]), \
                patch.object(night_light, "load_cookies", return_value=None), \
                patch.object(night_light, "local_hour", return_value=2):
            self.assertEqual(night_light.main(), 1)


if __name__ == "__main__":
    unittest.main()
