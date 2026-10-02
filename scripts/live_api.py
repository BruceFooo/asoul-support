#!/usr/bin/env python3
"""B 站直播 API 客户端（唯一实现）。

此前 `checkin.py` 与 `heartbeat.py` 各自复制了一份 `send_danmaku` /
`check_live_status` / `_make_headers`。这里收敛成一处，并加上直播间点赞与分享。

所有网络请求都走 `_http()`，单元测试通过 patch 它来避免真实请求。
"""

import json
import random
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import wbi
from wbi import WbiError, WbiSigner

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

LIVE_HOST = "https://live.bilibili.com"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
# 设备指纹（buvid3）来源。公开接口，不需要登录。
BUVID_URL = "https://api.bilibili.com/x/frontend/finger/spi"
ROOM_INFO_URL = "https://api.live.bilibili.com/room/v1/Room/get_info"
LIVE_STATUS_URL = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"
SEND_DANMAKU_URL = "https://api.live.bilibili.com/msg/send"
MEDAL_PANEL_URL = "https://api.live.bilibili.com/xlive/app-ucenter/v1/fansMedal/panel"
MEDAL_WEAR_URL = "https://api.live.bilibili.com/xlive/web-room/v1/fansMedal/wear"

# 点赞：前端把若干次点击汇总后一次性上报，click_time 就是汇总的次数
LIKE_URL = "https://api.live.bilibili.com/xlive/app-ucenter/v1/like_info_v3/like/likeReportV3"
# 分享直播间：网页端点分享时登记分享的那个接口（主站接口，房间参数见 share()）
SHARE_ADD_URL = "https://api.bilibili.com/x/web-interface/share/add"
# 分享直播间时的互动上报：interact_type=3 即「分享」。返回体是 allow_mock（能不能
# 播放模拟互动特效），并不代表分享结果，所以它决定不了成败，见 share()。
INTERACT_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/TrigerInteract"
SHARE_INTERACT_TYPE = 3
# share/add 的「今天已经分享过」。对调用方来说目标已达成，按成功处理。
SHARE_ALREADY_DONE = 71000

_COOKIE_PATHS = [
    Path(__file__).resolve().parent.parent / ".cookies.json",
    Path(__file__).resolve().parent.parent.parent / "bilibili-live-checkin" / ".cookies.json",
]
_BUVID_CACHE = Path(__file__).resolve().parent.parent / ".state" / "buvid3.txt"


def _load_cached_buvid() -> Optional[str]:
    try:
        return _BUVID_CACHE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _save_buvid(value: str) -> None:
    try:
        _BUVID_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _BUVID_CACHE.write_text(value, encoding="utf-8")
    except OSError:
        pass


def _visit_id() -> str:
    """一次性的访问标识。网页端每次分享都带一个（形如 `caxa5nscgpc0`）。"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def load_cookies() -> Optional[Dict[str, str]]:
    for p in _COOKIE_PATHS:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("SESSDATA") and data.get("bili_jct"):
                return data
    return None


def _http(method: str, url: str, headers: dict, data: Optional[dict] = None,
          timeout: int = 10) -> Dict:
    """统一 HTTP 入口，永远返回 dict（失败时 code=-1），不抛异常。"""
    body = None
    headers = dict(headers)
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        return {"code": exc.code, "message": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"code": -1, "message": f"{type(exc).__name__}: {exc}"}


class LiveClient:
    """带 cookie 与进程内缓存的直播 API 客户端。

    缓存两样东西：自己的 uid、短号→真实房间号。两者进程内都不变。
    """

    def __init__(self, sessdata: str, bili_jct: str, buvid3: Optional[str] = None):
        self._sessdata = sessdata
        self._bili_jct = bili_jct
        self._uid: Optional[int] = None
        self._rooms: Dict[int, int] = {}
        self._room_info: Dict[int, Dict] = {}
        self._buvid3 = buvid3
        self._buvid_done = buvid3 is not None
        self._signer = WbiSigner(self._nav_keys)

    # ── 基础 ──────────────────────────────────────────────

    def _nav_keys(self):
        """WBI 密钥来源：走统一的 _http，便于测试整体 mock。"""
        return wbi.keys_from_nav(_http("GET", NAV_URL, self.headers()))

    def _buvid(self) -> Optional[str]:
        """设备指纹。取一次就缓存到 .state/buvid3.txt，跨进程保持同一个「设备」。

        点赞接口（likeReportV3）不带 buvid3 会直接被风控拦掉，返回 -352；
        补上之后同样的请求就能过。同一台机器上每次跑都换一个新 buvid3 反而更像
        异常客户端，所以落盘复用。
        """
        if not self._buvid_done:
            self._buvid_done = True
            self._buvid3 = _load_cached_buvid()
            if self._buvid3 is None:
                resp = _http("GET", BUVID_URL, {
                    "User-Agent": _UA, "Referer": "https://www.bilibili.com/",
                })
                value = (resp.get("data") or {}).get("b_3") if resp.get("code") == 0 else None
                if value:
                    self._buvid3 = value
                    _save_buvid(value)
        return self._buvid3

    def headers(self, referer_room: Optional[int] = None) -> dict:
        referer = f"{LIVE_HOST}/{referer_room}" if referer_room else LIVE_HOST
        cookie = f"SESSDATA={self._sessdata}; bili_jct={self._bili_jct}"
        buvid = self._buvid()
        if buvid:
            cookie = f"buvid3={buvid}; {cookie}"
        return {
            "User-Agent": _UA,
            "Cookie": cookie,
            "Origin": LIVE_HOST,
            "Referer": referer,
        }

    @property
    def uid(self) -> int:
        """自己的 uid。点赞接口要带它。"""
        if self._uid is None:
            resp = _http("GET", NAV_URL, self.headers())
            if resp.get("code") != 0:
                raise WbiError(f"取不到自己的 uid（登录态可能已失效）：{resp.get('message')}")
            self._uid = int((resp.get("data") or {}).get("mid") or 0)
            if not self._uid:
                raise WbiError("nav 返回里没有 mid")
        return self._uid

    def room_info(self, room: int) -> Dict:
        """短号对应的 get_info 原始 data，进程内缓存（分享要用的分区信息在里面）。

        解析失败返回空 dict 而不是抛异常：房间元数据只是锦上添花，拿不到就退回
        原样，绝不因为解析不出来而破坏既有链路。
        """
        if room not in self._room_info:
            resp = _http("GET", f"{ROOM_INFO_URL}?room_id={room}", self.headers(room))
            data = resp.get("data") if resp.get("code") == 0 else None
            self._room_info[room] = data if isinstance(data, dict) else {}
        return self._room_info[room]

    def real_room_id(self, room: int) -> int:
        """把短号（如 281）换成真实房间号（如 49728）。

        点赞等接口用的是真实房间号；配置里通常会写浏览器地址栏那个短号。
        解析失败时**原样返回**，绝不因为解析不出来而破坏既有链路。
        """
        if room not in self._rooms:
            candidate = self.room_info(room).get("room_id")
            self._rooms[room] = (candidate if isinstance(candidate, int) and candidate > 0
                                 else room)
        return self._rooms[room]

    # ── 查询 ──────────────────────────────────────────────

    def live_status(self, members: List[Dict]) -> Dict[int, Dict]:
        """批量查直播状态，返回 {配置里的房间号: {live_status, title, ...}}。"""
        result = {m["room"]: {"live_status": 0, "title": ""} for m in members}
        if not members:
            return result

        form = "&".join(f"uids[]={m['uid']}" for m in members)
        req = urllib.request.Request(
            LIVE_STATUS_URL, data=form.encode("utf-8"),
            headers={**self.headers(), "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return result

        if body.get("code") != 0 or not body.get("data"):
            return result

        uid_to_room = {m["uid"]: m["room"] for m in members}
        for uid_str, info in body["data"].items():
            try:
                uid = int(uid_str)
            except ValueError:
                continue
            if uid in uid_to_room:
                result[uid_to_room[uid]] = {
                    "live_status": info.get("live_status", 0),
                    "title": info.get("title", ""),
                    "area_name": info.get("area_v2_name", ""),
                }
        return result

    def get_my_medals(self) -> Dict[int, Dict]:
        """返回 {主播uid: {medal_id, medal_name, ...}}。"""
        medals: Dict[int, Dict] = {}
        page = 1
        while True:
            resp = _http("GET", f"{MEDAL_PANEL_URL}?page={page}&page_size=50", self.headers())
            if resp.get("code") != 0:
                break
            data = resp.get("data") or {}
            for item in data.get("list") or []:
                up_uid = (item.get("medal") or {}).get("target_id") or item.get("target_id")
                if up_uid:
                    medals[int(up_uid)] = item.get("medal") or item
            info = data.get("page_info") or {}
            if page >= (info.get("total_page") or 1):
                break
            page += 1
        return medals

    # ── 动作 ──────────────────────────────────────────────

    def send_danmaku(self, room: int, msg: str) -> Dict:
        real = self.real_room_id(room)
        return _http("POST", SEND_DANMAKU_URL, self.headers(real), data={
            "bubble": "0",
            "msg": msg,
            "color": "16777215",
            "mode": "1",
            "font_size": "25",
            "fontsize": "25",
            "rnd": str(int(time.time())),
            "roomid": str(real),
            "room_type": "0",
            "jumpfrom": "0",
            "reply_mid": "0",
            "reply_attr": "0",
            "replay_dmid": "",
            "statistics": json.dumps({"appId": 100, "platform": 5}),
            "csrf": self._bili_jct,
            "csrf_token": self._bili_jct,
        })

    def like(self, room: int, anchor_uid: int, click_time: int) -> Dict:
        """上报 click_time 次点赞。点满与否由服务端返回决定。"""
        real = self.real_room_id(room)
        params = {
            "click_time": click_time,
            "room_id": real,
            "uid": self.uid,
            "anchor_id": anchor_uid,
            "web_location": "444.8",
            "csrf": self._bili_jct,
        }
        signed = self._signer.sign(params)
        url = f"{LIKE_URL}?{urllib.parse.urlencode(sorted(signed.items()))}"
        return _http("POST", url, self.headers(real))

    def share(self, room: int) -> Dict:
        """分享直播间。返回 **登记分享** 的那个响应。

        网页端抓包显示点分享会发两个请求，职责完全不同：

        1. `x/web-interface/share/add`——真正登记分享。`area_id` / `parent_area_id`
           来自 get_info，`up_id` 是主播 uid。返回 0 表示登记成功，71000
           「重复分享」表示今天已经登记过，同样算达成目标（否则每晚重试到放弃）。
        2. `TrigerInteract(interact_type=3)`——互动上报，返回体是 `allow_mock`
           （能不能播放模拟互动特效），**跟分享有没有生效无关**。

        早先的版本只发了第 2 个、把 `code == 0` 当成分享成功，于是 B 站端
        一直没有任何分享记录。这里的成败一律以第 1 个为准，第 2 个照发但失败不影响。
        """
        info = self.room_info(room)
        real = self.real_room_id(room)

        resp = _http("POST", SHARE_ADD_URL, self.headers(real), data={
            "area_id": info.get("area_id", ""),
            "parent_area_id": info.get("parent_area_id", ""),
            "room_id": real,
            "up_id": info.get("uid", ""),
            "csrf": self._bili_jct,
            "csrf_token": self._bili_jct,
            "visit_id": _visit_id(),
        })
        if resp.get("code") == SHARE_ALREADY_DONE:
            # 今天已经分享过，对调用方来说目标已达成
            resp = {**resp, "code": 0, "message": "重复分享（今日已登记）"}

        _http("POST", INTERACT_URL, self.headers(real), data={
            "roomid": real,
            "interact_type": SHARE_INTERACT_TYPE,
            "csrf_token": self._bili_jct,
            "csrf": self._bili_jct,
            "visit_id": "",
        })
        return resp

    def wear_medal(self, medal_id: int) -> bool:
        resp = _http("POST", MEDAL_WEAR_URL, self.headers(), data={
            "medal_id": medal_id, "csrf": self._bili_jct, "csrf_token": self._bili_jct,
        })
        return resp.get("code") == 0
