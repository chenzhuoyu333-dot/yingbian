"""多人协作测试：成员、活动记录、投票决策。

重点守三件事：
  1. 只有加入过的人才能投票（不能匿名改别人的行程）
  2. 投票的结束条件明确：全员投完 / 超时 → 平票用默认方案，绝不卡死
  3. 活动记录能回答"谁在什么时候改了什么"
"""

import time
import unittest

from yingbian.collab import CollabState


RAIN = {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7}


class MemberTest(unittest.TestCase):
    def setUp(self):
        self.state = CollabState()

    def test_join_is_idempotent(self):
        a = self.state.join("p1", "u1", "队长")
        b = self.state.join("p1", "u1", "队长")
        self.assertEqual(a.id, b.id)
        self.assertEqual(len(self.state.roster("p1")), 1)

    def test_join_defaults_name(self):
        member = self.state.join("p1", "u9", "")
        self.assertTrue(member.name.startswith("成员"))

    def test_join_records_activity(self):
        self.state.join("p1", "u1", "队长")
        feed = self.state.feed("p1")
        self.assertTrue(any("加入了行程" in item["text"] for item in feed))

    def test_rename_on_rejoin(self):
        self.state.join("p1", "u1", "张三")
        member = self.state.join("p1", "u1", "张三丰")
        self.assertEqual(member.name, "张三丰")


class VoteTest(unittest.TestCase):
    def setUp(self):
        self.state = CollabState()
        self.state.join("p1", "u1", "队长")
        self.state.join("p1", "u2", "队友")

    def test_stranger_cannot_vote(self):
        round_ = self.state.start_vote("p1", RAIN, initiator=self.state.member("p1", "u1"))
        result, message = self.state.cast_vote("p1", "u999", "A")
        self.assertIn("还没加入", message)
        self.assertEqual(round_.votes, {})

    def test_invalid_scheme_rejected(self):
        self.state.start_vote("p1", RAIN, initiator=self.state.member("p1", "u1"))
        _, message = self.state.cast_vote("p1", "u1", "Z")
        self.assertIn("只能投", message)

    def test_majority_wins_when_all_voted(self):
        self.state.start_vote("p1", RAIN, initiator=self.state.member("p1", "u1"))
        self.state.cast_vote("p1", "u1", "A")
        round_ = self.state.current_vote("p1")
        self.assertEqual(round_.status, "open")   # 还差一票

        self.state.cast_vote("p1", "u2", "A")
        round_ = self.state.current_vote("p1")
        self.assertEqual(round_.status, "closed")
        self.assertEqual(round_.winner, "A")
        self.assertEqual(round_.decided_by, "all-voted")

    def test_tie_falls_back_to_default(self):
        self.state.start_vote("p1", RAIN, default_scheme="B", initiator=self.state.member("p1", "u1"))
        self.state.cast_vote("p1", "u1", "A")
        self.state.cast_vote("p1", "u2", "B")
        round_ = self.state.current_vote("p1")
        self.assertEqual(round_.status, "closed")
        self.assertEqual(round_.winner, "B")
        self.assertEqual(round_.decided_by, "tie-default")

    def test_timeout_uses_default_when_nobody_voted(self):
        self.state.start_vote("p1", RAIN, ttl_sec=10, default_scheme="B",
                              initiator=self.state.member("p1", "u1"))
        # 直接把出生时间往前挪，模拟超时
        self.state.rounds["p1"].created_at = time.time() - 11
        round_ = self.state.current_vote("p1")
        self.assertEqual(round_.status, "closed")
        self.assertEqual(round_.winner, "B")
        self.assertEqual(round_.decided_by, "timeout-default")

    def test_timeout_keeps_current_leader(self):
        self.state.start_vote("p1", RAIN, ttl_sec=10, initiator=self.state.member("p1", "u1"))
        self.state.cast_vote("p1", "u1", "B")
        self.state.rounds["p1"].created_at = time.time() - 11
        round_ = self.state.current_vote("p1")
        self.assertEqual(round_.winner, "B")
        self.assertEqual(round_.decided_by, "majority")

    def test_new_vote_cancels_previous(self):
        first = self.state.start_vote("p1", RAIN, initiator=self.state.member("p1", "u1"))
        second = self.state.start_vote("p1", RAIN, initiator=self.state.member("p1", "u1"))
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(self.state.current_vote("p1").id, second.id)

    def test_vote_after_close_is_rejected(self):
        self.state.start_vote("p1", RAIN, initiator=self.state.member("p1", "u1"))
        self.state.cast_vote("p1", "u1", "A")
        self.state.cast_vote("p1", "u2", "B")
        _, message = self.state.cast_vote("p1", "u1", "A")
        self.assertIn("已经结束", message)

    def test_tally_and_remaining(self):
        self.state.start_vote("p1", RAIN, ttl_sec=60, initiator=self.state.member("p1", "u1"))
        round_ = self.state.cast_vote("p1", "u1", "A")[0]
        payload = round_.to_dict()
        self.assertEqual(payload["tally"]["A"], 1)
        self.assertGreater(payload["remainingSec"], 0)
        self.assertEqual(payload["status"], "open")

    def test_activity_records_votes(self):
        self.state.start_vote("p1", RAIN, initiator=self.state.member("p1", "u1"))
        self.state.cast_vote("p1", "u1", "A")
        texts = [item["text"] for item in self.state.feed("p1")]
        self.assertTrue(any("投了方案 A" in t for t in texts))
        self.assertTrue(any("发起投票" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
