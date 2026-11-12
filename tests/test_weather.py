import json
import os
import unittest
from unittest.mock import patch

from yingbian.weather import DEMO_PROB, DEMO_TEXT, fetch_weather


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


HOURLY = {
    "code": "200",
    "hourly": [
        {"fxTime": "2026-11-14T15:00+08:00", "pop": "70", "text": "中雨"},
        {"fxTime": "2026-11-14T16:00+08:00", "pop": "60", "text": "小雨"},
    ]
}

RE_GEO = {"regeocode": {"addressComponent": {"adcode": "330106"}}}
AMAP_WEATHER = {
    "status": "1",
    "forecasts": [{"casts": [{"dayweather": "中雨", "nightweather": "小雨"}]}],
}

# 所有测试都用这三把 Key 的空/实组合，保证不会真发网络请求
QWEATHER_HOST = "abcdef.re.qweatherapi.com"


def env(**overrides):
    """把三个天气配置项全部显式设置，避免本地 .env 泄漏进测试"""
    base = {"QWEATHER_HOST": "", "QWEATHER_KEY": "", "AMAP_KEY": ""}
    base.update(overrides)
    return patch.dict(os.environ, base)


class WeatherTest(unittest.TestCase):
    def test_demo_when_no_key(self):
        with env():
            data = fetch_weather("30.27", "120.15")
        self.assertTrue(data["isDemo"])
        self.assertIn("未配置", data["source"])
        self.assertEqual(data["next2hRainProb"], DEMO_PROB)
        self.assertEqual(data["text"], DEMO_TEXT)
        self.assertEqual(data["basis"], "写死的演示值")

    def test_qweather_when_host_and_key_present(self):
        with env(QWEATHER_HOST=QWEATHER_HOST, QWEATHER_KEY="test-key"):
            with patch("yingbian.weather._get_json", return_value=HOURLY) as mocked:
                data = fetch_weather("30.27", "120.15")
        self.assertFalse(data["isDemo"])
        self.assertEqual(data["source"], "和风天气")
        self.assertEqual(data["next2hRainProb"], 0.7)
        self.assertEqual(data["text"], "15:00 起中雨")
        self.assertIn("location=120.15%2C30.27", mocked.call_args[0][0])
        self.assertIn(QWEATHER_HOST, mocked.call_args[0][0])

    def test_qweather_needs_host(self):
        """只有 Key 没有专属 Host 时，不能去调公共域名（会 403）"""
        with env(QWEATHER_KEY="test-key"):
            with patch("yingbian.weather._get_json") as mocked:
                data = fetch_weather("30.27", "120.15")
        self.assertTrue(data["isDemo"])
        mocked.assert_not_called()

    def test_amap_fallback_when_only_amap_key(self):
        payloads = [RE_GEO, AMAP_WEATHER]

        def fake_json(url):
            return payloads.pop(0)

        with env(AMAP_KEY="amap-key"):
            with patch("yingbian.weather._get_json", side_effect=fake_json) as mocked:
                data = fetch_weather("30.27", "120.15")

        self.assertFalse(data["isDemo"])
        self.assertEqual(data["source"], "高德天气")
        self.assertEqual(data["next2hRainProb"], 0.8)  # 含"雨" → 0.8
        self.assertEqual(data["text"], "中雨转小雨")
        self.assertIn("依据" if False else "高德当日预报文字", data["basis"])
        self.assertEqual(mocked.call_count, 2)  # regeo + weatherInfo

    def test_amap_dry_weather_is_low_prob(self):
        dry = {"status": "1", "forecasts": [{"casts": [{"dayweather": "晴", "nightweather": "晴"}]}]}
        payloads = [RE_GEO, dry]

        with env(AMAP_KEY="amap-key"):
            with patch(
                "yingbian.weather._get_json",
                side_effect=lambda url: payloads.pop(0),
            ):
                data = fetch_weather()
        self.assertEqual(data["next2hRainProb"], 0.1)
        self.assertEqual(data["text"], "晴")

    def test_qweather_failure_falls_back_to_amap(self):
        """和风挂了要用高德顶上，而不是直接降级成演示数据"""

        def pick(url):
            if QWEATHER_HOST in url:
                raise OSError("qweather down")
            if "regeo" in url:
                return RE_GEO
            return AMAP_WEATHER

        with env(QWEATHER_HOST=QWEATHER_HOST, QWEATHER_KEY="k", AMAP_KEY="a"):
            with patch("yingbian.weather._get_json", side_effect=pick):
                data = fetch_weather()
        self.assertFalse(data["isDemo"])
        self.assertEqual(data["source"], "高德天气")

    def test_all_providers_fail_gives_honest_demo(self):
        with env(QWEATHER_HOST=QWEATHER_HOST, QWEATHER_KEY="k", AMAP_KEY="a"):
            with patch("yingbian.weather._get_json", side_effect=OSError("boom")):
                data = fetch_weather()
        self.assertTrue(data["isDemo"])
        self.assertIn("获取失败", data["source"])
        self.assertIn("boom", data["note"])
        self.assertNotEqual(data["basis"], "")


if __name__ == "__main__":
    unittest.main()
