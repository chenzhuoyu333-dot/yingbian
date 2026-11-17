"""All tunable numbers live here.

Judges and teammates should only need this file to answer "why this threshold".
"""

from __future__ import annotations

from dataclasses import dataclass

# Rain below this probability is ignored entirely.
RAIN_IGNORE_PROB = 0.30

# Affected ratio decides the repair path: local / vote / global.
RATIO_LOCAL_MAX = 0.30
RATIO_VOTE_MAX = 0.60

# Safety cap for the repair loop.
MAX_REPAIR_ROUNDS = 3


@dataclass(frozen=True)
class Scheme:
    key: str
    label: str
    w_shift: float
    w_replace: float
    w_drop: float
    # 每处改动的固定代价。
    # 没有这一项，"保少改动"就只是"挪动更贵"，
    # 一旦"挪"和"换"的价差落进同一区间，C 会和 B 选出完全一样的动作。
    w_action: float = 0.0


SCHEMES: dict[str, Scheme] = {
    # 保时间：宁可挪，也不换点；几乎不在意改动处数
    "A": Scheme("A", "保时间", w_shift=0.2, w_replace=100, w_drop=600, w_action=0),
    # 保体验：优先换备选，尽量不删
    "B": Scheme("B", "保体验", w_shift=1, w_replace=50, w_drop=100, w_action=20),
    # 保少改动：宁可一处挪很久，也不要改三处
    "C": Scheme("C", "保少改动", w_shift=3, w_replace=60, w_drop=200, w_action=150),
}
