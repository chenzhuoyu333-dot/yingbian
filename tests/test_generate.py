"""生成器测试：全部离线，mock 掉唯一的网络出口。

测的是什么：
  1. 生成的结构能被引擎解析（Plan.from_dict 不报错）
  2. 时间单调递增、不重叠
  3. 必去点必须出现，而且被锁定
  4. 边数 = 节点数 - 1（一条链，不漏边）
  5. 生成结果本身通过可行性自检（没有一出生就 invalid 的节点）
  6. 通勤超过上限的点不会被排进去（除非是必去）
  7. 没配 AMAP_KEY 时给出明确报错，而不是静默返回空计划
"""

import json
import os
import unittest
from unittest.mock import patch

from yingbian.generate import Preferences, generate
from yingbian.models import Plan, parse_time
from yingbian.propagate import propagate
from yingbian import generate as generate_module


def _poi(pid, name, type_text, lng, lat, address="测试地址"):
    return {
        "id": pid,
        "name": name,
        "type": type_text,
        "location": f"{lng},{lat}",
        "address": address,
    }


# 三个点围在 120.15,30.25 附近，彼此 5~15 分钟车程
POI_PAYLOAD = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "count": "3",
    "pois": [
        _poi("B001", "清河坊历史文化特色街区", "风景名胜;风景名胜;国家级景点", 120.169, 30.239),
        _poi("B002", "湖边公园", "风景名胜;公园广场;公园", 120.155, 30.250),
        _poi("B003", "转角咖啡", "餐饮服务;咖啡厅;咖啡厅", 120.150, 30.255),
    ],
}

# 必去点：单独一次检索返回它
MUST_PAYLOAD = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "count": "1",
    "pois": [_poi("B009", "鼓楼", "风景名胜;风景名胜;风景名胜", 120.170, 30.240)],
}

EMPTY_PAYLOAD = {"status": "1", "info": "OK", "infocode": "10000", "count": "0", "pois": []}


def fake_http(url: str) -> dict:
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(url).query)
    keyword = (query.get("keywords") or [""])[0]
    if "鼓楼" in keyword:
        return MUST_PAYLOAD
    if keyword:
        return POI_PAYLOAD
    return EMPTY_PAYLOAD


class GenerateTest(unittest.TestCase):
    def setUp(self):
        # 让 generate 认为 Key 已配置；并且关掉节流，测试才快
        self.env = patch.dict(os.environ, {"AMAP_KEY": "test-key"})
        self.env.start()
        self.throttle = patch("yingbian.poi._throttle", lambda: None)
        self.throttle.start()
        self.http = patch("yingbian.poi._http_json", side_effect=fake_http)
        self.http.start()
        # 清掉检索缓存，避免用例之间串味
        from yingbian import poi

        poi._CACHE.clear()

    def tearDown(self):
        patch.stopall()

    def _generate(self, **kw):
        prefs = Preferences(city="杭州", interests=["景点", "公园", "咖啡"], **kw)
        return generate(prefs)

    def test_plan_is_parseable(self):
        plan = self._generate()
        parsed = Plan.from_dict(plan)  # 不抛异常就算过
        self.assertGreaterEqual(len(parsed.nodes), 3)
        self.assertEqual(len(parsed.edges), len(parsed.nodes) - 1)

    def test_time_monotonic_and_no_overlap(self):
        plan = self._generate()
        nodes = plan["nodes"]
        for prev, nxt in zip(nodes, nodes[1:]):
            self.assertLessEqual(
                parse_time(prev["end"]),
                parse_time(nxt["start"]),
                f"{prev['title']} 与 {nxt['title']} 时间重叠了",
            )

    def test_must_visit_present_and_locked(self):
        plan = self._generate(must_visit=["鼓楼"])
        titles = [n["title"] for n in plan["nodes"]]
        self.assertIn("鼓楼", titles)
        locked = [n["title"] for n in plan["nodes"] if n["confirmed"]]
        self.assertIn("鼓楼", locked)

    def test_generated_plan_passes_feasibility_check(self):
        """生成结果喂回同一套约束引擎，不应该一出生就有 invalid 节点"""
        plan = self._generate()
        parsed = Plan.from_dict(plan)
        zero_event = {"type": "rain", "from": "00:00", "to": "00:01", "prob": 0.0}
        from yingbian.propagate import Event

        report = propagate(parsed, Event.from_dict(zero_event))
        bad = [nid for nid, st in report.states.items() if st != "ok"]
        self.assertEqual(bad, [], f"生成结果自带冲突：{bad}")

    def test_transit_limit_filters_far_points(self):
        """
        通勤上限压到 0：除必去点外都排不进来 → 节点不足 3 个 → 明确报错，
        而不是悄悄返回一个只有集合点的残缺计划。
        """
        with self.assertRaises(RuntimeError) as ctx:
            self._generate(max_transit_min=0, must_visit=["鼓楼"])
        self.assertIn("不到 3 个点", str(ctx.exception))

        # 正常上限下，普通点会进来，而且必去点仍在
        plan = self._generate(must_visit=["鼓楼"])
        titles = [n["title"] for n in plan["nodes"]]
        self.assertIn("鼓楼", titles)
        self.assertGreaterEqual(len(titles), 3)

    def test_missing_key_raises(self):
        with patch.dict(os.environ, {"AMAP_KEY": ""}):
            from yingbian import poi

            poi._CACHE.clear()
            with self.assertRaises(RuntimeError):
                generate(Preferences(city="杭州"))

    def test_empty_result_raises_clear_error(self):
        with patch("yingbian.poi._http_json", return_value=EMPTY_PAYLOAD):
            from yingbian import poi

            poi._CACHE.clear()
            with self.assertRaises(RuntimeError) as ctx:
                generate(Preferences(city="火星"))
            self.assertIn("火星", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
