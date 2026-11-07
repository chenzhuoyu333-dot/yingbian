"""W1 spec repair: shift / replace / drop, with lock-first blocking.

This is intentionally the rule engine from W1施工图 §3, not the CP-SAT solver:
the demo needs explainable actions and the exact T1-T4 results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .models import Alternative, Node, Plan, format_time
from .propagate import Event, ImpactReport, propagate


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


@dataclass
class Action:
    node_id: str
    action: str
    reason: str
    cost: float
    payload: dict[str, Any] = field(default_factory=dict)
    sacrifice: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "action": self.action,
            "payload": self.payload,
            "reason": self.reason,
            "cost": round(self.cost, 1),
            "sacrifice": self.sacrifice,
        }


@dataclass
class RepairResult:
    status: str
    scheme: str
    label: str
    actions: list[Action]
    blocked_node: str | None
    message: str
    keep_rate: float
    changed_count: int
    plan: Plan
    elapsed_ms: float

    @property
    def sacrifice(self) -> str:
        parts = [action.sacrifice for action in self.actions if action.sacrifice]
        return "；".join(parts) if parts else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "id": self.scheme,
            "label": self.label,
            "keepRate": round(self.keep_rate, 4),
            "changedCount": self.changed_count,
            "actions": [action.to_dict() for action in self.actions],
            "sacrifice": self.sacrifice,
            "blockedNode": self.blocked_node,
            "message": self.message,
            "elapsedMs": round(self.elapsed_ms, 1),
        }


def _shift_minutes(node: Node, event: Event, state: str) -> int | None:
    # Shifting only helps a rain-affected node: move it past the rain window.
    if event.type != "rain" or event.end is None or state != "at_risk":
        return None
    needed = max(0, event.end - node.start)
    if needed <= 0:
        return None
    new_start = node.start + needed
    if node.window_latest is not None and new_start > node.window_latest:
        return None
    return needed


def _replace_helps(node: Node, alt: Alternative, event: Event) -> bool:
    if event.type == "rain":
        return alt.indoor
    if event.type in {"cancel", "closed"}:
        return alt.id != node.id
    return True


def _keep_rate(original: Plan, working: Plan) -> float:
    locked = original.confirmed_nodes()
    if not locked:
        return 1.0
    preserved = 0
    for node in locked:
        now = working.find(node.id)
        if now is None or now.dropped:
            continue
        if now.start == node.start and now.end == node.end:
            preserved += 1
    return preserved / len(locked)


def _blocked(plan: Plan, report: ImpactReport, scheme: Scheme, started: float) -> RepairResult:
    node = report.blocked_node(plan)
    message = ""
    if node is not None:
        message = f"「{node.title}」是你锁定的，但会受影响。要解锁吗？"
    return RepairResult(
        status="blocked",
        scheme=scheme.key,
        label=scheme.label,
        actions=[],
        blocked_node=node.node_id if node else None,
        message=message,
        keep_rate=1.0,
        changed_count=0,
        plan=plan.clone(),
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def repair(plan: Plan, event: Event, scheme_key: str = "B", max_rounds: int = 3) -> RepairResult:
    scheme = SCHEMES[scheme_key]
    started = time.perf_counter()
    working = plan.clone()
    report = propagate(working, event)
    if report.blocked:
        return _blocked(plan, report, scheme, started)

    actions: list[Action] = []
    for _ in range(max_rounds):
        report = propagate(working, event)
        if report.blocked:
            return _blocked(plan, report, scheme, started)
        unresolved = sorted(
            [
                node
                for node in working.nodes
                if not node.dropped and report.states.get(node.id, "ok") != "ok"
            ],
            key=lambda node: node.start,
        )
        if not unresolved:
            break
        progressed = False
        for node in unresolved:
            state = report.states.get(node.id, "ok")
            if state == "ok":
                continue
            if node.confirmed and state == "at_risk":
                return _blocked(plan, report, scheme, started)

            candidates: list[tuple[float, int, Action, Alternative | None]] = []
            minutes = _shift_minutes(node, event, state)
            if minutes is not None:
                candidates.append((
                    minutes * scheme.w_shift,
                    1,
                    Action(
                        node_id=node.id,
                        action="shift",
                        reason=f"后移 {minutes} 分钟避开降雨",
                        cost=minutes * scheme.w_shift,
                        payload={"minutes": minutes},
                        sacrifice="",
                    ),
                    None,
                ))
            for alt in node.alternatives:
                if not _replace_helps(node, alt, event):
                    continue
                cost = scheme.w_replace + alt.travel_min * 0.5
                candidates.append((
                    cost,
                    0,
                    Action(
                        node_id=node.id,
                        action="replace",
                        reason=f"改去「{alt.title}」",
                        cost=cost,
                        payload={
                            "alternativeId": alt.id,
                            "fromTitle": node.title,
                            "toTitle": alt.title,
                        },
                        sacrifice=alt.sacrifice or f"改去{alt.title}",
                    ),
                    alt,
                ))
            drop_allowed = not (node.confirmed and state == "at_risk")
            if drop_allowed:
                candidates.append((
                    scheme.w_drop,
                    2,
                    Action(
                        node_id=node.id,
                        action="drop",
                        reason=(
                            "备选代价更高，选择放弃"
                            if node.alternatives
                            else ("没有可用的室内备选" if event.type == "rain" else "跳过该节点")
                        ),
                        cost=scheme.w_drop,
                        sacrifice=node.sacrifice or f"放弃{node.title}",
                    ),
                    None,
                ))
            if not candidates:
                return _blocked(plan, report, scheme, started)

            _, _, action, alt = min(candidates, key=lambda item: (item[0], item[1]))
            _apply_action(node, action, alt)
            actions.append(action)
            progressed = True
            report = propagate(working, event)
            if report.blocked:
                return _blocked(plan, report, scheme, started)
        if not progressed:
            break

    final_report = propagate(working, event)
    status = "ok" if all(state == "ok" for state in final_report.states.values()) else "partial"
    return RepairResult(
        status=status,
        scheme=scheme.key,
        label=scheme.label,
        actions=actions,
        blocked_node=None,
        message="",
        keep_rate=_keep_rate(plan, working),
        changed_count=len(actions),
        plan=working,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def _apply_action(node: Node, action: Action, alt: Alternative | None) -> None:
    if action.action == "shift":
        minutes = int(action.payload["minutes"])
        node.start += minutes
        node.end += minutes
    elif action.action == "replace":
        if alt is None:
            raise ValueError("replace 缺少备选")
        node.title = alt.title
        node.indoor = alt.indoor
        node.start = alt.start
        node.end = alt.end
        node.place = alt.place
        node.sacrifice = alt.sacrifice
        node.contact = alt.contact or node.contact
        node.resolved = True
    elif action.action == "drop":
        node.dropped = True
    else:
        raise ValueError(f"未知动作: {action.action}")


def apply_actions(plan: Plan, actions: list[dict[str, Any]]) -> Plan:
    working = plan.clone()
    for raw in actions:
        node = working.find(raw["nodeId"])
        if node is None:
            continue
        kind = raw["action"]
        payload = raw.get("payload", {})
        alt = None
        if kind == "replace":
            alt = next((a for a in node.alternatives if a.id == payload.get("alternativeId")), None)
        _apply_action(node, Action(node.id, kind, "", 0, payload), alt)
    working.version = plan.version + 1
    return working


def render_result(result: RepairResult) -> str:
    if result.status == "blocked":
        return f"方案 {result.scheme} · {result.label}\n  阻断：{result.message}"
    lines = [
        f"方案 {result.scheme} · {result.label}",
        f"  动作 {result.changed_count} 个｜保留率 {result.keep_rate:.0%}｜耗时 {result.elapsed_ms:.0f} ms",
    ]
    for action in result.actions:
        detail = action.payload.get("minutes")
        if detail:
            lines.append(f"  - {action.node_id} {action.action} {detail} 分钟：{action.reason}")
        else:
            lines.append(f"  - {action.node_id} {action.action}：{action.reason}")
    if result.sacrifice:
        lines.append(f"  牺牲：{result.sacrifice}")
    return "\n".join(lines)
