"""主动巡检测试。

守的几件事（这些是"管家"可信度的底线）：
  1. 一切正常时**不要打扰**用户（不能变成噪音）
  2. 时间不够逛完某个有收口的点时，要提醒"可能去不成了"
  3. 有位置且落后时，要提醒落后分钟数
  4. 提醒按严重程度排序，最要紧的在最前面
"""

import unittest

from yingbian import load_plan
from yingbian.patrol import patrol


def at(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


class PatrolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = load_plan("data/plan-demo.json")      # 有缓冲
        cls.tight = load_plan("data/plan-saturday.json")  # 零缓冲

    def test_quiet_when_all_good(self):
        result = patrol(self.demo, at("10:30"))
        self.assertFalse(result["needsAttention"], result["alerts"])
        self.assertEqual(result["severity"], "none")

    def test_warn_when_running_out_of_time(self):
        """16:50 时，日落点 17:40 收口，但逛完要 70 分钟 —— 今天去不成了"""
        result = patrol(self.demo, at("16:50"))
        self.assertTrue(result["needsAttention"])
        kinds = [alert["kind"] for alert in result["alerts"]]
        self.assertIn("closing", kinds, result["alerts"])
        closing = next(a for a in result["alerts"] if a["kind"] == "closing")
        self.assertIn("去不成", closing["title"])
        self.assertTrue(closing["nodeId"])

    def test_quiet_after_day_ends(self):
        result = patrol(self.demo, at("23:00"))
        self.assertFalse(result["needsAttention"], result["alerts"])

    def test_tight_plan_has_no_user_visible_buffer_alert(self):
        """缓冲是内部概念：用户界面不再出现“今天全程没有缓冲”这种提醒"""
        result = patrol(self.tight, at("10:00"))
        tight = [a for a in result["alerts"] if a["kind"] == "tight"]
        self.assertEqual(tight, [], result["alerts"])
        self.assertNotIn("没有缓冲", str(result))

    def test_alerts_sorted_by_severity(self):
        result = patrol(self.tight, at("16:50"))
        order = {"urgent": 0, "warn": 1, "info": 2}
        ranks = [order[a["severity"]] for a in result["alerts"]]
        self.assertEqual(ranks, sorted(ranks), result["alerts"])

    def test_behind_needs_position(self):
        """没有位置时不该判断落后"""
        result = patrol(self.demo, at("16:50"))
        kinds = [a["kind"] for a in result["alerts"]]
        self.assertNotIn("behind", kinds)


if __name__ == "__main__":
    unittest.main()
