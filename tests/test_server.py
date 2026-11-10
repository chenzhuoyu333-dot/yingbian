import unittest

from fastapi.testclient import TestClient

from server import app as app_module
from server.app import app
from yingbian import load_plan


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

        old = os.environ.pop("QWEATHER_KEY", None)
        try:
            body = self.client.get("/api/weather").json()
        finally:
            if old is not None:
                os.environ["QWEATHER_KEY"] = old
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

    def test_self_test_page_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("接口自测", response.text)


if __name__ == "__main__":
    unittest.main()
