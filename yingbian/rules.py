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


SCHEMES: dict[str, Scheme] = {
    "A": Scheme("A", "保时间", w_shift=0.2, w_replace=100, w_drop=100),
    "B": Scheme("B", "保体验", w_shift=1, w_replace=50, w_drop=100),
    "C": Scheme("C", "保少改动", w_shift=3, w_replace=60, w_drop=200),
}
