import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import app as app_module
from server.app import app
from yingbian import load_plan
from yingbian.models import parse_time
from yingbian.repair import RepairResult


RAIN = {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7}


class ServerContractTest(unittest.TestCase):
    def setUp(self):
        base = load_plan()
        app_module.PLANS = {base.plan_id: base.clone()}
        app_module.VERSIONS = {base.plan_id: [base.clone()]}
        self.client = TestClient(app)
        self.plan_id = base.plan_id

    def test_get_plan(self):
        body = self.client.get(f"/api/plan/{self.plan_id}").json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["data"]["plan"]["nodes"]), 12)
        self.assertEqual(body["data"]["version"], 1)

    def test_event_t1(self):
        body = self.client.post(f"/api/plan/{self.plan_id}/event", json=RAIN).json()
        data = body["data"]
        self.assertEqual(data["affectedCount"], 2)
        self.assertEqual(data["path"], "local")
        self.assertEqual(data["states"]["n_sunset"], "at_risk")

    def test_repair_t1_b(self):
        body = self.client.post(
            f"/api/plan/{self.plan_id}/repair",
            json={"event": RAIN, "schemes": ["B"]},
        ).json()
        scheme = body["data"]["schemes"][0]
        self.assertEqual(scheme["changedCount"], 2)
        self.assertEqual(scheme["keepRate"], 1.0)
        self.assertEqual([a["action"] for a in scheme["actions"]], ["replace", "drop"])

    def test_repair_collapses_identical_a_b(self):
        body = self.client.post(
            f"/api/plan/{self.plan_id}/repair",
            json={"event": RAIN},
        ).json()
        schemes = body["data"]["schemes"]
        self.assertEqual(len(schemes), 1)
        self.assertEqual(schemes[0]["id"], "A")
        self.assertEqual(schemes[0]["label"], "两种偏好结果一致")

    def test_repair_keeps_distinct_a_b(self):
        base = load_plan("data/plan-demo.json")
        app_module.PLANS = {base.plan_id: base.clone()}
        app_module.VERSIONS = {base.plan_id: [base.clone()]}
        body = self.client.post(
            f"/api/plan/{base.plan_id}/repair",
            json={"event": RAIN},
        ).json()
        self.assertEqual(
            [scheme["id"] for scheme in body["data"]["schemes"]],
            ["A", "B"],
        )

    def test_repair_keeps_usable_scheme_when_other_blocked(self):
        base = load_plan()
        blocked = RepairResult(
            status="blocked",
            scheme="A",
            label="保时间",
            actions=[],
            blocked_node="n_sunset",
            message="锁定节点被影响",
            keep_rate=1.0,
            changed_count=0,
            plan=base.clone(),
            elapsed_ms=0.0,
        )
        usable = RepairResult(
            status="ok",
            scheme="B",
            label="保体验",
            actions=[],
            blocked_node=None,
            message="",
            keep_rate=1.0,
            changed_count=0,
            plan=base.clone(),
            elapsed_ms=0.0,
        )
        with patch("server.app.repair", side_effect=[blocked, usable]):
            body = self.client.post(
                f"/api/plan/{self.plan_id}/repair",
                json={"event": RAIN, "schemes": ["A", "B"]},
            ).json()
        self.assertEqual(body["data"]["status"], "ok")
        self.assertEqual([scheme["id"] for scheme in body["data"]["schemes"]], ["B"])

    def test_all_blocked_returns_one_blocked_response(self):
        self.client.post(
            "/api/debug/lock",
            json={"planId": self.plan_id, "nodeId": "n_sunset", "confirmed": True},
        )
        body = self.client.post(
            f"/api/plan/{self.plan_id}/repair",
            json={"event": RAIN},
        ).json()
        self.assertEqual(body["data"]["status"], "blocked")
        self.assertEqual(body["data"]["schemes"], [])
        self.assertEqual(body["data"]["blockedNode"], "n_sunset")

    def test_apply_and_undo(self):
        repair_body = self.client.post(
            f"/api/plan/{self.plan_id}/repair",
            json={"event": RAIN, "schemes": ["B"]},
        ).json()
        actions = repair_body["data"]["schemes"][0]["actions"]
        applied = self.client.post(
            f"/api/plan/{self.plan_id}/apply",
            json={"schemeId": "B", "actions": actions},
        ).json()
        self.assertEqual(applied["data"]["version"], 2)
        undo = self.client.post(f"/api/plan/{self.plan_id}/undo").json()
        self.assertEqual(undo["data"]["version"], 1)

    def test_undo_preview_lists_what_will_restore(self):
        repair_body = self.client.post(
            f"/api/plan/{self.plan_id}/repair",
            json={"event": RAIN, "schemes": ["B"]},
        ).json()
        actions = repair_body["data"]["schemes"][0]["actions"]
        self.client.post(f"/api/plan/{self.plan_id}/apply", json={"actions": actions})
        preview = self.client.get(f"/api/plan/{self.plan_id}/undo/preview").json()["data"]
        self.assertTrue(preview["canUndo"])
        self.assertEqual(preview["targetVersion"], 1)
        self.assertTrue(preview["changes"])
        self.assertTrue(preview["summary"])

    def test_stay_change_shifts_later_nodes_same_day(self):
        base = load_plan()
        target = base.find("n_town")
        target.poi = {"lat": 30.25, "lng": 120.15, "openTime": "08:00-22:00"}
        target.date = base.date
        app_module.PLANS = {base.plan_id: base.clone()}
        app_module.VERSIONS = {base.plan_id: [base.clone()]}
        next_node = base.find("n_lunch")
        before = next_node.start
        body = self.client.post(
            f"/api/plan/{base.plan_id}/node/n_town/stay",
            json={"minutes": target.duration + 30},
        ).json()
        self.assertTrue(body["ok"])
        plan = body["data"]["plan"]
        after = next(node for node in plan["nodes"] if node["id"] == "n_lunch")["start"]
        self.assertNotEqual(before, parse_time(after))
        self.assertEqual(body["data"]["version"], 2)

    def test_blocked_t4(self):
        self.client.post(
            "/api/debug/lock",
            json={"planId": self.plan_id, "nodeId": "n_sunset", "confirmed": True},
        )
        body = self.client.post(
            f"/api/plan/{self.plan_id}/repair",
            json={"event": RAIN, "schemes": ["B"]},
        ).json()
        self.assertEqual(body["data"]["status"], "blocked")
        self.assertEqual(body["data"]["blockedNode"], "n_sunset")

    def test_weather_is_demo_without_key(self):
        import os
        from unittest.mock import patch

        # 必须把三个 Key 全部显式清空：项目根目录的 .env 会把它们塞进 os.environ，
        # 否则这个测试会真的去调高德，结果就不再是演示数据。
        clean = {"QWEATHER_HOST": "", "QWEATHER_KEY": "", "AMAP_KEY": ""}
        with patch.dict(os.environ, clean):
            body = self.client.get("/api/weather").json()
        weather = body["data"]
        self.assertTrue(weather["isDemo"])
        self.assertIn("演示数据", weather["source"])
        self.assertTrue(weather["fetchedAt"])
        self.assertIn("note", weather)

    def test_reset_restores_version_one(self):
        repair_body = self.client.post(
            f"/api/plan/{self.plan_id}/repair",
            json={"event": RAIN, "schemes": ["B"]},
        ).json()
        actions = repair_body["data"]["schemes"][0]["actions"]
        self.client.post(f"/api/plan/{self.plan_id}/apply", json={"actions": actions})
        reset = self.client.post("/api/reset").json()
        self.assertTrue(reset["data"]["reset"])
        version = self.client.get(f"/api/plan/{self.plan_id}").json()["data"]["version"]
        self.assertEqual(version, 1)

    def test_checkin_on_time(self):
        body = self.client.post(
            f"/api/plan/{self.plan_id}/checkin",
            json={"nodeId": "n_tea", "minutes": 0, "memberId": "m_me"},
        ).json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["status"], "on_time")
        self.assertEqual(body["data"]["schemes"], [])

    def test_checkin_late_returns_schemes(self):
        body = self.client.post(
            f"/api/plan/{self.plan_id}/checkin",
            json={"nodeId": "n_tea", "minutes": 20, "memberId": "m_me"},
        ).json()
        data = body["data"]
        self.assertEqual(data["status"], "late")
        self.assertEqual(
            [scheme["id"] for scheme in data["schemes"]],
            ["A", "B"],
        )

    def test_checkin_rejects_out_of_range_minutes(self):
        response = self.client.post(
            f"/api/plan/{self.plan_id}/checkin",
            json={"nodeId": "n_tea", "minutes": 181},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "BAD_MINUTES")

    def test_self_test_page_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("接口自测", response.text)


if __name__ == "__main__":
    unittest.main()
