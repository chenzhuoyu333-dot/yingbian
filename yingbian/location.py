"""位置打卡 → 晚到影响 → 可执行方案。

这里不引入持续定位：位置只负责让用户点「到了」，真正的判断和方案仍然
由确定性规则完成。AI 只在外部负责解释，不参与改计划。
"""

from __future__ import annotations

import time
from typing import Any

from .models import Node, Plan
from .propagate import Event, propagate
from .repair import Action, RepairResult, apply_actions
from .rules import SCHEMES


MIN_STAY_MINUTES = 10


def _keep_rate(original: Plan, working: Plan) -> float:
    locked = [node for node in original.nodes if node.confirmed]
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


def _result(
    key: str,
    label: str,
    actions: list[Action],
    plan: Plan,
    started: float,
) -> RepairResult:
    scheme = SCHEMES[key]
    working = apply_actions(plan, [action.to_dict() for action in actions]) if actions else plan.clone()
    return RepairResult(
        status="ok",
        scheme=key,
        label=label or scheme.label,
        actions=actions,
        blocked_node=None,
        message="",
        keep_rate=_keep_rate(plan, working),
        changed_count=len(actions),
        plan=working,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def _target_node(plan: Plan, node_id: str | None, person_id: str | None) -> Node | None:
    if person_id:
        candidates = [node for node in plan.nodes if person_id in node.persons and not node.dropped]
        if candidates:
            return sorted(candidates, key=lambda node: node.start)[0]
    if node_id:
        return plan.find(node_id)
    return None


def _event_for(
    target: Node,
    minutes: int,
    person_id: str | None,
) -> tuple[Event, dict[str, Any]]:
    if person_id:
        return (
            Event(
                type="memberLate",
                node_id=target.id,
                person_id=person_id,
                minutes=minutes,
                label=f"{person_id} 晚到 {minutes} 分钟",
            ),
            {"type": "memberLate", "nodeId": target.id, "personId": person_id, "minutes": minutes,
             "label": f"{person_id} 晚到 {minutes} 分钟"},
        )
    return (
        Event(
            type="delay",
            node_id=target.id,
            minutes=minutes,
            label=f"在「{target.title}」晚到 {minutes} 分钟",
        ),
        {"type": "delay", "nodeId": target.id, "minutes": minutes,
         "label": f"在「{target.title}」晚到 {minutes} 分钟"},
    )


def _scheme_actions(
    plan: Plan,
    target: Node,
    minutes: int,
    person_id: str | None,
    started: float,
) -> list[RepairResult]:
    affected = [
        node
        for node in plan.nodes
        if not node.dropped and node.start >= target.start
    ]
    schemes: list[RepairResult] = []

    # A. 缩短当前停留：最保守，后续时间完全不动。
    if target.duration - minutes >= MIN_STAY_MINUTES:
        trim = Action(
            node_id=target.id,
            action="trim",
            reason=f"把「{target.title}」的停留缩短 {minutes} 分钟",
            cost=minutes,
            payload={"minutes": minutes},
            sacrifice=f"少待 {minutes} 分钟",
        )
        schemes.append(_result("A", "缩短当前停留", [trim], plan, started))

    # B. 整体顺延：只有后续全是未锁定项时才安全。锁定节点是用户明确确认过的，
    # 不能因为同行人晚到就悄悄挪走；需要挪的话应由用户先解锁。
    can_shift = all(not node.confirmed for node in affected)
    windows_ok = all(
        node.window_latest is None or node.start + minutes <= node.window_latest
        for node in affected
    )
    if can_shift and windows_ok:
        shifts = [
            Action(
                node_id=node.id,
                action="shift",
                reason=f"整体后移 {minutes} 分钟",
                cost=minutes,
                payload={"minutes": minutes},
                sacrifice="",
            )
            for node in affected
        ]
        schemes.append(_result("B", "整体顺延", shifts, plan, started))

    # C. 跳过当前：不拖延后面，但会放弃当前节点。锁定节点不能这样被跳过。
    if not target.confirmed:
        drop = Action(
            node_id=target.id,
            action="drop",
            reason=f"跳过「{target.title}」",
            cost=0,
            payload={},
            sacrifice=f"放弃{target.title}",
        )
        schemes.append(_result("C", "跳过当前", [drop], plan, started))

    order = {"B": 0, "A": 1, "C": 2} if person_id else {"A": 0, "B": 1, "C": 2}
    return sorted(schemes, key=lambda item: order.get(item.scheme, 9))


def checkin(
    plan: Plan,
    node_id: str | None,
    minutes: int,
    person_id: str | None = None,
) -> dict[str, Any]:
    """记录一次到达；晚到时返回影响和方案，准时只返回确认。"""
    started = time.perf_counter()
    target = _target_node(plan, node_id, person_id)
    if target is None:
        raise ValueError("找不到要打卡的节点")

    if minutes <= 0:
        return {
            "nodeId": target.id,
            "nodeTitle": target.title,
            "status": "on_time",
            "minutes": 0,
            "event": None,
            "impact": None,
            "schemes": [],
            "blockedNode": None,
            "message": f"已记录到达：{target.title}",
        }

    event, event_dict = _event_for(target, minutes, person_id)
    report = propagate(plan, event)
    schemes = _scheme_actions(plan, target, minutes, person_id, started)
    who = f"{person_id} 晚到" if person_id else "你比计划晚到"
    status = "member_late" if person_id else "late"
    message = f"{who} {minutes} 分钟，下面是可以选的处理方式。"
    if not schemes:
        message = f"{who} {minutes} 分钟，但没有安全的自动改法，需要你手动决定。"

    return {
        "nodeId": target.id,
        "nodeTitle": target.title,
        "status": status,
        "minutes": minutes,
        "event": event_dict,
        "impact": report.to_dict(),
        "schemes": [scheme.to_dict() for scheme in schemes],
        "blockedNode": None if schemes else target.id,
        "message": message,
    }
