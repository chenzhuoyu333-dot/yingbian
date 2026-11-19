"""高德路径规划解析测试：交通方式、距离、分钟数必须来自接口返回。"""

import os
import unittest
from unittest.mock import patch

from yingbian import poi
from yingbian.poi import Poi, route_plan


def _poi(pid: str, lng: float, lat: float) -> Poi:
    return Poi(
        id=pid,
        name=pid,
        category="sight",
        indoor=False,
        lng=lng,
        lat=lat,
        stay_min=60,
    )


class RoutePlanTest(unittest.TestCase):
    def setUp(self):
        patch.dict(os.environ, {"AMAP_KEY": "test-key"}).start()
        patch("yingbian.poi._throttle", lambda: None).start()
        poi._ROUTE_CACHE.clear()
        poi._ROUTE_RETRY_AFTER = 0.0

    def tearDown(self):
        patch.stopall()
        poi._ROUTE_CACHE.clear()
        poi._ROUTE_RETRY_AFTER = 0.0

    def test_transit_uses_amap_duration_and_line_name(self):
        payload = {
            "status": "1",
            "route": {
                "transits": [
                    {
                        "distance": "4500",
                        "duration": "1800",
                        "segments": [
                            {
                                "walking": {"distance": "300", "duration": "240"},
                                "bus": {"buslines": [{"name": "地铁1号线(湘湖--萧山国际机场)"}]},
                            }
                        ],
                    }
                ]
            },
        }
        with patch("yingbian.poi._http_json", return_value=payload):
            info = route_plan(_poi("A", 120.15, 30.25), _poi("B", 120.17, 30.24), "杭州", "transit")

        self.assertEqual(info["source"], "amap")
        self.assertEqual(info["distanceM"], 4500)
        self.assertEqual(info["durationMin"], 30)
        self.assertIn("地铁1号线", info["label"])
        self.assertIn("步行", info["label"])

    def test_walking_uses_amap_duration(self):
        payload = {
            "status": "1",
            "route": {"paths": [{"distance": "900", "duration": "720"}]},
        }
        with patch("yingbian.poi._http_json", return_value=payload):
            info = route_plan(_poi("A", 120.15, 30.25), _poi("B", 120.155, 30.25), "杭州", "walk")

        self.assertEqual(info["mode"], "walk")
        self.assertEqual(info["label"], "步行")
        self.assertEqual(info["durationMin"], 12)
        self.assertEqual(info["source"], "amap")

    def test_missing_route_falls_back_and_is_labeled_estimate(self):
        with patch("yingbian.poi._http_json", return_value={"status": "1", "route": {}}):
            info = route_plan(_poi("A", 120.15, 30.25), _poi("B", 120.17, 30.24), "杭州", "transit")

        self.assertEqual(info["source"], "estimate")
        self.assertIn("估算", info["text"])
        self.assertGreater(info["durationMin"], 0)


if __name__ == "__main__":
    unittest.main()
