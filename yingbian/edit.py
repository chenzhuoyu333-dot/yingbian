"""在已生成的方案上继续加减节点。

产品意图：生成只是起点。用户看着行程说"这里我想加一站""这站不想去"，
系统就把这一改动接进依赖图、重算通勤与顺延，而不是让他回去改一句提示词重来。

设计上坚持两条：
  1. 时间不能凭感觉：新节点的到达时间 = 上一站结束 + 真实通勤（高德路径）；
     后面的点按差额整体顺延，和修复引擎的行为保持一致。
  2. 做不到就直说：晚于最晚进入时间、超出当天结束时间，都作为 warning 返回，
     不偷偷把点塞进去。
"""

from __future__ import annotations

from typing import Any

from .models import Edge, Node, Plan, format_time, parse_time
from .poi import Poi, find_by_name, route_plan


def _node_poi(node: Node) -> Poi | None:
    """把节点里存的 poi 字典还原成 Poi，用于算通勤。"""
    detail = node.poi or {}
    lat, lng = detail.get("lat"), detail.get("lng")
    if not lat or not lng:
        return None
    return Poi(
        id=str(node.id),
        name=node.title,
        category=str(detail.get("category") or "sight"),
        indoor=bool(node.indoor),
        lng=float(lng),
        lat=float(lat),
        stay_min=max(1, node.end - node.start),
    )


def _day_nodes(plan: Plan, date: str) -> list[Node]:
    same_day = [n for n in plan.nodes if not n.dropped and (n.date or plan.date) == date]
    return sorted(same_day, key=lambda n: (n.start, n.end))


def _shift_after(plan: Plan, date: str, from_start: int, delta: int) -> None:
    """把同一天里开始时间 >= from_start 的节点整体挪 delta 分钟。"""
    if delta == 0:
        return
    for node in plan.nodes:
        if node.dropped:
            continue
        if (node.date or plan.date) != date:
            continue
        if node.start >= from_start:
            node.start += delta
            node.end += delta


def _reconnect(plan: Plan, prev_id: str, next_id: str) -> None:
    """删掉 prev→next 之间的旧边。"""
    plan.edges = [
        edge for edge in plan.edges if not (edge.src == prev_id and edge.dst == next_id)
    ]


def add_node(
    plan: Plan,
    title: str,
    city: str,
    after_node_id: str | None = None,
    stay_min: int = 60,
) -> dict[str, Any]:
    """在某一站之后插入一个新节点，后面的点按差额顺延。

    返回 {plan, nodeId, warnings}
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("先说要加哪一站")

    poi = find_by_name(city, title)
    if poi is None:
        raise ValueError(f"在「{city}」没搜到「{title}」，换个说法或写全名试试")

    working = plan.clone()
    stay = max(15, min(300, int(stay_min or 60)))

    # 决定插在哪一天、哪一站之后
    if after_node_id:
        anchor = working.find(after_node_id)
        if anchor is None:
            raise ValueError("找不到要插入的位置")
        date = anchor.date or working.date
    else:
        # 默认插在最后一天最后一个非住宿点之后
        dated = [n for n in working.nodes if not n.dropped and not n.overnight]
        anchor = sorted(dated, key=lambda n: (n.date or working.date, n.start))[-1]
        date = anchor.date or working.date

    day = _day_nodes(working, date)
    if anchor not in day:
        day.append(anchor)
        day.sort(key=lambda n: n.start)

    index = day.index(anchor)
    nxt = day[index + 1] if index + 1 < len(day) else None

    prev_poi = _node_poi(anchor)
    transit = 0
    transit_estimated = False
    if prev_poi is not None:
        # 路径接口抖动不能让"加一站"整体失败：退化成估算并明确标注
        try:
            route = route_plan(prev_poi, poi, city)
            transit = int(route.get("durationMin") or 0)
            transit_estimated = str(route.get("source") or "") != "amap"
        except Exception:
            transit = _guess_minutes(prev_poi, poi)
            transit_estimated = True

    arrive = anchor.end + transit
    leave = arrive + stay

    warnings: list[str] = []
    window = poi.open_window()
    if window is not None:
        open_min, close_min = window
        if arrive < open_min:
            arrive = open_min
            leave = arrive + stay
        if leave > close_min:
            warnings.append(f"「{poi.name}」在 {format_time(close_min)} 关门，可能逛不完")

    if transit_estimated:
        warnings.append("通勤时间暂时是估算的（地图接口没返回），确认后再看一次会更准")

    new_id = f"n_add_{len(working.nodes) + 1}"
    while working.find(new_id) is not None:
        new_id += "x"

    from .generate import _node_from_poi, Preferences  # 延迟导入，避免循环引用

    detail = _node_from_poi(
        poi, arrive, leave, transit, len(working.nodes) + 1, False, Preferences(city=city)
    )
    detail["id"] = new_id
    detail["date"] = date
    detail["selectionReason"] = "用户添加"
    new_node = Node.from_dict(detail)

    # 后面的点顺延（只挪同一天、且在插入点之后的）
    delta = leave - (nxt.start if nxt is not None else leave)
    if nxt is not None:
        _shift_after(working, date, nxt.start, delta)

    working.nodes.append(new_node)

    # 连边：删旧边，接两条新边
    if nxt is not None:
        _reconnect(working, anchor.id, nxt.id)
        working.edges.append(
            Edge(
                src=new_id,
                dst=nxt.id,
                type="precedes",
                min_gap=transit,
                transport={"mode": "transit", "label": "公交" if transit else "估算", "durationMin": transit},
            )
        )
    working.edges.append(
        Edge(
            src=anchor.id,
            dst=new_id,
            type="precedes",
            min_gap=transit,
            transport={"mode": "transit", "label": "公交" if transit else "估算", "durationMin": transit},
        )
    )

    working.version = plan.version + 1
    return {"plan": working, "nodeId": new_id, "warnings": warnings}


def remove_node(plan: Plan, node_id: str) -> dict[str, Any]:
    """删掉一站，把它前后两站重新连起来并重算通勤。

    返回 {plan, removed, warnings}
    """
    working = plan.clone()
    target = working.find(node_id)
    if target is None:
        raise ValueError("找不到要删除的节点")
    if target.overnight:
        raise ValueError("住宿占位不能直接删，请先改住宿设置")

    date = target.date or working.date
    # 用"按时间排序后的相邻项"找前后，不能按 start/end 比较：
    # 加过站之后，前后两点的时间可能挨得很近（甚至相等），比较法会跳过一站。
    ordered = _day_nodes(working, date)
    position = next((i for i, n in enumerate(ordered) if n.id == node_id), None)
    if position is None:
        raise ValueError("找不到要删除的节点")
    prev = ordered[position - 1] if position > 0 else None
    nxt = ordered[position + 1] if position + 1 < len(ordered) else None

    warnings: list[str] = []
    transit = 0
    if prev is not None and nxt is not None:
        prev_poi, next_poi = _node_poi(prev), _node_poi(nxt)
        if prev_poi is not None and next_poi is not None:
            try:
                route = route_plan(prev_poi, next_poi, "")
                transit = int(route.get("durationMin") or 0)
            except Exception:
                transit = _guess_minutes(prev_poi, next_poi)
        want = prev.end + transit
        delta = want - nxt.start
        _shift_after(working, date, nxt.start, delta)
        if nxt.window_latest and nxt.start < (nxt.window_latest or 0):
            pass
    elif prev is not None and nxt is None:
        warnings.append("删掉的是当天最后一站，后面没有需要顺延的点")

    # 清掉与它相关的边，并把前后连起来
    working.edges = [
        edge
        for edge in working.edges
        if edge.src != node_id and edge.dst != node_id
    ]
    if prev is not None and nxt is not None:
        working.edges.append(
            Edge(
                src=prev.id,
                dst=nxt.id,
                type="precedes",
                min_gap=transit,
                transport={"mode": "transit", "label": "公交" if transit else "估算", "durationMin": transit},
            )
        )

    working.nodes = [n for n in working.nodes if n.id != node_id]
    working.version = plan.version + 1
    return {"plan": working, "removed": target.title, "warnings": warnings}
