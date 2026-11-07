import unittest

from yingbian import load_plan


class PlanModelTest(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan()

    def test_counts(self):
        self.assertEqual(len(self.plan.nodes), 12)
        self.assertEqual(len(self.plan.active_nodes()), 11)
        self.assertEqual(len(self.plan.members), 4)

    def test_alt_group_has_one_active(self):
        groups = self.plan.alt_groups()
        self.assertIn("afternoon", groups)
        active = [node.id for node in groups["afternoon"] if node.active]
        self.assertEqual(active, ["n07"])

    def test_locked_nodes(self):
        locked = [node.id for node in self.plan.nodes if node.locked]
        self.assertEqual(locked, ["n01", "n04", "n10"])

    def test_topo_order_covers_all_nodes(self):
        order = self.plan.topo_order()
        self.assertEqual(len(order), 12)
        self.assertLess(order.index("n04"), order.index("n05"))
        self.assertLess(order.index("n09"), order.index("n10"))


if __name__ == "__main__":
    unittest.main()
