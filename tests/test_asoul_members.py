"""tests/test_asoul_members.py —— 共享配置模块的校验逻辑。

所有用例都必须 patch CONFIG_PATH，否则会读到项目根目录里的真实配置。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import asoul_members  # noqa: E402
from asoul_members import ConfigError, load_config, load_members, load_settings  # noqa: E402


class _ConfigFixture(unittest.TestCase):
    """提供 write_config({...}) → 把 CONFIG_PATH 指向临时文件并返回其路径。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write_config(self, payload, name: str = ".asoul_config.json") -> Path:
        path = self.dir / name
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        patcher = patch.object(asoul_members, "CONFIG_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    def use_missing_config(self) -> Path:
        path = self.dir / "no-such-config.json"
        patcher = patch.object(asoul_members, "CONFIG_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path


JARAN = {"name": "嘉然", "uid": 672328094, "room": 22637261}


class LoadConfigTests(_ConfigFixture):
    def test_loads_members_and_hours(self):
        self.write_config({
            "members": [JARAN, {"name": "贝拉", "uid": 672353429, "room": 22632424}],
            "active_hours": {"start": 21, "end": 1},
        })
        cfg = load_config()
        self.assertEqual([m["name"] for m in cfg["members"]], ["嘉然", "贝拉"])
        self.assertEqual(cfg["members"][0], JARAN)
        self.assertEqual(cfg["active_hours"], {"start": 21, "end": 1})

    def test_config_path_is_absolute_project_root(self):
        """路径必须基于 __file__ 而不是 CWD——manage 在 import 期就会 os.chdir()。"""
        self.assertTrue(asoul_members.CONFIG_PATH.is_absolute())
        self.assertEqual(asoul_members.CONFIG_PATH.parent, Path(asoul_members.__file__).resolve().parent.parent)

    def test_missing_active_hours_defaults_to_all_day(self):
        self.write_config({"members": [JARAN]})
        self.assertEqual(load_config()["active_hours"], {"start": 0, "end": 0})

    def test_room_is_optional(self):
        self.write_config({"members": [{"name": "嘉然", "uid": 672328094}]})
        self.assertEqual(load_config()["members"], [{"name": "嘉然", "uid": 672328094}])

    def test_name_is_stripped(self):
        self.write_config({"members": [{"name": "  嘉然  ", "uid": 1}]})
        self.assertEqual(load_config()["members"][0]["name"], "嘉然")

    def test_custom_non_asoul_member_loads(self):
        """配置是唯一数据源：加任意主播都应可用，不限于内置 5 人。"""
        self.write_config({"members": [{"name": "测试", "uid": 1, "room": 2}]})
        self.assertEqual(load_members(), [{"name": "测试", "uid": 1, "room": 2}])


class ConfigErrorTests(_ConfigFixture):
    def test_missing_file(self):
        path = self.use_missing_config()
        with self.assertRaises(ConfigError) as ctx:
            load_config()
        self.assertIn("找不到配置文件", str(ctx.exception))
        self.assertIn(str(path), str(ctx.exception))  # 错误信息要指路

    def test_broken_json(self):
        self.write_config("{ not json")
        with self.assertRaises(ConfigError):
            load_config()

    def test_root_not_object(self):
        self.write_config([JARAN])
        with self.assertRaises(ConfigError):
            load_config()

    def test_members_missing(self):
        self.write_config({"active_hours": {"start": 21, "end": 1}})
        with self.assertRaises(ConfigError):
            load_config()

    def test_members_empty(self):
        self.write_config({"members": []})
        with self.assertRaises(ConfigError):
            load_config()

    def test_member_not_object(self):
        self.write_config({"members": ["嘉然"]})
        with self.assertRaises(ConfigError):
            load_config()

    def test_name_missing_or_blank(self):
        for bad in ({}, {"name": ""}, {"name": "   "}, {"name": 123}):
            with self.subTest(bad=bad):
                self.write_config({"members": [{"uid": 1, **bad}]})
                with self.assertRaises(ConfigError):
                    load_config()

    def test_duplicate_name(self):
        self.write_config({"members": [JARAN, {"name": "嘉然", "uid": 999}]})
        with self.assertRaises(ConfigError) as ctx:
            load_config()
        self.assertIn("重复", str(ctx.exception))

    def test_uid_missing(self):
        self.write_config({"members": [{"name": "嘉然", "room": 22637261}]})
        with self.assertRaises(ConfigError) as ctx:
            load_config()
        self.assertIn("uid", str(ctx.exception))

    def test_uid_not_positive_int(self):
        for bad in (0, -1, "672328094", None, 1.0, True):
            with self.subTest(uid=bad):
                self.write_config({"members": [{"name": "嘉然", "uid": bad}]})
                with self.assertRaises(ConfigError):
                    load_config()

    def test_room_not_positive_int(self):
        for bad in (0, -5, "22637261"):
            with self.subTest(room=bad):
                self.write_config({"members": [{"name": "嘉然", "uid": 1, "room": bad}]})
                with self.assertRaises(ConfigError):
                    load_config()

    def test_active_hours_out_of_range(self):
        for bad in ({"start": 24, "end": 1}, {"start": -1, "end": 1},
                    {"start": 21}, {"start": 21, "end": "1"}, {"start": True, "end": 1}):
            with self.subTest(hours=bad):
                self.write_config({"members": [JARAN], "active_hours": bad})
                with self.assertRaises(ConfigError):
                    load_config()

    def test_active_hours_not_object(self):
        self.write_config({"members": [JARAN], "active_hours": [21, 1]})
        with self.assertRaises(ConfigError):
            load_config()


class RequireRoomTests(_ConfigFixture):
    def setUp(self):
        super().setUp()
        self.write_config({
            "members": [JARAN, {"name": "无房间主播", "uid": 42}],
        })

    def test_require_room_false_allows_missing(self):
        self.assertEqual(len(load_members()), 2)
        self.assertEqual(len(load_members(require_room=False)), 2)

    def test_require_room_true_raises_and_names_the_member(self):
        with self.assertRaises(ConfigError) as ctx:
            load_members(require_room=True)
        self.assertIn("无房间主播", str(ctx.exception))


class SettingsTests(_ConfigFixture):
    """danmaku / like / share 三段都可选，缺省用内置默认值。"""

    def _settings(self, **extra):
        self.write_config({"members": [JARAN], **extra})
        return load_settings()

    def test_defaults_when_absent(self):
        s = self._settings()
        self.assertEqual(s["danmaku"]["on_live"], ["晚好"])
        self.assertEqual(s["danmaku"]["after_offline"],
                         ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"])
        self.assertEqual(s["danmaku"]["interval"], {"min": 3, "max": 12})
        self.assertEqual(s["like"]["target"], 500)
        self.assertEqual(s["like"]["batch"], 10)
        self.assertEqual(s["like"]["interval"], {"min": 1.0, "max": 3.0})
        self.assertEqual(s["share"], {"on_live": True, "after_offline": True})

    def test_partial_danmaku_falls_back_per_field(self):
        s = self._settings(danmaku={"interval": {"min": 5, "max": 9}})
        self.assertEqual(s["danmaku"]["interval"], {"min": 5, "max": 9})
        self.assertEqual(s["danmaku"]["on_live"], ["晚好"])  # 未给的字段仍用默认

    def test_custom_values(self):
        s = self._settings(
            danmaku={"on_live": ["来了"], "after_offline": ["签到"], "interval": {"min": 1, "max": 2}},
            like={"target": 30, "interval": {"min": 0.5, "max": 1.5}},
            share={"on_live": False, "after_offline": True},
        )
        self.assertEqual(s["danmaku"]["on_live"], ["来了"])
        self.assertEqual(s["danmaku"]["after_offline"], ["签到"])
        self.assertEqual(s["like"]["target"], 30)
        self.assertEqual(s["share"], {"on_live": False, "after_offline": True})

    def test_like_target_must_be_positive_int(self):
        for bad in (0, -1, "500", 1.5, True, None):
            with self.subTest(target=bad):
                with self.assertRaises(ConfigError) as ctx:
                    self._settings(like={"target": bad})
                self.assertIn("like.target", str(ctx.exception))

    def test_like_batch_must_be_positive_int(self):
        for bad in (0, -1, "10", 1.5, True, None):
            with self.subTest(batch=bad):
                with self.assertRaises(ConfigError) as ctx:
                    self._settings(like={"batch": bad})
                self.assertIn("like.batch", str(ctx.exception))

    def test_interval_bounds(self):
        for bad in ({"min": 5, "max": 1}, {"min": -1, "max": 5},
                    {"min": 1}, {"min": "1", "max": 2}):
            with self.subTest(interval=bad):
                with self.assertRaises(ConfigError):
                    self._settings(danmaku={"interval": bad})

    def test_interval_error_names_the_field(self):
        with self.assertRaises(ConfigError) as ctx:
            self._settings(like={"interval": {"min": 9, "max": 1}})
        self.assertIn("like.interval.max", str(ctx.exception))

    def test_empty_or_blank_messages_rejected(self):
        for bad in ([], [""], ["   "], [123], "晚好"):
            with self.subTest(msgs=bad):
                with self.assertRaises(ConfigError) as ctx:
                    self._settings(danmaku={"on_live": bad})
                self.assertIn("danmaku.on_live", str(ctx.exception))

    def test_share_must_be_boolean(self):
        for bad in ("yes", 1, None):
            with self.subTest(value=bad):
                with self.assertRaises(ConfigError) as ctx:
                    self._settings(share={"on_live": bad})
                self.assertIn("share.on_live", str(ctx.exception))

    def test_section_must_be_object(self):
        for key in ("danmaku", "like", "share"):
            with self.subTest(section=key):
                with self.assertRaises(ConfigError):
                    self._settings(**{key: ["not", "an", "object"]})


class RealConfigTests(unittest.TestCase):
    """项目自带的 .asoul_config.json 必须能通过校验（CI 依赖它）。"""

    def test_repo_config_is_valid(self):
        config = load_config()
        self.assertGreater(len(config["members"]), 0)
        for member in load_members(require_room=True):
            self.assertTrue(member["name"])
            self.assertGreater(member["uid"], 0)
            self.assertGreater(member["room"], 0)
        hours = config["active_hours"]
        self.assertTrue(0 <= hours["start"] <= 23)
        self.assertTrue(0 <= hours["end"] <= 23)


if __name__ == "__main__":
    unittest.main()
