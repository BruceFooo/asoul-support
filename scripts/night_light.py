#!/usr/bin/env python3
"""E3：下播点亮。

活跃时段结束（默认 1 点）之后，若成员**不在直播**，则分享直播间并发送
`settings["danmaku"]["after_offline"]` 里的弹幕（默认 "1" 到 "10"），
每条之间随机间隔 `settings["danmaku"]["interval"]` 秒。

在直播就什么都不发——这条是硬规则，`--force` 也不行。

由 manage_asoul_heartbeat.py 在睡眠时段每 5 分钟调一次：房间还开着就跳过，
等它下播；一旦下播就当晚发一次，之后不再重复。

状态按房间存在 `.state/night_light/<room>.json`，记录已发到第几条，
进程被杀后接着发而不是重头再来。发送失败会记一次尝试，连续 3 次当晚放弃，
避免凭据失效之类的硬错误整晚空转刷接口。
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from asoul_members import ConfigError, load_config, load_members  # noqa: E402
from live_api import LiveClient, load_cookies  # noqa: E402
from local_time import in_active_window, local_date, local_hour  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / ".state" / "night_light"

# 同一晚最多尝试几次发送。超了就放弃，等下一天。
MAX_ATTEMPTS = 3


def _state_path(room: int) -> Path:
    return STATE_DIR / f"{room}.json"


def _fresh_state(today: str) -> Dict:
    return {"date": today, "shared": False, "sent": 0, "attempts": 0, "done": False}


def load_state(room: int, today: str) -> Dict:
    """读今晚的进度。跨天 / 文件损坏 / 内容非法一律当作全新一晚。"""
    path = _state_path(room)
    if not path.exists():
        return _fresh_state(today)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _fresh_state(today)
    if not isinstance(data, dict) or data.get("date") != today:
        return _fresh_state(today)

    state = _fresh_state(today)
    state["shared"] = data.get("shared") is True
    state["done"] = data.get("done") is True
    for key in ("sent", "attempts"):
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            state[key] = value
    return state


def save_state(room: int, state: Dict) -> None:
    path = _state_path(room)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _settled(member: Dict, today: str) -> bool:
    """这个房间今晚已经有结论了：发完了，或者已经放弃。"""
    state = load_state(member["room"], today)
    return state["done"] or state["attempts"] >= MAX_ATTEMPTS


def all_settled(members: List[Dict], today: Optional[str] = None) -> bool:
    """今晚所有房间都已有结论。

    manage 在睡眠时段每 5 分钟调一次本脚本；全好了就直接退出，
    不必再为了一无所获去打一次直播状态接口（一整夜下来是上百次）。
    """
    today = today or local_date()
    return bool(members) and all(_settled(m, today) for m in members)


def _result(member: Dict, state: Dict, total: int, reason: str) -> Dict:
    return {"name": member["name"], "room": member["room"], "sent": state["sent"],
            "total": total, "shared": state["shared"], "done": state["done"],
            "reason": reason}


def light_member(client: LiveClient, member: Dict, settings: Dict, *,
                 today: Optional[str] = None,
                 sleep: Optional[Callable[[float], None]] = None,
                 rng: random.Random = random) -> Dict:
    """分享并发送下播弹幕。调用方必须已经确认该房间**没有**在直播。

    sleep 默认留 None 而不是直接写 time.sleep：默认参数在定义时求值，
    写死之后测试就没法通过 patch time.sleep 来让 main() 跑得动。
    """
    sleep = sleep or time.sleep
    room = member["room"]
    danmaku = settings["danmaku"]
    messages: List[str] = danmaku["after_offline"]
    low, high = danmaku["interval"]["min"], danmaku["interval"]["max"]
    today = today or local_date()

    state = load_state(room, today)
    if state["done"]:
        return _result(member, state, len(messages), "今晚已点亮，跳过")
    if state["attempts"] >= MAX_ATTEMPTS:
        return _result(member, state, len(messages),
                       f"今晚已失败 {state['attempts']} 次，放弃")

    if settings["share"]["after_offline"] and not state["shared"]:
        resp = client.share(room)
        if resp.get("code") != 0:
            state["attempts"] += 1
            save_state(room, state)
            return _result(member, state, len(messages),
                           f"分享失败 {resp.get('code')}: {resp.get('message')}")
        state["shared"] = True
        save_state(room, state)

    # danmaku.enabled=false 时只分享、不发弹幕；进度照样收尾成 done，免得每 5 分钟重来。
    remaining = messages[state["sent"]:] if danmaku.get("enabled", True) else []
    for index, msg in enumerate(remaining):
        resp = client.send_danmaku(room, msg)
        if resp.get("code") != 0:
            state["attempts"] += 1
            save_state(room, state)
            return _result(member, state, len(messages),
                           f"第 {state['sent'] + 1} 条弹幕发送失败 "
                           f"{resp.get('code')}: {resp.get('message')}")
        state["sent"] += 1
        save_state(room, state)
        if index < len(remaining) - 1:
            sleep(rng.uniform(low, high))

    state["done"] = True
    save_state(room, state)
    reason = "已发送完毕" if remaining else "弹幕已关闭，只分享"
    return _result(member, state, len(messages), reason)


def parse_args():
    parser = argparse.ArgumentParser(description="下播后分享直播间并发送弹幕（每晚一次）")
    parser.add_argument("--members", help="只处理这些成员（逗号分隔），默认全部")
    parser.add_argument("--force", action="store_true",
                        help="忽略活跃时段限制，立刻执行（在直播的房间仍然跳过）")
    return parser.parse_args()


def _select(members: List[Dict], names_arg: Optional[str]) -> List[Dict]:
    if not names_arg:
        return members
    names = {n.strip() for n in names_arg.split(",") if n.strip()}
    unknown = names - {m["name"] for m in members}
    if unknown:
        print(f"WARN: 忽略未知成员 {sorted(unknown)}")
    return [m for m in members if m["name"] in names]


def main() -> int:
    args = parse_args()

    try:
        config = load_config()
        members = _select(load_members(require_room=True), args.members)
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1
    if not members:
        print("ERROR: 没有匹配到任何成员，退出。")
        return 1

    settings = config["settings"]
    if not settings["night_light"]["enabled"]:
        print("下播点亮已在配置中关闭（night_light.enabled = false），退出。")
        return 0

    start, end = config["active_hours"]["start"], config["active_hours"]["end"]
    hour = local_hour()
    if in_active_window(hour, start, end) and not args.force:
        print(f"当前 {hour:02d}:00 仍在活跃时段 {start:02d}:00-{end:02d}:00，不点亮。"
              f"（要强制执行加 --force）")
        return 0

    today = local_date()
    if all_settled(members, today):
        print("今晚所有房间都已点亮，跳过。")
        return 0

    cookies = load_cookies()
    if not cookies:
        print("ERROR: 找不到可用的 .cookies.json（需要 SESSDATA 与 bili_jct）。")
        return 1

    client = LiveClient(cookies["SESSDATA"], cookies["bili_jct"])
    status = client.live_status(members)

    failed = 0
    for member in members:
        if status.get(member["room"], {}).get("live_status"):
            print(f"{member['name']}（房间 {member['room']}）正在直播，不发。")
            continue
        try:
            result = light_member(client, member, settings, today=today)
        except Exception as exc:  # 单个成员出错不该拖垮其他成员
            print(f"{member['name']}：点亮失败 {type(exc).__name__}: {exc}")
            failed += 1
            continue
        share_note = "已分享" if result["shared"] else "未分享"
        print(f"{result['name']}（房间 {result['room']}）：{share_note}，"
              f"弹幕 {result['sent']}/{result['total']} 条 —— {result['reason']}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
