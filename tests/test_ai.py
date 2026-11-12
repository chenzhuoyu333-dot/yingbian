"""AI 接入层测试：全部离线，mock 掉唯一的网络出口 _http_post。

守的几条边界：
  1. 有 Key 且模型返回合法 JSON → source = "ai"
  2. 模型返回垃圾 / 超时 / 没 Key → 自动退回规则解析，source = "rule"
  3. 规则解析要真的能抽出偏好（不能是摆设）
  4. 模型给的时间字段不合法 → 用规则结果兜住，不能把坏值传到下游
  5. explain 在没有模型时也要返回可读文本（就是算法摘要本身）
"""

import os
import unittest
from unittest.mock import patch

from yingbian import ai


class _Env:
    """统一管理环境变量 patch"""

    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.patch = patch.dict(os.environ, self.values)
        self.patch.start()

    def __exit__(self, *exc):
        self.patch.stop()


def _model_reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class RuleParsingTest(unittest.TestCase):
    """规则兜底是"没配 Key 也能演示"的底线，这些必须可靠"""

    def test_chinese_time_with_half(self):
        with _Env(LLM_API_KEY=""):
            event, _ = ai.parse_event("下午两点半开始下雨")
        self.assertEqual(event["from"], "14:30")

    def test_chinese_time_prefix_carries_over(self):
        """"晚上六点到七点"里的 七点 也应该是 19:00"""
        with _Env(LLM_API_KEY=""):
            event, _ = ai.parse_event("晚上六点到七点可能下雨")
        self.assertEqual(event["from"], "18:00")
        self.assertEqual(event["to"], "19:00")

    def test_quantifier_is_not_a_time(self):
        """'轻松一点' 不是 1 点钟"""
        with _Env(LLM_API_KEY=""):
            prefs, _ = ai.parse_preferences("轻松一点，苏州，下午三点开始")
        self.assertEqual(prefs["startTime"], "15:00")
        self.assertEqual(prefs["pace"], "relaxed")

    def test_negated_interest_becomes_avoid(self):
        """'别爬山' 不能被当成兴趣，应该进 avoid"""
        with _Env(LLM_API_KEY=""):
            prefs, _ = ai.parse_preferences("想拍照、不想早起，别爬山")
        self.assertIn("拍照", prefs["interests"])
        self.assertNotIn("爬山", prefs["interests"])
        self.assertIn("爬山", prefs["avoid"])
        self.assertEqual(prefs["startTime"], "10:30")


class ParsePreferencesTest(unittest.TestCase):
    def test_ai_path_used_when_model_returns_json(self):
        payload = '{"city":"杭州","startTime":"10:30","interests":["拍照","咖啡"],"pace":"relaxed"}'
        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", return_value=_model_reply(payload)):
            prefs, source = ai.parse_preferences("想拍照，喝咖啡，别太早")
        self.assertEqual(source, "ai")
        self.assertEqual(prefs["startTime"], "10:30")
        self.assertIn("拍照", prefs["interests"])
        self.assertEqual(prefs["pace"], "relaxed")

    def test_json_wrapped_in_fence_is_accepted(self):
        payload = '```json\n{"city":"杭州","pace":"packed"}\n```'
        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", return_value=_model_reply(payload)):
            prefs, source = ai.parse_preferences("紧凑一点")
        self.assertEqual(source, "ai")
        self.assertEqual(prefs["pace"], "packed")

    def test_garbage_reply_falls_back_to_rules(self):
        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", return_value=_model_reply("我觉得可以这样安排行程")):
            prefs, source = ai.parse_preferences("不想早起，想去公园")
        self.assertEqual(source, "rule")
        self.assertEqual(prefs["startTime"], "10:30")  # 规则抽到了"不想早起"
        self.assertIn("公园", prefs["interests"])

    def test_network_error_falls_back_to_rules(self):
        def boom(*args, **kwargs):
            raise RuntimeError("timeout")

        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", side_effect=boom):
            prefs, source = ai.parse_preferences("轻松一点，别爬山")
        self.assertEqual(source, "rule")
        self.assertEqual(prefs["pace"], "relaxed")
        self.assertEqual(prefs["avoid"], ["爬山"])

    def test_no_key_means_rule_source(self):
        with _Env(LLM_API_KEY=""):
            prefs, source = ai.parse_preferences("下午出发，城市是苏州")
        self.assertEqual(source, "rule")
        self.assertEqual(prefs["city"], "苏州")

    def test_invalid_time_from_model_is_rejected(self):
        payload = '{"startTime":"下午三点","endTime":"25:99","pace":"crazy"}'
        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", return_value=_model_reply(payload)):
            prefs, source = ai.parse_preferences("中午出发")
        self.assertEqual(source, "ai")
        # 坏值必须被规则结果顶掉，不能流到下游
        self.assertEqual(prefs["startTime"], "11:30")  # 规则从"中午"推断
        self.assertIn(prefs["endTime"], ("20:00",))
        self.assertEqual(prefs["pace"], "normal")

    def test_max_transit_clamped(self):
        payload = '{"maxTransitMin":9999}'
        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", return_value=_model_reply(payload)):
            prefs, _ = ai.parse_preferences("随便")
        self.assertEqual(prefs["maxTransitMin"], 120)


class ParseEventTest(unittest.TestCase):
    def test_ai_event(self):
        payload = '{"type":"rain","from":"14:00","to":"16:00","prob":0.7}'
        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", return_value=_model_reply(payload)):
            event, source = ai.parse_event("下午两点开始下雨，下到四点")
        self.assertEqual(source, "ai")
        self.assertEqual(event["from"], "14:00")
        self.assertEqual(event["to"], "16:00")

    def test_rule_event_rain(self):
        with _Env(LLM_API_KEY=""):
            event, source = ai.parse_event("晚上六点到七点可能下雨")
        self.assertEqual(source, "rule")
        self.assertEqual(event["type"], "rain")
        self.assertEqual(event["from"], "18:00")
        self.assertEqual(event["to"], "19:00")

    def test_rule_event_delay(self):
        with _Env(LLM_API_KEY=""):
            event, source = ai.parse_event("集合晚到 45 分钟")
        self.assertEqual(source, "rule")
        self.assertEqual(event["type"], "delay")
        self.assertEqual(event["minutes"], 45)

    def test_rule_event_cancel(self):
        with _Env(LLM_API_KEY=""):
            event, _ = ai.parse_event("午餐那家取消了")
        self.assertEqual(event["type"], "cancel")

    def test_unknown_text_returns_none(self):
        with _Env(LLM_API_KEY=""):
            event, source = ai.parse_event("今天天气不错")
        self.assertIsNone(event)
        self.assertEqual(source, "rule")

    def test_bad_ai_event_falls_back(self):
        payload = '{"type":"rain","from":"下午","to":"傍晚"}'
        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", return_value=_model_reply(payload)):
            event, source = ai.parse_event("下午下雨")
        self.assertEqual(source, "rule")
        self.assertEqual(event["type"], "rain")


class ExplainTest(unittest.TestCase):
    def test_explain_uses_model_when_available(self):
        with _Env(LLM_API_KEY="test"), patch.object(ai, "_http_post", return_value=_model_reply("舍弃日落，保住晚饭。")):
            text, source = ai.explain_scheme("方案B：改两处，牺牲日落")
        self.assertEqual(source, "ai")
        self.assertIn("日落", text)

    def test_explain_degrades_to_algorithm_summary(self):
        with _Env(LLM_API_KEY=""):
            text, source = ai.explain_scheme("方案B：改两处，牺牲日落")
        self.assertEqual(source, "rule")
        # 降级时至少要原样返回算法给的摘要，不能空
        self.assertEqual(text, "方案B：改两处，牺牲日落")

    def test_available_flag(self):
        with _Env(LLM_API_KEY=""):
            self.assertFalse(ai.available())
        with _Env(LLM_API_KEY="x"):
            self.assertTrue(ai.available())


if __name__ == "__main__":
    unittest.main()
