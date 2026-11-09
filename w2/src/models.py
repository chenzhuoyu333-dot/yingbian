"""
数据结构与公共小工具。

铁律：任何文件都可以 import 这里，这里不 import 任何业务文件。
"""
import json
import os

# ── 四态 + 三种原因 ────────────────────────────
STATE = {
    "OK": "ok",
    "AT_RISK": "at_risk",
    "INVALID": "invalid",
    "CONFLICT": "conflict",
}

REASON = {
    "RAIN": "rain",
    "DELAY": "delay",
    "CANCEL": "cancel",
}

# 严重程度，用来"只升不降"地合并状态
ORDER = {"ok": 0, "at_risk": 1, "invalid": 2, "conflict": 3}

# 项目根目录（src 的上一级）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def to_min(hhmm):
    """'HH:mm' -> 当天分钟数"""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes):
    """当天分钟数 -> 'HH:mm'"""
    m = minutes % 1440
    return "%02d:%02d" % (m // 60, m % 60)


def overlaps(a1, a2, b1, b2):
    """两个区间是否重叠（半开区间，首尾相接不算重叠）"""
    return a1 < b2 and b1 < a2


def covers(a1, a2, b1, b2):
    """a 是否完全被 b 覆盖"""
    return b1 <= a1 and a2 <= b2


def worse(a, b):
    """取更严重的那个状态"""
    return b if ORDER[b] > ORDER[a] else a


def load_plan(rel_path="data/plan-saturday.json"):
    path = os.path.join(ROOT, rel_path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def index_by_id(plan):
    return {n["id"]: n for n in plan["nodes"]}
