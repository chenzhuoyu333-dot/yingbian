"""Regenerate fixtures/ (and the Android copy) from the engine.

The app's offline mock must be produced by the same code path as the API,
otherwise the demo can drift away from the real behaviour.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yingbian import Event, load_plan, propagate, repair


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures"
ASSETS = ROOT / "android" / "app" / "src" / "main" / "assets" / "fixtures"
RAIN = {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7}
CANCEL = {"type": "cancel", "nodeId": "n_lunch"}


def write(name: str, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for folder in (OUT, ASSETS):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    print(f"wrote {name}")


def freeze_timing(schemes: list[dict]) -> list[dict]:
    """Timing is noise for a fixture; keep regeneration diffs empty."""
    for scheme in schemes:
        scheme["elapsedMs"] = 0
    return schemes


def main() -> None:
    plan = load_plan()
    write("plan-saturday.json", {"ok": True, "data": {"plan": plan.to_dict(), "version": 1}})
    write("event-rain-T1.json", {"ok": True, "data": propagate(plan, Event.from_dict(RAIN)).to_dict()})

    schemes = freeze_timing([repair(plan, Event.from_dict(RAIN), key).to_dict() for key in ("A", "B", "C")])
    write(
        "repair-T1.json",
        {"ok": True, "data": {"status": "ok", "schemes": schemes, "blockedNode": None, "message": ""}},
    )

    write("event-cancel-T3.json", {"ok": True, "data": propagate(plan, Event.from_dict(CANCEL)).to_dict()})
    schemes_t3 = freeze_timing([repair(plan, Event.from_dict(CANCEL), key).to_dict() for key in ("A", "B", "C")])
    write(
        "repair-T3.json",
        {"ok": True, "data": {"status": "ok", "schemes": schemes_t3, "blockedNode": None, "message": ""}},
    )

    locked = plan.clone()
    locked.node("n_sunset").confirmed = True
    blocked = repair(locked, Event.from_dict(RAIN), "B")
    write(
        "blocked-T4.json",
        {"ok": True, "data": {
            "status": "blocked",
            "schemes": [],
            "blockedNode": blocked.blocked_node,
            "message": blocked.message,
        }},
    )
    write(
        "weather.json",
        {"ok": True, "data": {
            "source": "演示数据（Android 离线 mock）",
            "isDemo": True,
            "fetchedAt": "2026-11-14T17:02",
            "next2hRainProb": 0.7,
            "text": "15:00 起中雨",
            "note": "这是演示数据，不是真实预报；连上后端后显示真实来源。",
        }},
    )


if __name__ == "__main__":
    main()
