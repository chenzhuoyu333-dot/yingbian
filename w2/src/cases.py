"""
四个测试用例的"标准答案"。

这些答案是对着手推的表写下来的（W1施工图 第 4 节）。
程序跑不出这个结果 = 程序错，不是答案错。

※ 实现过程中发现施工图里 T2 的两处预期写错了，已在此修正：
   - n_lunch / n_dinner 是"已锁定"的，被顶掉时应为 conflict，不是 invalid
   - n_sunset 后移 60 分钟后是 16:30，未超过 windowLatest 16:40，应为 at_risk
"""


def _lock_sunset(plan):
    for n in plan["nodes"]:
        if n["id"] == "n_sunset":
            n["confirmed"] = True
    return plan


CASES = {
    "T1": {
        "title": "下雨（15:00–17:00，概率 70%）",
        "event": {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7},
        "expect": {
            "states": {"n_sunset": "at_risk", "n_photo": "at_risk"},
            "ok_count": 10,
            "ratio": 0.1667,
            "path": "local",
        },
        "expect_repair": {
            "status": "ok",
            "changed_count": 2,
            "keep_rate": 1.0,
            "actions": {"n_sunset": "replace", "n_photo": "drop"},
        },
    },
    "T2": {
        "title": "成员晚到 1 小时（全网连锁）",
        "event": {"type": "delay", "nodeId": "n_meet", "minutes": 60},
        "expect": {
            "path": "global",
            "ratio": 1.0,
            "conflicts": ["n_meet", "n_town", "n_lunch", "n_transit_back", "n_dinner"],
        },
        "expect_repair": {"status": "blocked", "blocked_node": "n_meet"},
    },
    "T3": {
        "title": "餐厅取消预订（只改 1 处）",
        "event": {"type": "cancel", "nodeId": "n_lunch"},
        "expect": {
            "states": {"n_lunch": "invalid"},
            "ok_count": 11,
            "ratio": 0.0833,
            "path": "local",
        },
        "expect_repair": {
            "status": "ok",
            "changed_count": 1,
            "keep_rate": 1.0,
            "actions": {"n_lunch": "replace"},
        },
    },
    "T4": {
        "title": "下雨 + 用户锁定了日落点（必须停下来问人）",
        "event": {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7},
        "mutate": _lock_sunset,
        "expect": {
            "states": {"n_sunset": "conflict", "n_photo": "at_risk"},
            "path": "local",
        },
        "expect_repair": {"status": "blocked", "blocked_node": "n_sunset"},
    },
}
