import unittest

from yingbian import Event, load_plan, propagate, repair


RAIN = Event(type="rain", start=15 * 60, end=17 * 60, prob=0.7)


class T1RainTest(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan()
        self.report = propagate(self.plan, RAIN)

    def test_states(self):
        self.assertEqual(self.report.states["n_sunset"], "at_risk")
        self.assertEqual(self.report.states["n_photo"], "at_risk")
        for node_id in (
            "n_meet", "n_transit_go", "n_town", "n_lunch",
            "n_tea", "n_river", "n_transit_back", "n_hotpot",
            "n_market", "n_hotel",
        ):
            self.assertEqual(self.report.states[node_id], "ok", node_id)

    def test_ratio_and_path(self):
        self.assertEqual(self.report.affected_count, 2)
        self.assertAlmostEqual(self.report.ratio, 2 / 12, places=4)
        self.assertEqual(self.report.path, "local")

    def test_repair_b(self):
        result = repair(self.plan, RAIN, "B")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.changed_count, 2)
        self.assertEqual([a.action for a in result.actions], ["replace", "drop"])
        self.assertEqual(result.actions[0].payload["alternativeId"], "a_museum")
        self.assertEqual(result.keep_rate, 1.0)
        self.assertFalse(any(a.action == "shift" for a in result.actions))


class T2MemberLateTest(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan()
        self.event = Event(type="delay", node_id="n_meet", minutes=60)
        self.report = propagate(self.plan, self.event)

    def test_key_states(self):
        self.assertEqual(self.report.states["n_meet"], "conflict")
        self.assertEqual(self.report.states["n_lunch"], "invalid")
        self.assertEqual(self.report.states["n_sunset"], "invalid")
        self.assertEqual(self.report.states["n_transit_back"], "conflict")

    def test_shifts(self):
        self.assertEqual(self.report.shifts["n_meet"], 60)
        self.assertEqual(self.report.details["n_transit_back"].start, 18 * 60 + 10)
        self.assertGreater(self.report.ratio, 0.6)
        self.assertEqual(self.report.path, "global")

    def test_repair_is_blocked(self):
        result = repair(self.plan, self.event, "B")
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.blocked_node, "n_meet")
        self.assertIn("锁定", result.message)
        self.assertEqual(result.changed_count, 0)


class T3CancelTest(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan()
        self.event = Event(type="cancel", node_id="n_lunch")
        self.report = propagate(self.plan, self.event)

    def test_only_lunch_affected(self):
        self.assertEqual(self.report.states["n_lunch"], "invalid")
        others = [nid for nid in self.report.states if nid != "n_lunch"]
        self.assertTrue(all(self.report.states[nid] == "ok" for nid in others))
        self.assertAlmostEqual(self.report.ratio, 1 / 12, places=4)

    def test_repair_replaces_once(self):
        result = repair(self.plan, self.event, "B")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.changed_count, 1)
        self.assertEqual(result.actions[0].action, "replace")
        self.assertEqual(result.actions[0].payload["alternativeId"], "a_jiangpan")
        self.assertEqual(result.keep_rate, 1.0)


class T4LockedConflictTest(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan()
        self.plan.node("n_sunset").confirmed = True
        self.report = propagate(self.plan, RAIN)

    def test_sunset_is_conflict_not_auto_replaced(self):
        self.assertEqual(self.report.states["n_sunset"], "conflict")
        result = repair(self.plan, RAIN, "B")
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.blocked_node, "n_sunset")
        self.assertEqual(result.changed_count, 0)
        self.assertIn("解锁", result.message)


if __name__ == "__main__":
    unittest.main()
