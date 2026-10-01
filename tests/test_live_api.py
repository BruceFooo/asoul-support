"""live_api / wbi 的单元测试。所有网络请求都被 patch 掉，不发真实请求。"""

import hashlib
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import live_api  # noqa: E402
import wbi  # noqa: E402
from live_api import LiveClient  # noqa: E402


# nav 的返回体：自己的 uid + WBI 密钥来源
NAV_OK = {
    "code": 0,
    "data": {
        "mid": 3690980884613679,
        "wbi_img": {
            "img_url": "https://i0.hdslb.com/bfs/wbi/" + "a" * 32 + ".png",
            "sub_url": "https://i0.hdslb.com/bfs/wbi/" + "b" * 32 + ".png",
        },
    },
}


def _fresh(payload):
    return json.loads(json.dumps(payload))


def _router(**overrides):
    """假的 _http：按 URL 分发，并记录所有调用。

    注意 config 里写的是短号 281，接口该用真实房间号 49728。
    """
    calls = []

    def fake_http(method, url, headers=None, data=None, timeout=10):
        calls.append({"method": method, "url": url, "headers": headers, "data": data})
        for key, resp in overrides.items():
            if key in url:
                return _fresh(resp)
        if live_api.NAV_URL in url:
            return _fresh(NAV_OK)
        if live_api.ROOM_INFO_URL in url:
            return {"code": 0, "data": {"room_id": 49728, "short_id": 281}}
        return {"code": 0}

    return fake_http, calls


def _calls_to(calls, needle):
    return [c for c in calls if needle in c["url"]]


# ── WBI ────────────────────────────────────────────────────

class MixinKeyTests(unittest.TestCase):
    def test_key_from_url(self):
        self.assertEqual(
            wbi.key_from_url("https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.webp"),
            "7cd084941338484aae1ad9425b84077c",
        )

    def test_mixin_key_is_permutation_prefix(self):
        img = "".join(chr(ord("a") + i % 26) for i in range(32))
        sub = "".join(chr(ord("A") + i % 26) for i in range(32))
        key = wbi.mixin_key(img, sub)

        self.assertEqual(len(key), 32)
        raw = img + sub
        # 逐位验证置换表确实被用了，而不是简单截断
        self.assertEqual(key, "".join(raw[i] for i in wbi._MIXIN_KEY_ENC_TAB)[:32])
        self.assertEqual(set(key), {raw[i] for i in wbi._MIXIN_KEY_ENC_TAB[:32]})
        self.assertNotEqual(key, raw[:32])

    def test_keys_from_nav_extracts_and_trims_extension(self):
        img_key, sub_key = wbi.keys_from_nav(_fresh(NAV_OK))
        self.assertEqual(img_key, "a" * 32)
        self.assertEqual(sub_key, "b" * 32)

    def test_keys_from_nav_rejects_error_payload(self):
        with self.assertRaises(wbi.WbiError):
            wbi.keys_from_nav({"code": -101, "message": "账号未登录"})

    def test_keys_from_nav_rejects_missing_wbi_img(self):
        with self.assertRaises(wbi.WbiError):
            wbi.keys_from_nav({"code": 0, "data": {}})

    def test_signer_fetches_key_once(self):
        calls = []

        def provider():
            calls.append(1)
            return "a" * 32, "b" * 32

        signer = wbi.WbiSigner(provider)
        signer.sign({"x": 1}, wts=1)
        signer.sign({"x": 2}, wts=2)
        self.assertEqual(len(calls), 1)

    def test_permutation_table_is_a_valid_permutation(self):
        self.assertEqual(len(wbi._MIXIN_KEY_ENC_TAB), 64)
        self.assertEqual(sorted(wbi._MIXIN_KEY_ENC_TAB), list(range(64)))

    def test_wrong_length_raises(self):
        with self.assertRaises(wbi.WbiError):
            wbi.mixin_key("short", "also-short")


class SignTests(unittest.TestCase):
    MIXIN = "0123456789abcdef0123456789abcdef"

    def _expected_rid(self, params: dict) -> str:
        query = urllib.parse.urlencode(sorted(params.items()))
        return hashlib.md5((query + self.MIXIN).encode()).hexdigest()

    def test_adds_wts_and_w_rid(self):
        signed = wbi.sign({"room_id": 281}, self.MIXIN, wts=1700000000)
        self.assertEqual(signed["wts"], "1700000000")
        self.assertEqual(len(signed["w_rid"]), 32)
        self.assertEqual(
            signed["w_rid"],
            self._expected_rid({"room_id": "281", "wts": "1700000000"}),
        )

    def test_params_are_sorted_before_signing(self):
        """顺序不同的同一组参数，签出来必须一致——否则服务端校验不过。"""
        a = wbi.sign({"b": 2, "a": 1}, self.MIXIN, wts=1)
        b = wbi.sign({"a": 1, "b": 2}, self.MIXIN, wts=1)
        self.assertEqual(a["w_rid"], b["w_rid"])

    def test_strips_filtered_chars_from_values(self):
        signed = wbi.sign({"msg": "he!llo'wo(rl)d*"}, self.MIXIN, wts=1)
        self.assertEqual(signed["msg"], "helloworld")
        self.assertEqual(
            signed["w_rid"],
            self._expected_rid({"msg": "helloworld", "wts": "1"}),
        )

    def test_different_mixin_gives_different_rid(self):
        a = wbi.sign({"x": 1}, self.MIXIN, wts=1)
        b = wbi.sign({"x": 1}, "f" * 32, wts=1)
        self.assertNotEqual(a["w_rid"], b["w_rid"])


# ── LiveClient ─────────────────────────────────────────────

def _client(buvid3="TESTBUVID") -> LiveClient:
    """默认注入固定的 buvid3——否则 headers() 会去网络取设备指纹。"""
    return LiveClient("SESS", "JCT", buvid3=buvid3)


class HeadersTests(unittest.TestCase):
    def test_carries_cookie_and_live_origin(self):
        headers = _client().headers(49728)
        self.assertIn("SESSDATA=SESS", headers["Cookie"])
        self.assertIn("bili_jct=JCT", headers["Cookie"])
        self.assertEqual(headers["Origin"], "https://live.bilibili.com")
        self.assertEqual(headers["Referer"], "https://live.bilibili.com/49728")

    def test_referer_without_room(self):
        self.assertEqual(_client().headers()["Referer"], "https://live.bilibili.com")


SPI_OK = {"code": 0, "data": {"b_3": "SPI-BUVID-3", "b_4": "SPI-BUVID-4"}}


class BuvidTests(unittest.TestCase):
    """点赞接口不带 buvid3 会被风控拦（-352）——实测过，必须带上。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / "buvid3.txt"
        patcher = patch.object(live_api, "_BUVID_CACHE", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_included_in_cookie_when_provided(self):
        self.assertTrue(_client().headers()["Cookie"].startswith("buvid3=TESTBUVID; "))

    def test_fetched_from_spi_and_cached_to_disk(self):
        with patch.object(live_api, "_http", return_value=_fresh(SPI_OK)) as http:
            headers = LiveClient("S", "J").headers()
        self.assertIn("buvid3=SPI-BUVID-3", headers["Cookie"])
        self.assertIn("finger/spi", http.call_args[0][1])
        self.assertEqual(self.cache.read_text(), "SPI-BUVID-3")

    def test_disk_cache_avoids_a_request(self):
        self.cache.write_text("CACHED-BUVID")
        with patch.object(live_api, "_http") as http:
            headers = LiveClient("S", "J").headers()
        http.assert_not_called()
        self.assertIn("buvid3=CACHED-BUVID", headers["Cookie"])

    def test_fetches_only_once_per_client(self):
        with patch.object(live_api, "_http", return_value=_fresh(SPI_OK)) as http:
            client = LiveClient("S", "J")
            client.headers()
            client.headers()
        self.assertEqual(http.call_count, 1)

    def test_failure_degrades_to_omitting_it(self):
        """取不到就只是不带这个 cookie，不能让整条链路挂掉。"""
        with patch.object(live_api, "_http", return_value={"code": -1, "message": "boom"}):
            cookie = LiveClient("S", "J").headers()["Cookie"]
        self.assertNotIn("buvid3", cookie)
        self.assertIn("SESSDATA=S", cookie)

    def test_empty_payload_is_not_cached(self):
        with patch.object(live_api, "_http", return_value={"code": 0, "data": {}}):
            cookie = LiveClient("S", "J").headers()["Cookie"]
        self.assertNotIn("buvid3", cookie)
        self.assertFalse(self.cache.exists())


class RealRoomIdTests(unittest.TestCase):
    def test_short_id_resolved_to_real_room(self):
        """配置里写浏览器地址栏的短号 281，接口要用真实房间号 49728。"""
        with patch.object(live_api, "_http",
                          return_value={"code": 0, "data": {"room_id": 49728}}) as http:
            self.assertEqual(_client().real_room_id(281), 49728)
        self.assertIn("room_id=281", http.call_args[0][1])

    def test_resolution_is_cached(self):
        with patch.object(live_api, "_http",
                          return_value={"code": 0, "data": {"room_id": 49728}}) as http:
            client = _client()
            client.real_room_id(281)
            client.real_room_id(281)
        self.assertEqual(http.call_count, 1)

    def test_falls_back_to_original_on_failure(self):
        """解析不出来时必须原样返回，不能破坏既有链路。"""
        for bad in ({"code": -1, "message": "boom"}, {"code": 0, "data": {}}):
            with self.subTest(resp=bad):
                with patch.object(live_api, "_http", return_value=bad):
                    self.assertEqual(_client().real_room_id(281), 281)

    def test_ignores_non_positive_room_id(self):
        with patch.object(live_api, "_http", return_value={"code": 0, "data": {"room_id": 0}}):
            self.assertEqual(_client().real_room_id(281), 281)


class UidTests(unittest.TestCase):
    def test_reads_mid_from_nav(self):
        with patch.object(live_api, "_http",
                          return_value={"code": 0, "data": {"mid": 3690980884613679}}):
            self.assertEqual(_client().uid, 3690980884613679)

    def test_caches_uid(self):
        with patch.object(live_api, "_http",
                          return_value={"code": 0, "data": {"mid": 42}}) as http:
            client = _client()
            client.uid
            client.uid
        self.assertEqual(http.call_count, 1)

    def test_not_logged_in_raises(self):
        with patch.object(live_api, "_http", return_value={"code": -101, "message": "未登录"}):
            with self.assertRaises(wbi.WbiError):
                _client().uid


class LikeTests(unittest.TestCase):
    """点赞是本方案里唯一没有依据的接口，参数形状必须与抓包一致。"""

    CAPTURE = {
        "click_time": 2,
        "room_id": 49728,
        "uid": 3690980884613679,
        "anchor_id": 699438,
        "web_location": "444.8",
    }

    def _call(self, click_time=2, room=49728):
        client = _client()
        fake, calls = _router()
        with patch.object(live_api, "_http", fake):
            client.like(room, anchor_uid=self.CAPTURE["anchor_id"], click_time=click_time)
        return client, _calls_to(calls, live_api.LIKE_URL)[0]

    def test_hits_like_report_v3(self):
        _, call = self._call()
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].startswith(live_api.LIKE_URL + "?"))

    def test_query_contains_captured_params(self):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self._call()[1]["url"]).query))
        for key, expected in self.CAPTURE.items():
            self.assertEqual(query[key], str(expected), f"{key} 与抓包不一致")

    def test_is_wbi_signed(self):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self._call()[1]["url"]).query))
        self.assertIn("wts", query)
        self.assertEqual(len(query["w_rid"]), 32)
        self.assertIn("csrf", query)

    def test_w_rid_matches_recomputed_signature(self):
        """用同一个 mixin_key 重算，验证 w_rid 确实是对整串参数签的。"""
        client, call = self._call()
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(call["url"]).query))

        wts = query.pop("wts")
        rid = query.pop("w_rid")
        resealed = wbi.sign(query, client._signer.mixin, wts=int(wts))
        self.assertEqual(rid, resealed["w_rid"])

    def test_empty_body(self):
        """抓包里是 content-length: 0，参数全在 query 上。"""
        self.assertIsNone(self._call()[1]["data"])

    def test_resolves_short_room_id(self):
        """配置里写 281（短号），点赞接口要用 49728。"""
        _, call = self._call(room=281)
        self.assertIn("room_id=49728", call["url"])

    def test_uid_taken_from_nav(self):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self._call()[1]["url"]).query))
        self.assertEqual(query["uid"], str(NAV_OK["data"]["mid"]))


class ShareTests(unittest.TestCase):
    def test_uses_trigger_interact_with_type_3(self):
        with patch.object(live_api, "_http", return_value={"code": 0}) as http:
            _client().share(49728)
        args = http.call_args
        self.assertEqual(args[0][1], live_api.INTERACT_URL)
        self.assertEqual(args[1]["data"]["roomid"], 49728)
        self.assertEqual(args[1]["data"]["interact_type"], live_api.SHARE_INTERACT_TYPE)
        self.assertEqual(args[1]["data"]["csrf"], "JCT")

    def test_no_wbi_needed(self):
        with patch.object(live_api, "_http", return_value={"code": 0}) as http:
            _client().share(49728)
        self.assertNotIn("w_rid", http.call_args[0][1])


class DanmakuTests(unittest.TestCase):
    def test_sends_to_msg_send_with_real_room(self):
        client = _client()
        client._rooms[281] = 49728
        with patch.object(live_api, "_http", return_value={"code": 0}) as http:
            client.send_danmaku(281, "晚好")
        args = http.call_args
        self.assertEqual(args[0][1], live_api.SEND_DANMAKU_URL)
        self.assertEqual(args[1]["data"]["msg"], "晚好")
        self.assertEqual(args[1]["data"]["roomid"], "49728")
        self.assertEqual(args[1]["data"]["csrf"], "JCT")


class LiveStatusTests(unittest.TestCase):
    def test_keys_by_configured_room_not_real_room(self):
        members = [{"name": "枯水", "uid": 699438, "room": 281}]
        body = {"code": 0, "data": {"699438": {"live_status": 1, "title": "直播中"}}}
        with patch.object(live_api.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = \
                __import__("json").dumps(body).encode()
            status = _client().live_status(members)
        self.assertTrue(status[281]["live_status"])
        self.assertEqual(status[281]["title"], "直播中")

    def test_network_failure_yields_all_offline(self):
        members = [{"name": "枯水", "uid": 699438, "room": 281}]
        with patch.object(live_api.urllib.request, "urlopen", side_effect=OSError("boom")):
            status = _client().live_status(members)
        self.assertEqual(status[281]["live_status"], 0)

    def test_empty_members(self):
        self.assertEqual(_client().live_status([]), {})


class HttpTests(unittest.TestCase):
    def test_never_raises_returns_error_dict(self):
        with patch.object(live_api.urllib.request, "urlopen", side_effect=OSError("down")):
            resp = live_api._http("GET", "https://example.com", {})
        self.assertEqual(resp["code"], -1)
        self.assertIn("down", resp["message"])

    def test_parses_json(self):
        with patch.object(live_api.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"code": 0}'
            self.assertEqual(live_api._http("GET", "https://example.com", {}), {"code": 0})


if __name__ == "__main__":
    unittest.main()
