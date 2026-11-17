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
    # 没有这一项，"少改动"就只是"挪动更贵"，
    # 一旦"挪"和"换"的价差落进同一区间，C 会和 B 选出完全一样的动作。
    w_action: float = 0.0


SCHEMES: dict[str, Scheme] = {
    # 保时间：时间可以让，内容不能让。
    # shift 极便宜 → 能挪就挪；replace / drop 贵到几乎不会选。
    "A": Scheme("A", "保时间", w_shift=0.2, w_replace=300, w_drop=1500, w_action=0),
    # 保体验：内容不能让，但可以换地方。
    # replace 便宜（50）→ 有备选就换；
    # shift 定得贵（4/分）→ 只要挪动超过约 15 分钟，就宁可选备选；
    # drop 提到 1200 → 没有备选时宁可挪很久也不删点。
    "B": Scheme("B", "保体验", w_shift=4, w_replace=50, w_drop=1200, w_action=15),
}
