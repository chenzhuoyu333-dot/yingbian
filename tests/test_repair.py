import unittest

from yingbian import Event, analyze, apply_repair, load_plan, repair
from yingbian.repair import RepairError


class RepairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = load_plan()
        cls.event = Event(type="rain", start=15 * 60, end=17 * 60)
        cls.results = repair(cls.plan, cls.event)

    def test_three_schemes(self):
        self.assertEqual([item.scheme.key for item in self.results], ["A", "B", "C"])

    def test_scheme_a_minimum_change(self):
        result = self.results[0]
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.changed_count, 2)
        self.assertFalse(result.active["n07"])
        self.assertTrue(result.active["n08"])
        self.assertEqual(result.changed_persons, ["p1", "p2"])

    def test_locked_nodes_preserved(self):
        for result in self.results:
            self.assertTrue(result.locked_preserved, result.scheme.key)
            for node_id in ("n01", "n04", "n10"):
                self.assertEqual(result.starts[node_id], self.plan.node(node_id).start)

    def test_scheme_c_trades_notice_for_safety(self):
        conservative = self.results[2]
        self.assertFalse(conservative.active["n09"])
        self.assertIn("p3", conservative.changed_persons)
        self.assertGreaterEqual(conservative.changed_count, self.results[0].changed_count)

    def test_solve_is_fast(self):
        for result in self.results:
            self.assertLess(result.solve_ms, 2000, result.scheme.key)

    def test_apply_repair_bumps_version(self):
        next_plan = apply_repair(self.plan, self.results[0])
        self.assertEqual(next_plan.version, self.plan.version + 1)
        self.assertFalse(next_plan.node("n07").active)
        self.assertTrue(next_plan.node("n08").active)
        self.assertEqual(next_plan.node("n04").start, self.plan.node("n04").start)

    def test_greedy_fallback_matches_core_result(self):
        results = repair(self.plan, self.event, use_cpsat=False)
        self.assertEqual(results[0].status, "GREEDY")
        self.assertFalse(results[0].active["n07"])
        self.assertTrue(results[0].active["n08"])
        self.assertTrue(results[0].locked_preserved)

    def test_locked_invalid_needs_human(self):
        event = Event(type="closure", node_ids=("n10",))
        with self.assertRaises(RepairError):
            repair(self.plan, event)


if __name__ == "__main__":
    unittest.main()
