"""位置打卡 → 晚到影响 → 可执行方案。

这里不引入持续定位：位置只负责让用户点「到了」，真正的判断和方案仍然
由确定性规则完成。AI 只在外部负责解释，不参与改计划。
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from .models import Node, Plan
from .propagate import Event, propagate
from .repair import Action, RepairResult, apply_actions


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
    working = apply_actions(plan, [action.to_dict() for action in actions]) if actions else plan.clone()
    return RepairResult(
        status="ok",
        scheme=key,
        label=label,
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
    shifted = can_shift and windows_ok
    if shifted:
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

    # B. 如果整体顺延不安全，退而求其次：跳过当前。锁定节点不能这样被跳过。
    if not shifted and not target.confirmed:
        drop = Action(
            node_id=target.id,
            action="drop",
            reason=f"跳过「{target.title}」",
            cost=0,
            payload={},
            sacrifice=f"放弃{target.title}",
        )
        schemes.append(_result("B", "跳过当前", [drop], plan, started))

    order = {"B": 0, "A": 1} if person_id else {"A": 0, "B": 1}
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

# ── 定位驱动的自动判断 ────────────────────────────────
def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(h))


def _node_point(node: Node) -> tuple[float, float] | None:
    poi = getattr(node, "poi", None) or {}
    lat, lng = poi.get("lat"), poi.get("lng")
    if lat and lng:
        return float(lat), float(lng)
    return None


NEAR_RADIUS_M = 1500        # 超过这个距离就认为不在任何计划点附近
LATE_TOLERANCE_MIN = 10     # 落后 10 分钟以内不算晚


def _active_day(plan: Plan, today: str | None) -> str:
    """定位判断只比较当天节点，避免第 1 天 12:10 拿去和第 4 天 11:51 比。"""
    day = today or date.today().isoformat()
    start = plan.date
    end = plan.end_date or plan.date
    if start and end and start <= day <= end:
        return day
    return start or day


def locate(
    plan: Plan,
    lat: float,
    lng: float,
    now_minutes: int,
    today: str | None = None,
) -> dict[str, Any]:
    """根据当前位置和当前时间，判断你落后了吗，落后就给出改法。

    场景：17:00 本该到下一个点，但你还在上一个点。
      · 找离你最近的计划节点（要 1.5 公里内）
      · 找此刻本该在的节点（第一个 start >= now 的）
      · 如果你人还停在前面的节点，落后 = now - 本该到的节点的 start
      · 落后超过 10 分钟，直接复用 checkin 的方案生成逻辑

    不做持续定位、不上传轨迹：只在用户主动点一下时算一次。
    """
    day = _active_day(plan, today)
    day_nodes = [
        node
        for node in plan.nodes
        if not node.dropped and (not node.date or node.date == day)
    ]
    if not day_nodes:
        day_nodes = [node for node in plan.nodes if not node.dropped]

    located = [
        (node, _node_point(node))
        for node in day_nodes
        if not node.dropped and _node_point(node) is not None
    ]
    if not located:
        return {
            "status": "no_location_data",
            "message": "这份行程没有地点坐标，无法用定位判断（内置示范计划没有坐标）",
            "driftMinutes": 0,
            "schemes": [],
        }

    node, point = min(
        located, key=lambda item: _distance_m(lat, lng, item[1][0], item[1][1])
    )
    distance = int(_distance_m(lat, lng, point[0], point[1]))
    if distance > NEAR_RADIUS_M:
        return {
            "status": "unknown",
            "message": f"你离最近的计划点「{node.title}」还有 {distance} 米，先不判断" ,
            "atNodeId": node.id,
            "atNodeTitle": node.title,
            "atDistanceM": distance,
            "driftMinutes": 0,
            "schemes": [],
        }

    # “此刻本该在”哪个点：计划里 start 已经过了的最后一个节点
    passed = sorted(
        (n for n in day_nodes if n.start <= now_minutes),
        key=lambda n: n.start,
    )
    should = passed[-1] if passed else node

    # 人还在更早的点上 → 落后 = 现在 - 本该到的那个点的开始时间
    drift = 0
    if should.id != node.id:
        drift = max(0, now_minutes - should.start)

    base = {
        "atNodeId": node.id,
        "atNodeTitle": node.title,
        "atDistanceM": distance,
        # 就在当前目标点旁边 → 可以直接提示“到了，打卡吗？”
        "arrived": distance <= 250 and node.id == should.id,
        "shouldNodeId": should.id,
        "shouldNodeTitle": should.title,
        "shouldStart": should.start,
        "nowMinutes": now_minutes,
        "driftMinutes": drift,
    }

    if drift < LATE_TOLERANCE_MIN:
        return {
            **base,
            "status": "on_track",
            "message": f"按计划走：现在应该在「{should.title}」",
            "schemes": [],
        }

    result = checkin(plan, should.id, drift, None)
    return {
        **base,
        "status": "behind",
        "message": f"你还在「{node.title}」，计划 {should.start // 60:02d}:{should.start % 60:02d} 就该到「{should.title}」，已落后 {drift} 分钟",
        "impact": result.get("impact"),
        "schemes": result.get("schemes", []),
        "blockedNode": result.get("blockedNode"),
    }
