#!/usr/bin/env python3
"""E2：直播间点赞。

开播时由 manage_asoul_heartbeat.py 拉起，点满 settings["like"]["target"] 次后自行退出；
也可手动 `python scripts/like_room.py` 跑一次（只对正在直播的房间生效）。

B 站在服务端有未知的每日点赞上限。本脚本**不猜**这个上限：一旦接口返回非 0
（触顶、被风控都是这个形态），就如实记录已点次数并停止，不再重试。

注意接口有个已知的局限：成功时 `data` 恒为空，服务端不会告诉你这次实际认了几次。
所以「点满 500」只代表发够了请求，不代表服务端全部计入——这一点文档里也写明了。

进度按天存在 `.state/likes/<room>.json`，进程被杀 / 重启后接着点，不从头再来。

所有网络请求都走 `LiveClient`，单元测试通过替换 client 来避免真实请求。
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from asoul_members import ConfigError, load_members, load_settings  # noqa: E402
from live_api import LiveClient, load_cookies  # noqa: E402
from local_time import local_date  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / ".state" / "likes"

# 服务端「本次承认了几次」可能落在这些字段里。取不到就按请求次数记。
_CREDIT_KEYS = ("click_time", "add_count")


def _state_path(room: int) -> Path:
    return STATE_DIR / f"{room}.json"


def load_progress(room: int, today: str) -> int:
    """读今晚已点的次数。跨天 / 文件损坏 / 内容非法都当作 0。"""
    path = _state_path(room)
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(data, dict) or data.get("date") != today:
        return 0  # 新的一天，重新计数
    clicked = data.get("clicked")
    return clicked if isinstance(clicked, int) and not isinstance(clicked, bool) and clicked > 0 else 0


def save_progress(room: int, today: str, clicked: int) -> None:
    path = _state_path(room)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": today, "clicked": clicked}, ensure_ascii=False),
                    encoding="utf-8")


def is_done(room: int, target: int, today: Optional[str] = None) -> bool:
    """今晚是否已经点满。manage 用它避免点满之后每 5 分钟白起一个进程。"""
    return load_progress(room, today or local_date()) >= target


def credited_count(resp: Dict, requested: int) -> Optional[int]:
    """服务端实际承认了几次。返回 None 表示返回体里没有可用的信息。

    **实测（2026-10-02）：这个接口成功时返回 `{"code": 0, "data": {}}`，
    data 恒为空，所以本函数目前总是返回 None——「承认次数少于请求次数」这条
    判定不会触发。真正能拦住的上限信号只有 `code != 0`。**

    留着这段是因为它是唯一能从返回体里读出上限的入口：万一 B 站开始回传计数，
    这里立刻就能用上。字段名只认语义明确的几个，且必须落在 [0, requested] 内，
    否则宁可当作「不知道」——绝不能拿房间总点赞数（like_count 之类）当成
    这次承认的次数，那是数量级完全不同的两个东西。
    """
    data = resp.get("data")
    if not isinstance(data, dict):
        return None
    for key in _CREDIT_KEYS:
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= requested:
            return value
    return None


def like_member(client: LiveClient, member: Dict, settings: Dict, *,
                today: Optional[str] = None,
                sleep: Optional[Callable[[float], None]] = None,
                rng: random.Random = random) -> Dict:
    """把一个成员点到 target 次，返回本轮结果。

    today 在外层固定一次：跨零点运行的进程不会中途把进度清零重新点。

    sleep 默认留 None 而不是直接写 time.sleep：默认参数在定义时求值，
    写死之后测试就没法通过 patch time.sleep 来让 main() 跑得动。
    """
    sleep = sleep or time.sleep
    room = member["room"]
    target = settings["like"]["target"]
    batch = settings["like"]["batch"]
    low, high = settings["like"]["interval"]["min"], settings["like"]["interval"]["max"]
    today = today or local_date()

    clicked = min(load_progress(room, today), target)
    reason = "已点满"

    while clicked < target:
        n = min(batch, target - clicked)
        resp = client.like(room, anchor_uid=member["uid"], click_time=n)

        if resp.get("code") != 0:
            reason = f"接口返回 {resp.get('code')}: {resp.get('message')}（已停，不再重试）"
            break

        credited = credited_count(resp, n)
        clicked += n if credited is None else credited
        save_progress(room, today, clicked)

        if credited is not None and credited < n:
            reason = f"服务端本次只承认 {credited}/{n} 次，判定已接近每日上限"
            break

        if clicked < target:
            sleep(rng.uniform(low, high))

    return {"name": member["name"], "room": room, "clicked": clicked,
            "target": target, "reason": reason}


def parse_args():
    parser = argparse.ArgumentParser(description="给直播间点赞，点满配置的 target 次后停止")
    parser.add_argument("--members", help="只处理这些成员（逗号分隔），默认全部")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印目标与进度，不发任何请求")
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
        members = _select(load_members(require_room=True), args.members)
        settings = load_settings()
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1
    if not members:
        print("ERROR: 没有匹配到任何成员，退出。")
        return 1

    today = local_date()
    like = settings["like"]
    if args.dry_run:
        for m in members:
            done = load_progress(m["room"], today)
            print(f"{m['name']}（房间 {m['room']}）：今日已点 {done}/{like['target']}，"
                  f"每次上报 {like['batch']} 次，间隔 {like['interval']['min']}-{like['interval']['max']}s")
        return 0

    if not like["enabled"]:
        print("点赞已在配置中关闭（like.enabled = false），退出。")
        return 0

    cookies = load_cookies()
    if not cookies:
        print("ERROR: 找不到可用的 .cookies.json（需要 SESSDATA 与 bili_jct）。")
        return 1

    client = LiveClient(cookies["SESSDATA"], cookies["bili_jct"])
    status = client.live_status(members)

    failed = 0
    for member in members:
        if not status.get(member["room"], {}).get("live_status"):
            print(f"{member['name']}（房间 {member['room']}）未在直播，跳过。")
            continue
        try:
            result = like_member(client, member, settings, today=today)
        except Exception as exc:  # 单个成员出错不该拖垮其他成员
            print(f"{member['name']}：点赞失败 {type(exc).__name__}: {exc}")
            failed += 1
            continue
        print(f"{result['name']}（房间 {result['room']}）："
              f"共 {result['clicked']}/{result['target']} 次 —— {result['reason']}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
