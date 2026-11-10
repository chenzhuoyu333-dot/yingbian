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
    "hourly": [
        {"fxTime": "2026-11-14T15:00+08:00", "pop": "70", "text": "中雨"},
        {"fxTime": "2026-11-14T16:00+08:00", "pop": "60", "text": "小雨"},
    ]
}


class WeatherTest(unittest.TestCase):
    def test_demo_when_key_missing(self):
        old = os.environ.pop("QWEATHER_KEY", None)
        try:
            data = fetch_weather("30.27", "120.15")
        finally:
            if old is not None:
                os.environ["QWEATHER_KEY"] = old
        self.assertTrue(data["isDemo"])
        self.assertIn("未配置", data["source"])
        self.assertEqual(data["next2hRainProb"], DEMO_PROB)
        self.assertEqual(data["text"], DEMO_TEXT)

    def test_real_payload_when_key_present(self):
        with patch.dict(os.environ, {"QWEATHER_KEY": "test-key"}):
            with patch("yingbian.weather.urllib.request.urlopen", return_value=_FakeResponse(HOURLY)) as mocked:
                data = fetch_weather("30.27", "120.15")
        self.assertFalse(data["isDemo"])
        self.assertEqual(data["source"], "和风天气")
        self.assertEqual(data["next2hRainProb"], 0.7)
        self.assertEqual(data["text"], "15:00 起中雨")
        self.assertIn("location=120.15%2C30.27", mocked.call_args[0][0])

    def test_failure_falls_back_to_demo(self):
        with patch.dict(os.environ, {"QWEATHER_KEY": "test-key"}):
            with patch("yingbian.weather.urllib.request.urlopen", side_effect=OSError("boom")):
                data = fetch_weather()
        self.assertTrue(data["isDemo"])
        self.assertIn("获取失败", data["source"])
        self.assertIn("boom", data["note"])


if __name__ == "__main__":
    unittest.main()
