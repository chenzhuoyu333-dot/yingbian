import unittest

from yingbian import load_plan, propagate


class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan()

    def test_plan_matches_w1_fixture(self):
        self.assertEqual(self.plan.plan_id, "p_sat_guzhen")
        self.assertEqual(self.plan.date, "2026-11-14")
        self.assertEqual(len(self.plan.nodes), 12)
        self.assertEqual(len(self.plan.edges), 11)
        self.assertEqual(len(self.plan.confirmed_nodes()), 5)

    def test_baseline_has_no_risk(self):
        report = propagate(self.plan)
        self.assertEqual(report.affected_count, 0)
        self.assertEqual(report.ratio, 0)

    def test_topo_order_covers_all_nodes(self):
        order = self.plan.topo_order()
        self.assertEqual(len(order), 12)
        self.assertLess(order.index("n_town"), order.index("n_lunch"))
        self.assertLess(order.index("n_sunset"), order.index("n_photo"))


if __name__ == "__main__":
    unittest.main()
