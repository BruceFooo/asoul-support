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

    hours = {}
    for key in ("start", "end"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
            raise _fail(f"active_hours.{key} 必须是 0-23 的整数，实际是 {value!r}")
        hours[key] = value
    return hours


def load_config() -> Dict:
    """读取并校验配置，返回 {"members": [{name, uid, room?}, ...], "active_hours": {...}}。"""
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
    }


def load_members(require_room: bool = False) -> List[Dict]:
    """取成员列表。require_room=True 时缺少 room 直接报错（挂机/点亮链路需要）。"""
    members = load_config()["members"]
    if require_room:
        missing = [m["name"] for m in members if "room" not in m]
        if missing:
            raise _fail(f"以下成员缺少 room（该功能需要直播间号）：{'、'.join(missing)}")
    return members
