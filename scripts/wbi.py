#!/usr/bin/env python3
"""B 站 WBI 签名。

部分接口（例如直播间点赞 `likeReportV3`）要求 query 里带 `wts` + `w_rid`：

    w_rid = md5(按 key 排序后的 query + mixin_key)

`mixin_key` 由 `nav` 接口返回的 `img_key` / `sub_key` 按固定置换表重排后取前 32 位。

⚠️ 民间 API 文档库（bilibili-API-collect）已于 2026-01 被律师函关停，置换表与算法
细节无权威来源可查。此处按通行实现编写，**机制可用单元测试保证，正确性需以真实请求验证**。
"""

import hashlib
import time
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

# 把 img_key + sub_key 拼成的 64 字符重新排序，取前 32 位作 mixin_key
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_MIXIN_KEY_LEN = 32

# 签名前这些字符不能出现在参数值里
_STRIP = "!'()*"


class WbiError(Exception):
    """取不到 WBI 密钥（通常是登录态失效）。"""


def key_from_url(url: str) -> str:
    """从 `.../wbi/abcdef.webp` 取出 `abcdef`。"""
    return url.rsplit("/", 1)[-1].split(".")[0]


def mixin_key(img_key: str, sub_key: str) -> str:
    """按置换表把 img_key + sub_key 重排出 32 位密钥。"""
    raw = img_key + sub_key
    if len(raw) != 64:
        raise WbiError(f"img_key + sub_key 应为 64 字符，实际 {len(raw)}")
    return "".join(raw[i] for i in _MIXIN_KEY_ENC_TAB)[:_MIXIN_KEY_LEN]


def _clean(value) -> str:
    return str(value).translate(str.maketrans("", "", _STRIP))


def sign(params: Dict, mixin: str, wts: Optional[int] = None) -> Dict[str, str]:
    """给参数加上 `wts` 和 `w_rid`，返回可直接拼进 query 的字符串字典。

    必须先加 wts 再排序，否则签出来的 w_rid 对不上。
    """
    signed = {k: _clean(v) for k, v in params.items()}
    signed["wts"] = str(wts if wts is not None else int(time.time()))

    query = urllib.parse.urlencode(sorted(signed.items()))
    signed["w_rid"] = hashlib.md5((query + mixin).encode("utf-8")).hexdigest()
    return signed


def keys_from_nav(data: Dict) -> Tuple[str, str]:
    """从 nav 的返回体里取出 (img_key, sub_key)。纯函数，便于测试。"""
    if data.get("code") != 0:
        raise WbiError(f"nav 返回 code={data.get('code')}: {data.get('message')}"
                       "（登录态可能已失效）")

    wbi_img = (data.get("data") or {}).get("wbi_img") or {}
    img_url, sub_url = wbi_img.get("img_url"), wbi_img.get("sub_url")
    if not img_url or not sub_url:
        raise WbiError("nav 返回里没有 wbi_img.img_url / sub_url")

    return key_from_url(img_url), key_from_url(sub_url)


def fetch_keys(sessdata: str, bili_jct: str, timeout: int = 10) -> Tuple[str, str]:
    """自行发请求取密钥。调用方若已有统一的 HTTP 层，改用 keys_from_nav 更好。"""
    headers = {
        "User-Agent": _UA,
        "Cookie": f"SESSDATA={sessdata}; bili_jct={bili_jct}",
        "Referer": "https://www.bilibili.com",
    }
    req = urllib.request.Request(NAV_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except Exception as exc:
        raise WbiError(f"请求 nav 失败：{type(exc).__name__}: {exc}") from exc

    import json

    try:
        return keys_from_nav(json.loads(body))
    except ValueError as exc:
        raise WbiError(f"nav 返回的不是 JSON：{body[:200]}") from exc


class WbiSigner:
    """缓存 WBI 密钥的签名器——密钥一天一变，进程内取一次就够。

    `keys_provider` 是零参可调用对象，返回 (img_key, sub_key)。由调用方注入，
    这样 HTTP 层可以统一收口（`live_api` 传的是走 `_http` 的取法）。
    """

    def __init__(self, keys_provider):
        self._provider = keys_provider
        self._mixin: Optional[str] = None

    @property
    def mixin(self) -> str:
        if self._mixin is None:
            img_key, sub_key = self._provider()
            self._mixin = mixin_key(img_key, sub_key)
        return self._mixin

    def sign(self, params: Dict, wts: Optional[int] = None) -> Dict[str, str]:
        return sign(params, self.mixin, wts)
