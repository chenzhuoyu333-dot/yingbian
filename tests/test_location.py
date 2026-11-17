import unittest

from yingbian import load_plan
from yingbian.location import checkin
from yingbian.repair import apply_actions


class CheckinTest(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan()

    def test_on_time_has_no_scheme(self):
        result = checkin(self.plan, "n_tea", 0)
        self.assertEqual(result["status"], "on_time")
        self.assertEqual(result["schemes"], [])
        self.assertIsNone(result["impact"])

    def test_late_offers_safe_schemes_only(self):
        result = checkin(self.plan, "n_tea", 20)
        self.assertEqual(result["status"], "late")
        ids = [scheme["id"] for scheme in result["schemes"]]
        # 茶馆后面有已锁定的返程和晚餐，不能整体顺延。
        self.assertIn("A", ids)
        self.assertIn("B", ids)
        skip = next(item for item in result["schemes"] if item["id"] == "B")
        self.assertEqual(skip["label"], "跳过当前")

    def test_trim_keeps_following_nodes_in_place(self):
        result = checkin(self.plan, "n_tea", 20)
        scheme = next(item for item in result["schemes"] if item["id"] == "A")
        updated = apply_actions(self.plan, scheme["actions"])
        tea = updated.find("n_tea")
        river = updated.find("n_river")
        self.assertEqual(tea.start, 14 * 60)
        self.assertEqual(tea.end, 14 * 60 + 10)
        self.assertEqual(river.start, self.plan.find("n_river").start)
        self.assertEqual(river.end, self.plan.find("n_river").end)

    def test_locked_node_is_not_shifted_or_dropped(self):
        result = checkin(self.plan, "n_lunch", 15)
        ids = [scheme["id"] for scheme in result["schemes"]]
        self.assertEqual(ids, ["A"])
        for scheme in result["schemes"]:
            for action in scheme["actions"]:
                self.assertNotEqual(action["action"], "shift")
                self.assertNotEqual(action["action"], "drop")

    def test_member_late_is_reported_separately(self):
        result = checkin(
            self.plan,
            "n_tea",
            15,
            person_id="p_xiaowang",
        )
        self.assertEqual(result["status"], "member_late")
        self.assertEqual(result["event"]["type"], "memberLate")
        self.assertEqual(result["event"]["nodeId"], "n_tea")
        self.assertEqual(result["impact"]["states"]["n_tea"], "at_risk")
        self.assertIn("p_xiaowang", result["message"])
        self.assertEqual(
            [scheme["id"] for scheme in result["schemes"]],
            ["B", "A"],
        )

    def test_unknown_node_raises(self):
        with self.assertRaises(ValueError):
            checkin(self.plan, "n_missing", 10)


if __name__ == "__main__":
    unittest.main()
