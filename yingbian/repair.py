"""Minimum-change repair with OR-Tools CP-SAT.

The hard part is not re-planning; it is *not* re-planning. Locked nodes are
equality constraints, and everything else carries a change penalty. Three
weight profiles produce the three plans shown to the user.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .models import Node, Plan, format_time
from .propagate import Event, classify


class RepairError(RuntimeError):
    """Raised when no repair can satisfy the hard constraints."""


@dataclass(frozen=True)
class SchemeSpec:
    key: str
    name: str
    tagline: str
    w_change: int
    w_notify: int
    w_late: int
    w_buffer: int
    w_risk: int = 0


DEFAULT_SCHEMES: tuple[SchemeSpec, ...] = (
    SchemeSpec("A", "最小改动", "只动必要节点", w_change=100, w_notify=5, w_late=20, w_buffer=0),
    SchemeSpec("B", "最少打扰", "需要通知的人最少", w_change=20, w_notify=50, w_late=20, w_buffer=0),
    SchemeSpec("C", "最稳妥", "宁可多改一处，也不留室外风险", w_change=20, w_notify=5, w_late=20, w_buffer=5, w_risk=60),
)


@dataclass
class Change:
    node_id: str
    title: str
    old_start: int
    new_start: int
    old_active: bool
    new_active: bool
    persons: list[str]

    def describe(self) -> str:
        if self.old_active and not self.new_active:
            return f"{self.node_id} {self.title}：取消"
        if not self.old_active and self.new_active:
            return f"{self.node_id} {self.title}：启用"
        if self.old_start != self.new_start:
            return (
                f"{self.node_id} {self.title}：{format_time(self.old_start)}"
                f" → {format_time(self.new_start)}"
            )
        return f"{self.node_id} {self.title}：变更"


@dataclass
class RepairResult:
    scheme: SchemeSpec
    status: str
    starts: dict[str, int]
    active: dict[str, bool]
    changes: list[Change] = field(default_factory=list)
    changed_persons: list[str] = field(default_factory=list)
    locked_preserved: bool = True
    objective: float = 0.0
    solve_ms: float = 0.0
    note: str = ""

    @property
    def changed_count(self) -> int:
        return len(self.changes)

    def summary(self) -> str:
        return (
            f"改动 {self.changed_count} 个节点，锁定项"
            f"{'全部未动' if self.locked_preserved else '被破坏'}，"
            f"需通知 {len(self.changed_persons)} 人"
        )


def invalid_nodes(plan: Plan, event: Event | None) -> set[str]:
    return {
        node.id
        for node in plan.nodes
        if node.active and classify(node, event)[0] == "invalid"
    }


def risky_nodes(plan: Plan, event: Event | None) -> set[str]:
    return {
        node.id
        for node in plan.nodes
        if node.active and classify(node, event)[0] == "at_risk"
    }


def _apply_original(plan: Plan, starts: dict[str, int], active: dict[str, bool]) -> None:
    for node in plan.nodes:
        starts[node.id] = node.start
        active[node.id] = node.active


def _make_changes(plan: Plan, starts: dict[str, int], active: dict[str, bool]) -> list[Change]:
    changes: list[Change] = []
    for node in plan.nodes:
        new_start = starts[node.id]
        new_active = active[node.id]
        if new_start != node.start or new_active != node.active:
            changes.append(
                Change(
                    node_id=node.id,
                    title=node.title,
                    old_start=node.start,
                    new_start=new_start,
                    old_active=node.active,
                    new_active=new_active,
                    persons=list(node.persons),
                )
            )
    return changes


def _changed_persons(plan: Plan, changes: list[Change]) -> list[str]:
    person_ids = {person for change in changes for person in change.persons}
    return sorted(
        person_ids,
        key=lambda pid: int(pid[1:]) if pid[1:].isdigit() else pid,
    )


def repair(
    plan: Plan,
    event: Event | None,
    schemes: tuple[SchemeSpec, ...] = DEFAULT_SCHEMES,
    time_limit: float = 2.0,
    use_cpsat: bool = True,
) -> list[RepairResult]:
    invalid = invalid_nodes(plan, event)
    risky = risky_nodes(plan, event)
    _precheck(plan, invalid)
    results: list[RepairResult] = []
    for spec in schemes:
        if use_cpsat:
            try:
                results.append(_solve_cpsat(plan, invalid, risky, spec, time_limit))
                continue
            except ImportError:
                pass
        results.append(_solve_greedy(plan, invalid, spec))
    _mark_duplicates(results)
    return results


def _precheck(plan: Plan, invalid: set[str]) -> None:
    for node_id in invalid:
        node = plan.node(node_id)
        if node.locked:
            raise RepairError(f"锁定节点 {node_id} {node.title} 被事件判为不可行，需要人来决定")
        if node.alt_group is None and node.kind != "slot":
            raise RepairError(f"节点 {node_id} {node.title} 没有备选，无法自动修复")
    for group, nodes in plan.alt_groups().items():
        if all(node.id in invalid for node in nodes):
            raise RepairError(f"备选组 {group} 全部不可行，需要人来决定")


def _solve_cpsat(
    plan: Plan,
    invalid: set[str],
    risky: set[str],
    spec: SchemeSpec,
    time_limit: float,
) -> RepairResult:
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise ImportError("未安装 ortools") from exc

    started = time.perf_counter()
    for relax in (False, True):
        model, variables = _build_model(cp_model, plan, invalid, risky, spec, relax)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_search_workers = 8
        status = solver.Solve(model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            elapsed = (time.perf_counter() - started) * 1000
            return _extract(plan, spec, solver, variables, status == cp_model.OPTIMAL, elapsed)
        if status == cp_model.INFEASIBLE and not relax:
            continue
        raise RepairError(f"CP-SAT 无法求解（状态 {solver.StatusName(status)}）")
    raise RepairError("CP-SAT 无法求解")


def _build_model(
    cp_model,
    plan: Plan,
    invalid: set[str],
    risky: set[str],
    spec: SchemeSpec,
    relax: bool,
):
    model = cp_model.CpModel()
    horizon = 24 * 60
    active: dict[str, object] = {}
    start: dict[str, object] = {}
    end: dict[str, object] = {}
    changed: dict[str, object] = {}
    switched: dict[str, object] = {}
    touched: dict[str, object] = {}
    late: dict[str, object] = {}
    shift: dict[str, object] = {}
    groups = plan.alt_groups()

    for node in plan.nodes:
        start[node.id] = model.NewIntVar(0, horizon, f"start_{node.id}")
        end[node.id] = model.NewIntVar(0, horizon, f"end_{node.id}")
        if node.alt_group:
            active[node.id] = model.NewBoolVar(f"active_{node.id}")
        elif node.kind == "slot":
            active[node.id] = model.NewBoolVar(f"active_{node.id}")
        else:
            active[node.id] = model.NewConstant(1)
            if node.id in invalid:
                if node.kind == "slot":
                    active[node.id] = model.NewBoolVar(f"active_{node.id}")
                else:
                    raise RepairError(f"节点 {node.id} 没有备选，无法自动修复")
        if node.id in invalid:
            model.Add(active[node.id] == 0)
        if node.locked:
            model.Add(active[node.id] == 1)

        model.Add(end[node.id] == start[node.id] + node.duration).OnlyEnforceIf(active[node.id])
        model.Add(end[node.id] == 0).OnlyEnforceIf(active[node.id].Not())
        model.Add(start[node.id] == 0).OnlyEnforceIf(active[node.id].Not())

        changed[node.id] = model.NewBoolVar(f"changed_{node.id}")
        switched[node.id] = model.NewBoolVar(f"switched_{node.id}")
        touched[node.id] = model.NewBoolVar(f"touched_{node.id}")
        model.Add(changed[node.id] == 0).OnlyEnforceIf(active[node.id].Not())
        model.Add(start[node.id] == node.start).OnlyEnforceIf([changed[node.id].Not(), active[node.id]])
        model.Add(start[node.id] != node.start).OnlyEnforceIf([changed[node.id], active[node.id]])
        model.Add(active[node.id] == int(node.active)).OnlyEnforceIf(switched[node.id].Not())
        model.Add(active[node.id] != int(node.active)).OnlyEnforceIf(switched[node.id])
        model.AddMaxEquality(touched[node.id], [changed[node.id], switched[node.id]])

        delta = model.NewIntVar(-horizon, horizon, f"delta_{node.id}")
        shift[node.id] = model.NewIntVar(0, horizon, f"shift_{node.id}")
        model.Add(delta == start[node.id] - node.start)
        model.Add(shift[node.id] >= delta).OnlyEnforceIf(active[node.id])
        model.Add(shift[node.id] >= -delta).OnlyEnforceIf(active[node.id])
        model.Add(shift[node.id] == 0).OnlyEnforceIf(active[node.id].Not())

        late[node.id] = model.NewIntVar(0, 240, f"late_{node.id}")
        if node.window:
            model.Add(start[node.id] >= node.window.start).OnlyEnforceIf(active[node.id])
            if relax and not node.locked:
                model.Add(start[node.id] <= node.window.end + 180).OnlyEnforceIf(active[node.id])
                model.Add(late[node.id] >= start[node.id] - node.window.end).OnlyEnforceIf(active[node.id])
            else:
                model.Add(start[node.id] <= node.window.end).OnlyEnforceIf(active[node.id])
        if node.deadline is not None:
            if relax and not node.locked:
                model.Add(end[node.id] <= node.deadline + 180).OnlyEnforceIf(active[node.id])
                model.Add(late[node.id] >= end[node.id] - node.deadline).OnlyEnforceIf(active[node.id])
            else:
                model.Add(end[node.id] <= node.deadline).OnlyEnforceIf(active[node.id])

    for edge in plan.edges_of("precedes", "requires"):
        for a, b in ((edge.src, edge.dst),):
            model.Add(
                start[b] >= end[a] + plan.travel_between(a, b)
            ).OnlyEnforceIf([active[a], active[b]])

    for group, nodes in groups.items():
        model.AddExactlyOne([active[node.id] for node in nodes])

    notify: dict[str, object] = {}
    for member in plan.members:
        notify[member.id] = model.NewBoolVar(f"notify_{member.id}")
    for node in plan.nodes:
        for person in node.persons:
            model.Add(notify[person] >= touched[node.id])

    risk_keep: dict[str, object] = {}
    for node_id in risky:
        risk_keep[node_id] = model.NewBoolVar(f"risk_keep_{node_id}")
        model.Add(risk_keep[node_id] >= active[node_id])

    min_slack = model.NewIntVar(-300, 300, "min_slack")
    for node in plan.nodes:
        if node.window:
            model.Add(min_slack <= node.window.end - start[node.id]).OnlyEnforceIf(active[node.id])

    objective = (
        spec.w_change * sum(touched.values())
        + spec.w_notify * sum(notify.values())
        + spec.w_late * sum(late.values())
        + 5 * sum(shift.values())
        + spec.w_risk * sum(risk_keep.values())
        - spec.w_buffer * min_slack
    )
    model.Minimize(objective)
    return model, {
        "active": active,
        "start": start,
        "end": end,
        "touched": touched,
        "notify": notify,
        "min_slack": min_slack,
    }


def _extract(plan: Plan, spec, solver, variables, optimal: bool, elapsed_ms: float) -> RepairResult:
    starts: dict[str, int] = {}
    active: dict[str, bool] = {}
    for node in plan.nodes:
        is_active = solver.Value(variables["active"][node.id]) == 1
        active[node.id] = is_active
        starts[node.id] = solver.Value(variables["start"][node.id]) if is_active else node.start
    changes = _make_changes(plan, starts, active)
    locked_preserved = all(
        starts[node.id] == node.start and active[node.id] == node.active
        for node in plan.nodes
        if node.locked
    )
    return RepairResult(
        scheme=spec,
        status="OPTIMAL" if optimal else "FEASIBLE",
        starts=starts,
        active=active,
        changes=changes,
        changed_persons=_changed_persons(plan, changes),
        locked_preserved=locked_preserved,
        objective=float(solver.ObjectiveValue()),
        solve_ms=elapsed_ms,
    )


def _solve_greedy(plan: Plan, invalid: set[str], spec: SchemeSpec) -> RepairResult:
    started = time.perf_counter()
    starts: dict[str, int] = {}
    active: dict[str, bool] = {}
    _apply_original(plan, starts, active)

    for group, nodes in plan.alt_groups().items():
        selected = next((node for node in nodes if node.active and node.id not in invalid), None)
        if selected is None:
            candidates = [node for node in nodes if node.id not in invalid]
            if not candidates:
                raise RepairError(f"备选组 {group} 全部不可行")
            selected = sorted(candidates, key=lambda n: (n.outdoor, n.start))[0]
        for node in nodes:
            active[node.id] = node is selected

    for node in plan.nodes:
        if node.id in invalid and node.alt_group is None:
            if node.kind != "slot":
                raise RepairError(f"节点 {node.id} 没有备选，无法自动修复")
            active[node.id] = False

    order = plan.topo_order()
    finishes: dict[str, int] = {}
    for node_id in order:
        node = plan.node(node_id)
        if not active[node_id]:
            starts[node_id] = node.start
            finishes[node_id] = node.end
            continue
        earliest = node.start
        for pred_id in plan.predecessors(node_id):
            if active[pred_id]:
                earliest = max(earliest, finishes[pred_id] + plan.travel_between(pred_id, node_id))
        if node.window and earliest < node.window.start:
            earliest = node.window.start
        if node.locked and earliest != node.start:
            raise RepairError(f"锁定节点 {node.id} 无法在原时间执行")
        starts[node_id] = earliest
        finishes[node_id] = earliest + node.duration

    changes = _make_changes(plan, starts, active)
    return RepairResult(
        scheme=spec,
        status="GREEDY",
        starts=starts,
        active=active,
        changes=changes,
        changed_persons=_changed_persons(plan, changes),
        locked_preserved=all(
            starts[node.id] == node.start and active[node.id] == node.active
            for node in plan.nodes
            if node.locked
        ),
        solve_ms=(time.perf_counter() - started) * 1000,
    )


def _mark_duplicates(results: list[RepairResult]) -> None:
    seen: dict[tuple, RepairResult] = {}
    for result in results:
        signature = (
            tuple(sorted(result.starts.items())),
            tuple(sorted(result.active.items())),
        )
        if signature in seen:
            if result.status == "GREEDY":
                result.note = "贪心回退：与方案 A 相同（安装 OR-Tools 可得到最稳妥方案）"
            else:
                result.note = f"与方案 {seen[signature].scheme.key} 相同（当前约束下只有一种可行改法）"
        else:
            seen[signature] = result


def apply_repair(plan: Plan, result: RepairResult) -> Plan:
    return plan.copy_with(starts=result.starts, active=result.active)


def render_results(plan: Plan, results: list[RepairResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"方案 {result.scheme.key} · {result.scheme.name} —— {result.scheme.tagline}")
        lines.append(
            f"  {result.summary()}｜{result.status}｜{result.solve_ms:.0f} ms"
        )
        for change in result.changes:
            lines.append(f"  - {change.describe()}")
        if result.note:
            lines.append(f"  * {result.note}")
        lines.append("")
    return "\n".join(lines).rstrip()
