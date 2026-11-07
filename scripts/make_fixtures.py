"""Regenerate fixtures/ from the engine so the Android mock stays honest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yingbian import Event, load_plan, propagate, repair


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures"
RAIN = {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7}


def write(name: str, payload: dict) -> None:
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> None:
    plan = load_plan()
    write("plan-saturday.json", {"ok": True, "data": {"plan": plan.to_dict(), "version": 1}})
    write("event-rain-T1.json", {"ok": True, "data": propagate(plan, Event.from_dict(RAIN)).to_dict()})

    schemes = [repair(plan, Event.from_dict(RAIN), key).to_dict() for key in ("A", "B", "C")]
    write(
        "repair-T1.json",
        {"ok": True, "data": {"status": "ok", "schemes": schemes, "blockedNode": None, "message": ""}},
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
            "source": "和风天气（W3 待接入）",
            "fetchedAt": "2026-11-14T17:02",
            "next2hRainProb": 0.7,
            "text": "15:00 起中雨",
        }},
    )


if __name__ == "__main__":
    main()
