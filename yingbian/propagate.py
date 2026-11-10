"""W1 spec impact propagation: four states + shifts + ratio.

States: ok / at_risk / invalid / conflict.
`conflict` means the node is confirmed (locked) and would need to move, so the
system must stop and ask the user instead of repairing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Plan, format_time, parse_time
from .rules import RAIN_IGNORE_PROB, RATIO_LOCAL_MAX, RATIO_VOTE_MAX


STATE_RANK = {"ok": 0, "at_risk": 1, "conflict": 2, "invalid": 3}
STATE_LABEL = {"ok": "正常", "at_risk": "有风险", "conflict": "锁定冲突", "invalid": "不可行"}
PATH_LABEL = {"local": "局部修复", "vote": "发起变更投票", "global": "全体共同变更"}


def _worse(current: str, candidate: str) -> str:
    return candidate if STATE_RANK[candidate] > STATE_RANK[current] else current


@dataclass(frozen=True)
class Event:
    type: str
    start: int | None = None
    end: int | None = None
    prob: float = 1.0
    node_id: str | None = None
    minutes: int = 0
    person_id: str | None = None
    label: str = ""

    def summary(self) -> str:
        if self.label:
            return self.label
        if self.type == "rain":
            return (
                f"降雨 {format_time(self.start)}–{format_time(self.end)}"
                f"（概率 {self.prob:.0%}）"
            )
        if self.type in {"cancel", "closed"}:
            return f"{'取消' if self.type == 'cancel' else '临时关闭'} {self.node_id}"
        if self.type == "delay":
            return f"{self.node_id} 延后 {self.minutes} 分钟"
        if self.type == "memberLate":
            return f"{self.person_id} 晚到 {self.minutes} 分钟"
        return self.type

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Event":
        return cls(
            type=raw["type"],
            start=parse_time(raw.get("from")),
            end=parse_time(raw.get("to")),
            prob=float(raw.get("prob", 1.0)),
            node_id=raw.get("nodeId"),
            minutes=int(raw.get("minutes", 0)),
            person_id=raw.get("personId"),
            label=raw.get("label", ""),
        )


@dataclass
class NodeImpact:
    node_id: str
    title: str
    state: str
    start: int
    shift: int
    reason: str
    confirmed: bool


@dataclass
class ImpactReport:
    event: Event | None
    states: dict[str, str]
    shifts: dict[str, int]
    ratio: float
    path: str
    affected_count: int
    total_count: int
    details: dict[str, NodeImpact]
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return any(state == "conflict" for state in self.states.values())

    def blocked_node(self, plan: Plan) -> NodeImpact | None:
        conflicts = [
            item for item in self.details.values() if item.state == "conflict"
        ]
        if not conflicts:
            return None
        return sorted(conflicts, key=lambda item: item.start)[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "states": dict(self.states),
            "shifts": dict(self.shifts),
            "ratio": round(self.ratio, 4),
            "path": self.path,
            "affectedCount": self.affected_count,
            "totalCount": self.total_count,
        }


def _overlaps(node_start: int, node_end: int, event_start: int, event_end: int) -> bool:
    return node_start < event_end and node_end > event_start


def _direct_hit(node, event: Event) -> tuple[str, int, str]:
    """Returns (state, shift, reason) for the direct hit, before propagation."""
    if event.type in {"cancel", "closed"} and node.id == event.node_id:
        return "invalid", 0, "餐厅取消" if event.type == "cancel" else "临时关闭"
    if event.type == "delay" and node.id == event.node_id:
        return "at_risk", event.minutes, f"上游延后 {event.minutes} 分钟"
    if event.type == "rain" and event.start is not None and event.end is not None:
        if event.prob < RAIN_IGNORE_PROB:
            return "ok", 0, ""
        if node.indoor:
            return "ok", 0, ""
        if _overlaps(node.start, node.end, event.start, event.end):
            return "at_risk", 0, f"室外 + 降雨概率 {event.prob:.0%}"
    return "ok", 0, ""


def _apply_confirmed_rule(node, state: str) -> str:
    # A locked node that is only at risk must be surfaced as a conflict.
    # A locked node that is already invalid stays invalid: the thing is gone,
    # replacing it at the same slot is still possible (see T3).
    if node.confirmed and state == "at_risk":
        return "conflict"
    return state


def propagate(plan: Plan, event: Event | None = None) -> ImpactReport:
    states = {node.id: "ok" for node in plan.nodes}
    shifts = {node.id: 0 for node in plan.nodes}
    reasons = {node.id: "" for node in plan.nodes}

    if event is not None:
        # memberLate: first version maps to the first node the person participates in
        if event.type == "memberLate":
            candidates = [node for node in plan.nodes if event.person_id in node.persons]
            target = sorted(candidates, key=lambda n: n.start)[0] if candidates else plan.nodes[0]
            event = Event(
                type="delay",
                node_id=target.id,
                minutes=event.minutes,
                label=event.label or f"{event.person_id} 晚到 {event.minutes} 分钟",
            )

        for node in plan.nodes:
            if node.dropped or node.resolved:
                continue
            state, shift, reason = _direct_hit(node, event)
            if shift:
                shifts[node.id] = max(shifts[node.id], shift)
            if state != "ok":
                state = _apply_confirmed_rule(node, state)
                states[node.id] = _worse(states[node.id], state)
                reasons[node.id] = reasons[node.id] or reason

    # Propagate shifts until stable. Edges are processed by source start time,
    # so a single pass handles a linear plan; the outer loop handles branches.
    changed = True
    guard = 0
    while changed and guard < len(plan.edges) + 2:
        changed = False
        guard += 1
        for edge in sorted(plan.edges_of("precedes", "requires"), key=lambda e: plan.node(e.src).start):
            src = plan.find(edge.src)
            dst = plan.find(edge.dst)
            if src is None or dst is None or src.dropped or dst.dropped:
                continue
            # 缓冲 = 这条边的天然余量（实际间隙 − 最小间隙）。
            # 上游后移时先用缓冲吸收，吸不完的部分才顶到下游。
            # 没有这一步，计划里留的缓冲等于白留 —— 任何延误都会顶穿整条链，
            # 于是"最小修复"永远没得改，只可能 blocked。
            slack = max(0, (dst.start - src.end) - edge.min_gap)
            needed = max(0, shifts[src.id] - slack)
            if needed <= shifts[dst.id]:
                continue
            shifts[dst.id] = needed
            new_start = dst.start + needed
            level = "at_risk"
            reason = f"上游 {src.id} 后移超出缓冲（余量 {slack} 分），本节点后移 {needed} 分"
            if dst.window_latest is not None and new_start > dst.window_latest:
                level = "invalid"
                reason = f"新开始 {format_time(new_start)} 晚于最晚 {format_time(dst.window_latest)}"
            state = _apply_confirmed_rule(dst, level)
            if STATE_RANK[state] > STATE_RANK[states[dst.id]]:
                states[dst.id] = state
                reasons[dst.id] = reason
                changed = True

    active = [node for node in plan.nodes if not node.dropped]
    affected = [node for node in active if states[node.id] != "ok"]
    total = len(active)
    ratio = len(affected) / total if total else 0.0
    if ratio <= RATIO_LOCAL_MAX:
        path = "local"
    elif ratio <= RATIO_VOTE_MAX:
        path = "vote"
    else:
        path = "global"

    details = {
        node.id: NodeImpact(
            node_id=node.id,
            title=node.title,
            state=states[node.id],
            start=node.start + shifts[node.id],
            shift=shifts[node.id],
            reason=reasons[node.id],
            confirmed=node.confirmed,
        )
        for node in plan.nodes
        if not node.dropped
    }
    return ImpactReport(
        event=event,
        states=states,
        shifts=shifts,
        ratio=ratio,
        path=path,
        affected_count=len(affected),
        total_count=total,
        details=details,
        reasons=reasons,
    )


def render(report: ImpactReport) -> str:
    lines = [
        f"事件：{report.event.summary() if report.event else '基线（无事件）'}",
        f"影响面：{report.affected_count}/{report.total_count} = {report.ratio:.0%}"
        f" → {PATH_LABEL[report.path]}",
        "",
        f"{'节点':<12}{'状态':<8}{'计划':<7}{'新开始':<8}{'后移':<6}说明",
    ]
    for item in report.details.values():
        lines.append(
            f"{item.node_id:<12}{STATE_LABEL[item.state]:<8}"
            f"{format_time(item.start - item.shift):<7}"
            f"{format_time(item.start):<8}{item.shift:<6}{item.reason}"
        )
    return "\n".join(lines)
