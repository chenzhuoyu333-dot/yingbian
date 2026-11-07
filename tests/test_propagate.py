import unittest

from yingbian import Event, analyze, load_plan


class ImpactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = load_plan()
        cls.rain = Event(type="rain", start=15 * 60, end=17 * 60)

    def test_baseline_is_clean(self):
        report = analyze(self.plan)
        self.assertEqual(report.affected, [])
        self.assertEqual(report.impact_ratio, 0)
        self.assertTrue(report.locked_preserved)

    def test_rain_cancels_boat(self):
        report = analyze(self.plan, self.rain)
        self.assertEqual(report.nodes["n07"].state, "invalid")
        for node_id in ("n09", "n10", "n11", "n12"):
            self.assertEqual(report.nodes[node_id].state, "at_risk", node_id)

    def test_rain_ratio_and_severity(self):
        report = analyze(self.plan, self.rain)
        self.assertEqual(len(report.affected), 5)
        self.assertAlmostEqual(report.impact_ratio, 5 / 11, places=4)
        self.assertEqual(report.severity, "medium")

    def test_untouched_morning_stays_ok(self):
        report = analyze(self.plan, self.rain)
        for node_id in ("n01", "n02", "n03", "n04", "n05", "n06"):
            self.assertEqual(report.nodes[node_id].state, "ok", node_id)

    def test_direct_closure_same_result(self):
        closure = Event(type="closure", node_ids=("n07",))
        report = analyze(self.plan, closure)
        self.assertEqual(report.nodes["n07"].state, "invalid")
        self.assertEqual(report.severity, "medium")

    def test_locked_nodes_never_move_in_analysis(self):
        report = analyze(self.plan, self.rain)
        for node_id in ("n01", "n04", "n10"):
            node = self.plan.node(node_id)
            self.assertEqual(report.nodes[node_id].start, node.start)


if __name__ == "__main__":
    unittest.main()
