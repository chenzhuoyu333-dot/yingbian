"""高德路径规划解析测试：交通方式、距离、分钟数必须来自接口返回。"""

import os
import unittest
from unittest.mock import patch

from yingbian import poi
from yingbian.poi import Poi, choose_route, route_plan


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
        poi._ROUTE_FAILURES = 0

    def tearDown(self):
        patch.stopall()
        poi._ROUTE_CACHE.clear()
        poi._ROUTE_RETRY_AFTER = 0.0
        poi._ROUTE_FAILURES = 0

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

    # ── 多方式选择 ───────────────────────────────
    @staticmethod
    def _router(walk_s=0, bike_s=0, transit=None, drive_s=0):
        def fake(url: str) -> dict:
            if url.endswith("direction/walking") or "/direction/walking?" in url:
                return {"status": "1", "route": {"paths": [{"distance": "1200", "duration": str(walk_s)}]}}
            if "/direction/bicycling" in url:
                return {"errcode": "0", "data": {"paths": [{"distance": "1200", "duration": str(bike_s)}]}}
            if "/direction/transit/integrated" in url:
                return {"status": "1", "route": {"transits": transit or []}}
            if "/direction/driving" in url:
                return {"status": "1", "route": {"paths": [{"distance": "1200", "duration": str(drive_s)}]}}
            return {"status": "1", "route": {}}
        return fake

    @staticmethod
    def _transit(duration_s: int, walk_m: int, bus: str = "地铁1号线") -> dict:
        return {
            "duration": str(duration_s),
            "distance": "1200",
            "segments": [
                {"walking": {"distance": str(walk_m), "duration": "240"},
                 "bus": {"buslines": [{"name": bus}]}},
            ],
        }

    def test_walk_wins_only_when_clearly_faster_than_transit(self):
        a = _poi("A", 120.15, 30.25)
        b = _poi("B", 120.162, 30.25)   # 约 1.1 公里
        with patch("yingbian.poi._http_json", side_effect=self._router(
            walk_s=720, bike_s=1000, transit=[self._transit(1800, 300)]
        )):
            info = choose_route(a, b, "杭州")
        self.assertEqual(info["mode"], "walk")
        self.assertIn("快", info["chosenBy"])

    def test_transit_wins_when_walk_is_only_slightly_faster(self):
        a = _poi("A", 120.15, 30.25)
        b = _poi("B", 120.162, 30.25)
        with patch("yingbian.poi._http_json", side_effect=self._router(
            walk_s=960, bike_s=1300, transit=[self._transit(1200, 300)]
        )):
            info = choose_route(a, b, "杭州")
        self.assertEqual(info["mode"], "transit")

    def test_bike_can_beat_transit(self):
        a = _poi("A", 120.15, 30.25)
        b = _poi("B", 120.171, 30.25)   # 约 2 公里
        with patch("yingbian.poi._http_json", side_effect=self._router(
            walk_s=1800, bike_s=780, transit=[self._transit(1500, 300)]
        )):
            info = choose_route(a, b, "杭州")
        self.assertEqual(info["mode"], "bicycling")

    def test_avoid_walking_picks_transit_with_least_walking(self):
        a = _poi("A", 120.15, 30.25)
        b = _poi("B", 120.162, 30.25)
        transits = [
            self._transit(1200, 900, "地铁2号线"),
            self._transit(1440, 120, "地铁1号线"),
        ]
        with patch("yingbian.poi._http_json", side_effect=self._router(transit=transits)):
            info = choose_route(a, b, "杭州", avoid_walking=True)
        self.assertEqual(info["mode"], "transit")
        self.assertEqual(info["walkM"], 120)
        self.assertIn("少走路", info["chosenBy"])
        self.assertNotEqual(info["mode"], "walk")


if __name__ == "__main__":
    unittest.main()
