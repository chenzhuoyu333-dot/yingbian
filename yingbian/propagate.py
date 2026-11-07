"""Impact propagation: event -> node states -> downstream risk.

This is the classic critical-path-method pass over a DAG, plus a small
weather/closure classifier. It is intentionally dependency-free so it can run
inside the Android backend, a Lambda, or a plain CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Node, Plan, format_time


STATE_ORDER = {"ok": 0, "at_risk": 1, "invalid": 2, "inactive": 3}
SEVERITY_LABEL = {"local": "局部变化", "medium": "中等变化", "major": "不可抗力 / 重构"}
STATE_LABEL = {"ok": "正常", "at_risk": "有风险", "invalid": "不可行", "inactive": "未启用"}


def worsen(current: str, candidate: str) -> str:
    return candidate if STATE_ORDER[candidate] > STATE_ORDER[current] else current


@dataclass(frozen=True)
class Event:
    type: str
    start: int | None = None
    end: int | None = None
    node_ids: tuple[str, ...] = ()
    label: str = ""
    intensity: str = "moderate"

    def window(self) -> tuple[int, int] | None:
        if self.start is None:
            return None
        return self.start, self.end if self.end is not None else self.start + 120

    def summary(self) -> str:
        if self.label:
            return self.label
        if self.type == "rain" and self.start is not None:
            end = self.end if self.end is not None else self.start + 120
            return f"降雨 {format_time(self.start)}–{format_time(end)}"
        if self.type == "closure":
            return f"临时封闭：{', '.join(self.node_ids)}"
        return self.type


@dataclass
class NodeImpact:
    node_id: str
    title: str
    state: str
    planned_start: int
    start: int
    finish: int
    persons: list[str]
    slack: int | None = None
    reason: str = ""

    @property
    def affected(self) -> bool:
        return self.state in {"at_risk", "invalid"}


@dataclass
class ImpactReport:
    event: Event | None
    nodes: dict[str, NodeImpact]
    impact_ratio: float
    severity: str
    affected: list[str] = field(default_factory=list)
    affected_persons: list[str] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    locked_preserved: bool = True


def classify(node: Node, event: Event | None) -> tuple[str, str]:
    if not node.active:
        return "inactive", "备选未启用"
    if event is None:
        return "ok", ""
    if node.id in event.node_ids:
        return "invalid", f"事件直接命中：{event.summary()}"
    if event.type == "rain" and event.start is not None and node.outdoor:
        rain_start, rain_end = event.window() or (event.start, event.start + 120)
        overlap_start = max(node.start, rain_start)
        overlap_end = min(node.end, rain_end)
        if overlap_start < overlap_end:
            if node.weather_risk == "cancel":
                return "invalid", f"室外活动遇降雨（{format_time(overlap_start)}–{format_time(overlap_end)}）"
            if node.weather_risk == "degrade":
                return "at_risk", "室外活动受降雨影响，可保留但体验下降"
    return "ok", ""


def analyze(plan: Plan, event: Event | None = None) -> ImpactReport:
    order = plan.topo_order()
    states: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for node in plan.nodes:
        state, reason = classify(node, event)
        states[node.id] = state
        reasons[node.id] = reason

    starts: dict[str, int] = {}
    finishes: dict[str, int] = {}

    for node_id in order:
        node = plan.node(node_id)
        if not node.active:
            starts[node_id] = node.start
            finishes[node_id] = node.end
            continue

        preds = [plan.node(pid) for pid in plan.predecessors(node_id) if plan.node(pid).active]
        for pred in preds:
            if states[pred.id] in {"invalid", "at_risk"}:
                states[node_id] = worsen(states[node_id], "at_risk")
                reasons[node_id] = reasons[node_id] or f"上游 {pred.id} {STATE_LABEL[states[pred.id]]}"

        if states[node_id] == "invalid":
            starts[node_id] = node.start
            finishes[node_id] = node.end
            continue

        earliest = node.start
        for pred in preds:
            earliest = max(earliest, finishes[pred.id] + plan.travel_between(pred.id, node.id))
        if earliest > node.start:
            states[node_id] = worsen(states[node_id], "at_risk")
            reasons[node_id] = reasons[node_id] or "前序完成时间推迟"

        if node.window and earliest < node.window.start:
            earliest = node.window.start
        if node.window and earliest > node.window.end:
            states[node_id] = worsen(states[node_id], "at_risk")
            reasons[node_id] = reasons[node_id] or "超出时间窗"

        finish = earliest + node.duration
        if node.deadline is not None and finish > node.deadline:
            states[node_id] = worsen(states[node_id], "at_risk")
            reasons[node_id] = reasons[node_id] or "超过最晚结束时间"

        starts[node_id] = earliest
        finishes[node_id] = finish

    impacts: dict[str, NodeImpact] = {}
    for node in plan.nodes:
        start = starts.get(node.id, node.start)
        finish = finishes.get(node.id, node.end)
        slack = node.window.end - start if node.window and node.active else None
        impacts[node.id] = NodeImpact(
            node_id=node.id,
            title=node.title,
            state=states[node.id],
            planned_start=node.start,
            start=start,
            finish=finish,
            persons=list(node.persons),
            slack=slack,
            reason=reasons[node.id],
        )

    active = [node.id for node in plan.nodes if node.active]
    affected = [node_id for node_id in active if impacts[node_id].affected]
    ratio = len(affected) / len(active) if active else 0.0
    severity = "local" if ratio <= 0.30 else "medium" if ratio <= 0.60 else "major"
    persons = sorted(
        {person for node_id in affected for person in impacts[node_id].persons},
        key=lambda pid: int(pid[1:]) if pid[1:].isdigit() else pid,
    )
    locked_preserved = all(
        impacts[node.id].start == node.start for node in plan.nodes if node.active and node.locked
    )
    return ImpactReport(
        event=event,
        nodes=impacts,
        impact_ratio=ratio,
        severity=severity,
        affected=affected,
        affected_persons=persons,
        critical_path=_critical_path(plan),
        locked_preserved=locked_preserved,
    )


def _critical_path(plan: Plan) -> list[str]:
    order = plan.topo_order()
    best: dict[str, int] = {}
    previous: dict[str, str | None] = {}
    for node_id in order:
        node = plan.node(node_id)
        if not node.active:
            continue
        best_len = 0
        best_pred: str | None = None
        for pred_id in plan.predecessors(node_id):
            pred = plan.node(pred_id)
            if not pred.active or pred_id not in best:
                continue
            candidate = best[pred_id] + plan.travel_between(pred_id, node_id)
            if candidate > best_len:
                best_len, best_pred = candidate, pred_id
        best[node_id] = best_len + node.duration
        previous[node_id] = best_pred
    if not best:
        return []
    tail = max(best, key=best.get)
    path: list[str] = []
    cursor: str | None = tail
    while cursor:
        path.append(cursor)
        cursor = previous.get(cursor)
    return list(reversed(path))


def render(report: ImpactReport, plan: Plan) -> str:
    lines = []
    event_text = report.event.summary() if report.event else "基线（无事件）"
    lines.append(f"事件：{event_text}")
    lines.append(
        f"影响面：{len(report.affected)} 个节点 / {len(plan.active_nodes())} 个活动节点"
        f" = {report.impact_ratio:.0%} → {SEVERITY_LABEL[report.severity]}"
    )
    lines.append("")
    lines.append(f"{'节点':<5}{'状态':<7}{'计划':<7}{'最早':<7}{'结束':<7}{'缓冲':<6}说明")
    for node in plan.nodes:
        impact = report.nodes[node.id]
        if impact.state == "inactive":
            continue
        slack = "-" if impact.slack is None else str(impact.slack)
        lines.append(
            f"{node.id:<5}{STATE_LABEL[impact.state]:<7}"
            f"{format_time(impact.planned_start):<7}{format_time(impact.start):<7}"
            f"{format_time(impact.finish):<7}{slack:<6}{impact.reason}"
        )
    lines.append("")
    lines.append(f"关键路径：{' → '.join(report.critical_path)}")
    lines.append(f"需要知情的人：{', '.join(report.affected_persons) or '无'}")
    return "\n".join(lines)
