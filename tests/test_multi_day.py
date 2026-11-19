"""多日行程测试。

守的几件事：
  1. days=1 不产生住宿节点，标题是"一日行程"
  2. days>1 每天都有集合/出发节点，除最后一天外都有住宿节点
  3. 多日行程的节点 id 带天前缀，不会和单日冲突
  4. 边不会悬空（多日里每天是独立链，边数不等于 nodes-1）
  5. 住宿节点必须排在当天最后一站之后 —— 曾经算错过，导致"时间重叠"
"""

import os
import unittest
from unittest.mock import patch

from yingbian.generate import Preferences, generate
from yingbian.models import Plan

POIS = [
    ("B1", "湖边公园", "风景名胜;公园", "120.155,30.250"),
    ("B2", "转角咖啡", "餐饮服务;咖啡厅", "120.150,30.255"),
    ("B3", "城市博物馆", "科教文化服务;博物馆", "120.160,30.245"),
    ("B4", "老街", "风景名胜;风景名胜", "120.165,30.240"),
    ("B5", "江畔茶馆", "餐饮服务;茶艺馆", "120.168,30.243"),
    ("B6", "近代史博物馆", "科教文化服务;博物馆", "120.152,30.248"),
    ("B7", "梅园", "风景名胜;公园", "120.147,30.252"),
    ("B8", "旧书店咖啡", "餐饮服务;咖啡厅", "120.157,30.247"),
    ("B9", "古城墙", "风景名胜;风景名胜", "120.163,30.238"),
    ("B10", "艺术馆", "科教文化服务;美术馆", "120.149,30.244"),
    ("B11", "运河步道", "风景名胜;风景名胜", "120.145,30.249"),
    ("B12", "手工面包房", "餐饮服务;甜品店", "120.159,30.251"),
    ("B13", "园林", "风景名胜;公园", "120.143,30.246"),
    ("B14", "小剧场", "科教文化服务;剧场", "120.166,30.252"),
]

POI_PAYLOAD = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "count": str(len(POIS)),
    "pois": [
        {"id": pid, "name": name, "type": type_text, "location": location}
        for pid, name, type_text, location in POIS
    ],
}


def fake_http(url: str) -> dict:
    return POI_PAYLOAD


class MultiDayTest(unittest.TestCase):
    def setUp(self):
        patch.dict(os.environ, {"AMAP_KEY": "test-key", "YINGBIAN_OFFLINE_ROUTE": "1"}).start()
        patch("yingbian.poi._throttle", lambda: None).start()
        patch("yingbian.poi._http_json", side_effect=fake_http).start()
        from yingbian import poi

        poi._CACHE.clear()

    def tearDown(self):
        patch.stopall()

    def _gen(self, days):
        return generate(
            Preferences(city="杭州", interests=["景点", "咖啡"], days=days, max_transit_min=45)
        )

    def test_single_day_has_no_hotel(self):
        plan = self._gen(1)
        ids = [n["id"] for n in plan["nodes"]]
        self.assertTrue(all(i.startswith("d1_") for i in ids), ids)
        self.assertFalse(any("hotel" in i for i in ids), "单日行程不该有住宿节点")
        self.assertIn("一日行程", plan["title"])

    def test_multi_day_has_hotel_per_night(self):
        plan = self._gen(2)
        ids = [n["id"] for n in plan["nodes"]]
        self.assertIn("d1_hotel", ids)
        self.assertIn("d2_meet", ids)
        self.assertNotIn("d2_hotel", ids, "最后一天不该补住宿")
        self.assertIn("2 日行程", plan["title"])

    def test_three_days_have_two_hotels(self):
        plan = self._gen(3)
        ids = [n["id"] for n in plan["nodes"]]
        self.assertIn("d1_hotel", ids)
        self.assertIn("d2_hotel", ids)
        self.assertNotIn("d3_hotel", ids)

    def test_no_dangling_edges(self):
        for days in (1, 2, 3):
            plan = self._gen(days)
            node_ids = {n["id"] for n in plan["nodes"]}
            for edge in plan["edges"]:
                self.assertIn(edge["from"], node_ids, f"{days}天：悬空 from {edge}")
                self.assertIn(edge["to"], node_ids, f"{days}天：悬空 to {edge}")
            Plan.from_dict(plan)   # 引擎内部也会校验边引用

    def test_hotel_starts_after_last_stop(self):
        """住宿节点不能和当天最后一站重叠 —— 曾经算错过"""
        plan = self._gen(2)
        for day in (1, 2):
            stops = [
                n for n in plan["nodes"]
                if n["id"].startswith(f"d{day}_") and "hotel" not in n["id"] and "meet" not in n["id"]
            ]
            hotel = next((n for n in plan["nodes"] if n["id"] == f"d{day}_hotel"), None)
            if hotel is None or not stops:
                continue
            last = max(stops, key=lambda n: n["start"])
            self.assertGreaterEqual(
                hotel["start"],
                last["end"],
                f"第{day}天住宿开始 {hotel['start']} 早于最后一站结束 {last['end']}",
            )

    def test_days_clamped(self):
        plan = generate(Preferences(city="杭州", interests=["景点"], days=99, max_transit_min=45))
        hotels = [n for n in plan["nodes"] if "hotel" in n["id"]]
        self.assertLessEqual(len(hotels), 6, "天数应被限制在 7 天以内（最多 6 晚住宿）")

    def test_few_places_degrades_gracefully(self):
        """候选点不够时，多日行程应当少排几天，而不是崩"""
        small = {"status": "1", "count": "2", "pois": [
            {"id": "S1", "name": "小公园", "type": "风景名胜;公园", "location": "120.155,30.250"},
            {"id": "S2", "name": "小咖啡馆", "type": "餐饮服务;咖啡厅", "location": "120.150,30.255"},
        ]}
        with patch("yingbian.poi._http_json", return_value=small):
            from yingbian import poi

            poi._CACHE.clear()
            try:
                plan = generate(
                    Preferences(city="杭州", interests=["景点"], days=3, max_transit_min=45)
                )
            except RuntimeError:
                return   # 点太少直接报错也是可接受的行为
        ids = [n["id"] for n in plan["nodes"]]
        self.assertTrue(any(i.startswith("d1_") for i in ids))
        Plan.from_dict(plan)


if __name__ == "__main__":
    unittest.main()
