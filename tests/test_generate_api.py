"""接口层测试：/api/generate 必须把生成的计划注册进计划表。

为什么这条重要：
  生成不是终点。用户看到行程后马上要问"下雨了怎么办"，
  所以生成的计划必须和内置计划享受同一套 /event /repair /apply /undo。
  这个测试守的就是"生成完能不能立刻发事件"。

全部离线：mock 掉 poi 唯一的网络出口。
"""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app import app

POI_PAYLOAD = {
    "status": "1",
    "info": "OK",
    "infocode": "10000",
    "count": "3",
    "pois": [
        {"id": "B1", "name": "清河坊历史文化特色街区", "type": "风景名胜;风景名胜;国家级景点",
         "location": "120.169,30.239"},
        {"id": "B2", "name": "湖边公园", "type": "风景名胜;公园广场;公园",
         "location": "120.155,30.250"},
        {"id": "B3", "name": "转角咖啡", "type": "餐饮服务;咖啡厅;咖啡厅",
         "location": "120.150,30.255"},
    ],
}

RAIN = {"type": "rain", "from": "11:00", "to": "13:00", "prob": 0.7}


def fake_http(url: str) -> dict:
    return POI_PAYLOAD


class GenerateApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        patch.dict(os.environ, {"AMAP_KEY": "test-key"}).start()
        patch("yingbian.poi._throttle", lambda: None).start()
        patch("yingbian.poi._http_json", side_effect=fake_http).start()
        from yingbian import poi

        poi._CACHE.clear()

    def tearDown(self):
        patch.stopall()

    def test_generate_registers_plan_so_events_work(self):
        res = self.client.post("/api/generate", json={"city": "杭州"}).json()
        self.assertTrue(res["ok"], res)
        plan = res["data"]["plan"]
        pid = plan["planId"]
        self.assertEqual(pid, "p_generated")
        self.assertGreaterEqual(len(plan["nodes"]), 3)

        # 能被取出来
        got = self.client.get(f"/api/plan/{pid}").json()
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["data"]["plan"]["nodes"]), len(plan["nodes"]))

        # 能直接发事件（这条是重点）
        ev = self.client.post(f"/api/plan/{pid}/event", json=RAIN).json()
        self.assertTrue(ev["ok"], ev)
        self.assertIn("n_", "".join(ev["data"]["states"].keys()))

        # 能直接求方案
        rp = self.client.post(f"/api/plan/{pid}/repair", json={"event": RAIN}).json()
        self.assertTrue(rp["ok"], rp)
        self.assertIn(rp["data"]["status"], ("ok", "blocked"))

    def test_generate_returns_generation_meta(self):
        res = self.client.post("/api/generate", json={"city": "杭州"}).json()
        gen = res["data"]["generation"]
        self.assertIn("warnings", gen)
        self.assertIn("note", gen)
        # 生成器必须自己说明"这些数据是怎么来的、哪里不确定"
        self.assertIn("高德", gen["note"])

    def test_generate_without_key_reports_readable_error(self):
        with patch.dict(os.environ, {"AMAP_KEY": ""}):
            from yingbian import poi

            poi._CACHE.clear()
            res = self.client.post("/api/generate", json={"city": "杭州"}).json()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "GENERATE_FAILED")
        self.assertIn("AMAP_KEY", res["error"]["message"])


if __name__ == "__main__":
    unittest.main()
