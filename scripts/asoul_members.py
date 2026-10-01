#!/usr/bin/env python3
"""A-SOUL 成员配置加载（共享模块）。

成员的唯一数据源是项目根目录的 `.asoul_config.json`。
heartbeat / checkin / videos / dynamics / manage_asoul_heartbeat 全部从这里取成员，
避免把 uid / room 重复硬编码在多个文件里。
"""

import json
from pathlib import Path
from typing import Dict, List

CONFIG_PATH = Path(__file__).resolve().parent.parent / ".asoul_config.json"

_EXAMPLE = (
    '格式示例：{"members": [{"name": "嘉然", "uid": 672328094, "room": 22637261}], '
    '"active_hours": {"start": 21, "end": 1}}'
)


class ConfigError(Exception):
    """配置文件缺失或内容非法。"""


def _fail(msg: str) -> ConfigError:
    return ConfigError(f"{msg}\n配置文件：{CONFIG_PATH}\n{_EXAMPLE}")


def _positive_int(value, where: str) -> int:
    # 注意 bool 是 int 的子类，需显式排除
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _fail(f"{where} 必须是正整数，实际是 {value!r}")
    return value


def _parse_members(raw) -> List[Dict]:
    if not isinstance(raw, list) or not raw:
        raise _fail("配置缺少非空的 members 列表")

    members: List[Dict] = []
    seen = set()
    for index, item in enumerate(raw):
        where = f"members[{index}]"
        if not isinstance(item, dict):
            raise _fail(f'{where} 必须是对象，如 {{"name": "嘉然", "uid": 672328094, "room": 22637261}}')

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _fail(f"{where}.name 必须是非空字符串")
        name = name.strip()
        if name in seen:
            raise _fail(f"成员名重复：{name}")
        seen.add(name)

        member = {"name": name, "uid": _positive_int(item.get("uid"), f"{where}.uid")}
        if "room" in item:
            member["room"] = _positive_int(item["room"], f"{where}.room")
        members.append(member)
    return members


def _parse_hours(raw) -> Dict[str, int]:
    if raw is None:
        return {"start": 0, "end": 0}  # start == end 表示全天活跃
    if not isinstance(raw, dict):
        raise _fail('active_hours 必须是对象，如 {"start": 21, "end": 1}')

    return {key: _hour(raw.get(key), f"active_hours.{key}") for key in ("start", "end")}


_DEFAULT_SETTINGS = {
    "danmaku": {
        # false = 一条弹幕都不发（开播问候与下播点亮都只分享、不发弹幕）
        "enabled": True,
        # 开播时发的一条
        "on_live": ["晚好"],
        # 下播/未开播时发的编号弹幕
        "after_offline": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
        "interval": {"min": 3, "max": 12},
    },
    "like": {
        # false = 完全不起点赞进程
        "enabled": True,
        # 直播间点赞不涨亲密度、只加热度，且 B 站有未知的每日上限。
        # 默认取一个「一晚能点满、不至于整晚空转刷接口」的值，实测后可上调。
        "target": 500,
        # 每次请求汇总上报几次点击（网页前端就是这么攒着一起报的）。
        # 服务端若因这个值报错，调小它，最小是 1。
        "batch": 10,
        # 每次上报之间随机等待的秒数
        "interval": {"min": 1.0, "max": 3.0},
    },
    "share": {"on_live": True, "after_offline": True},
    "night_light": {
        # false = 下播点亮整段不做（不分享也不发弹幕）
        "enabled": True,
        # 几点之后可以点亮。与 active_hours 解耦：到了这个点，即使还在挂机
        # 时段内也照样检查「没在播就发」，这样挂机能一直到下播，点亮也不会被
        # 拖到挂机时段结束才做。
        "after_hour": 1,
    },
    "notify": {
        # false = 不发 Discord 开播/下播通知。默认关：通知靠外部的 openclaw CLI，
        # 没装 / 没登录的环境只会白起一个进程，不如让需要的人自己开。
        "enabled": False,
    },
}


def _number(value, where: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise _fail(f"{where} 必须是非负数，实际是 {value!r}")
    return value


def _interval(raw, where: str) -> Dict[str, float]:
    if not isinstance(raw, dict):
        raise _fail(f'{where} 必须是对象，如 {{"min": 3, "max": 12}}')
    low = _number(raw.get("min"), f"{where}.min")
    high = _number(raw.get("max"), f"{where}.max")
    if high < low:
        raise _fail(f"{where}.max（{high}）不能小于 min（{low}）")
    return {"min": low, "max": high}


def _messages(raw, where: str) -> List[str]:
    if not isinstance(raw, list) or not raw:
        raise _fail(f"{where} 必须是非空字符串数组")
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise _fail(f"{where}[{i}] 必须是非空字符串，实际是 {item!r}")
        out.append(item.strip())
    return out


def _bool_setting(raw, where: str) -> bool:
    if not isinstance(raw, bool):
        raise _fail(f"{where} 必须是 true 或 false，实际是 {raw!r}")
    return raw


def _hour(raw, where: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 23:
        raise _fail(f"{where} 必须是 0-23 的整数，实际是 {raw!r}")
    return raw


def _parse_settings(data: Dict) -> Dict:
    """把 danmaku / like / share / night_light / notify 五段与默认值合并，并校验。

    五段都可整段省略，缺省用内置默认值（notify 是唯一缺省为「关」的一段）。
    """
    raw = {key: data.get(key, {}) for key in _DEFAULT_SETTINGS}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise _fail(f"{key} 必须是对象")

    danmaku_raw, like_raw = raw["danmaku"], raw["like"]
    share_raw, nl_raw = raw["share"], raw["night_light"]
    notify_raw = raw["notify"]
    d_def = _DEFAULT_SETTINGS["danmaku"]
    l_def = _DEFAULT_SETTINGS["like"]
    s_def = _DEFAULT_SETTINGS["share"]
    n_def = _DEFAULT_SETTINGS["night_light"]
    nt_def = _DEFAULT_SETTINGS["notify"]

    target = like_raw.get("target", l_def["target"])
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        raise _fail(f"like.target 必须是正整数，实际是 {target!r}")

    batch = like_raw.get("batch", l_def["batch"])
    if isinstance(batch, bool) or not isinstance(batch, int) or batch <= 0:
        raise _fail(f"like.batch 必须是正整数，实际是 {batch!r}")

    return {
        "danmaku": {
            "enabled": _bool_setting(danmaku_raw.get("enabled", d_def["enabled"]),
                                     "danmaku.enabled"),
            "on_live": _messages(danmaku_raw.get("on_live", d_def["on_live"]),
                                 "danmaku.on_live"),
            "after_offline": _messages(danmaku_raw.get("after_offline", d_def["after_offline"]),
                                       "danmaku.after_offline"),
            "interval": _interval(danmaku_raw.get("interval", d_def["interval"]),
                                  "danmaku.interval"),
        },
        "like": {
            "enabled": _bool_setting(like_raw.get("enabled", l_def["enabled"]),
                                     "like.enabled"),
            "target": target,
            "batch": batch,
            "interval": _interval(like_raw.get("interval", l_def["interval"]),
                                  "like.interval"),
        },
        "share": {
            "on_live": _bool_setting(share_raw.get("on_live", s_def["on_live"]), "share.on_live"),
            "after_offline": _bool_setting(
                share_raw.get("after_offline", s_def["after_offline"]), "share.after_offline"),
        },
        "night_light": {
            "enabled": _bool_setting(nl_raw.get("enabled", n_def["enabled"]),
                                     "night_light.enabled"),
            "after_hour": _hour(nl_raw.get("after_hour", n_def["after_hour"]),
                                "night_light.after_hour"),
        },
        "notify": {
            "enabled": _bool_setting(
                notify_raw.get("enabled", nt_def["enabled"]), "notify.enabled"),
        },
    }


def load_config() -> Dict:
    """读取并校验配置。

    返回 {"members": [...], "active_hours": {...}, "settings": {...}}。
    """
    if not CONFIG_PATH.exists():
        raise _fail("找不到配置文件")

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _fail(f"配置文件读取失败：{type(exc).__name__}: {exc}")

    if not isinstance(data, dict):
        raise _fail("配置根节点必须是 JSON 对象")

    return {
        "members": _parse_members(data.get("members")),
        "active_hours": _parse_hours(data.get("active_hours")),
        "settings": _parse_settings(data),
    }


def load_settings() -> Dict:
    """只取弹幕 / 点赞 / 分享 / 下播点亮 / 通知五段设置（已填好默认值并校验）。"""
    return load_config()["settings"]


def load_members(require_room: bool = False) -> List[Dict]:
    """取成员列表。require_room=True 时缺少 room 直接报错（挂机/点亮链路需要）。"""
    members = load_config()["members"]
    if require_room:
        missing = [m["name"] for m in members if "room" not in m]
        if missing:
            raise _fail(f"以下成员缺少 room（该功能需要直播间号）：{'、'.join(missing)}")
    return members
