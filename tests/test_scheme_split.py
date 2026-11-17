"""守住两件事：
  1. 方案只有 A/B 两个（第三个"保少改动"已砍掉，因为它想优化的量数学上改不动）
  2. A 与 B 在"挪时间和换备选都可行"时，必须给出不同的动作
     否则屏 2 上两张卡片会一模一样，演示时会被问"这不重复吗"
"""

import unittest

from yingbian import load_plan, Event, repair
from yingbian.rules import SCHEMES

RAIN = {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7}


def _actions(plan_file: str, scheme: str) -> list[tuple[str, str]]:
    plan = load_plan(plan_file)
    result = repair(plan, Event.from_dict(RAIN), scheme)
    return [(action.node_id, action.action) for action in result.actions]


class SchemeSetTest(unittest.TestCase):
    def test_only_two_schemes(self):
        self.assertEqual(list(SCHEMES), ["A", "B"])

    def test_labels(self):
        self.assertEqual(SCHEMES["A"].label, "保时间")
        self.assertEqual(SCHEMES["B"].label, "保体验")


class DivergenceTest(unittest.TestCase):
    def test_a_and_b_differ_on_demo_plan(self):
        """
        plan-demo 特意把日落点的最晚开始时间放宽、并给了室内备选，
        所以"挪时间"和"换备选"两条路都走得通：
          A 保时间 → 挪到雨停（宁可晚，也不换）
          B 保体验 → 换成美术馆（宁可换，也不晚）
        """
        a = _actions("data/plan-demo.json", "A")
        b = _actions("data/plan-demo.json", "B")
        self.assertNotEqual(a, b, f"A/B 输出相同，屏 2 会重复：{a}")

        # 具体断言语义：A 把日落点挪走，B 把日落点换掉
        a_sunset = [act for node, act in a if node == "n_sunset"]
        b_sunset = [act for node, act in b if node == "n_sunset"]
        self.assertEqual(a_sunset, ["shift"], f"A 应该挪日落点，实际 {a_sunset}")
        self.assertEqual(b_sunset, ["replace"], f"B 应该换日落点，实际 {b_sunset}")

    def test_b_never_drops_when_shift_is_possible(self):
        """
        "保体验"最不该删点。drop 代价调到 1200 之后，
        只要还能挪，就不能选删。
        """
        for plan_file in ("data/plan-demo.json", "data/plan-slack.json"):
            for node_id, action in _actions(plan_file, "B"):
                self.assertNotEqual(
                    action, "drop",
                    f"{plan_file} 的 {node_id} 被 B 删掉了 —— '保体验'删点自相矛盾",
                )


if __name__ == "__main__":
    unittest.main()
