"""定位驱动的"落后判断"测试。

场景（比赛里要演的那一段）：
  17:00 本该到下一站，人还停在上一个点 → 系统应该自己发现落后，并给出改法。

守的几件事：
  1. 准点/人就在该在的点上 → on_track，不打扰用户
  2. 人在上一个点、时间已过下一站 → behind，并给出落后分钟数
  3. 落后少 → 同时给「缩短当前停留」和「整体顺延」
  4. 落后太多（停留时长不够扣）→ 不给缩短方案，只给顺延
  5. 离所有计划点都很远 → unknown，不乱判断
  6. 没有坐标的计划 → no_location_data，不瞎猜
"""

import unittest
from unittest.mock import patch

from yingbian.generate import Preferences, generate
from yingbian.location import locate
from yingbian.models import Node, Plan

POIS = [
    ("B1", "博物馆甲", "科教文化服务;博物馆", "120.160,30.245"),
    ("B2", "咖啡馆乙", "餐饮服务;咖啡厅", "120.165,30.248"),
    ("B3", "公园丙", "风景名胜;公园", "120.170,30.243"),
    ("B4", "老街丁", "风景名胜;风景名胜", "120.172,30.246"),
    ("B5", "美术馆戊", "科教文化服务;美术馆", "120.168,30.250"),
    ("B6", "书店己", "购物服务;书店", "120.163,30.241"),
]


def fake_http(url: str) -> dict:
    return {
        "status": "1",
        "count": str(len(POIS)),
        "pois": [
            {"id": pid, "name": name, "type": t, "location": loc}
            for pid, name, t, loc in POIS
        ],
    }


def build_plan() -> Plan:
    with patch("yingbian.poi._throttle", lambda: None), patch(
        "yingbian.poi._http_json", side_effect=fake_http
    ), patch.dict("os.environ", {"AMAP_KEY": "test", "YINGBIAN_OFFLINE_ROUTE": "1"}):
        from yingbian import poi

        poi._CACHE.clear()
        raw = generate(Preferences(city="杭州", interests=["博物馆", "咖啡"], max_transit_min=45))
    return Plan.from_dict(raw)


class LocateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = build_plan()
        cls.points = [
            (n, (n.poi or {}).get("lat"), (n.poi or {}).get("lng"))
            for n in cls.plan.nodes
            if (n.poi or {}).get("lat")
        ]
        assert len(cls.points) >= 2, "测试计划需要至少两个带坐标的节点"

    def _at(self, index: int):
        node, lat, lng = self.points[index]
        return node, lat, lng

    def test_on_track_when_at_expected_place(self):
        node, lat, lng = self._at(0)
        result = locate(self.plan, lat, lng, node.start)
        self.assertEqual(result["status"], "on_track")
        self.assertEqual(result["driftMinutes"], 0)
        self.assertEqual(result["schemes"], [])

    def test_behind_when_still_at_previous_node(self):
        first, lat, lng = self._at(0)
        second, _, _ = self._at(1)
        # 时间已经过了第二站的开始，但人还在第一站
        now = second.start + 20
        result = locate(self.plan, lat, lng, now)
        self.assertEqual(result["status"], "behind", result)
        self.assertEqual(result["atNodeId"], first.id)
        self.assertEqual(result["shouldNodeId"], second.id)
        self.assertEqual(result["driftMinutes"], 20)
        self.assertTrue(result["schemes"], "落后了却没给任何改法")

    def test_short_delay_offers_trim_and_shift(self):
        _, lat, lng = self._at(0)
        second, _, _ = self._at(1)
        result = locate(self.plan, lat, lng, second.start + 15)
        ids = [s["id"] for s in result["schemes"]]
        self.assertIn("A", ids, f"应该给出缩短停留方案：{ids}")
        self.assertIn("B", ids, f"应该给出整体顺延方案：{ids}")

    def test_far_away_reports_unknown(self):
        _, lat, lng = self._at(0)
        result = locate(self.plan, lat + 0.5, lng + 0.5, self._at(0)[0].start)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["schemes"], [])

    def test_plan_without_coordinates(self):
        with patch("yingbian.poi._throttle", lambda: None), patch(
            "yingbian.poi._http_json", side_effect=fake_http
        ), patch.dict("os.environ", {"AMAP_KEY": "test", "YINGBIAN_OFFLINE_ROUTE": "1"}):
            from yingbian import poi

            poi._CACHE.clear()
            from yingbian import load_plan

            builtin = load_plan("data/plan-saturday.json")
        result = locate(builtin, 30.25, 120.15, 600)
        self.assertEqual(result["status"], "no_location_data")
        self.assertTrue(result["message"])

    def test_multiday_only_compares_the_active_day(self):
        plan = Plan(
            plan_id="multi",
            title="多日",
            date="2026-11-24",
            end_date="2026-11-27",
            days=4,
            nodes=[
                Node(
                    id="d1",
                    type="place",
                    title="第一天",
                    start=600,
                    end=660,
                    indoor=False,
                    confirmed=False,
                    date="2026-11-24",
                    poi={"lat": 30.0, "lng": 120.0},
                ),
                Node(
                    id="d4",
                    type="place",
                    title="第四天",
                    start=600,
                    end=660,
                    indoor=False,
                    confirmed=False,
                    date="2026-11-27",
                    poi={"lat": 30.2, "lng": 120.2},
                ),
            ],
            edges=[],
        )
        result = locate(plan, 30.0, 120.0, 700, today="2026-11-24")
        self.assertEqual(result["shouldNodeId"], "d1", result)
        self.assertEqual(result["status"], "on_track", result)


if __name__ == "__main__":
    unittest.main()
