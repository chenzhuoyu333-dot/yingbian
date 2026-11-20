"""主动巡检：不等用户开口，先发现"该改计划了"。

这是产品的核心创新点所在。
  别人的产品：用户发现出问题了 → 打开 App → 手动改
  我们：App 定时自己看一遍 → 发现要改 → 告诉用户 → 一键改

巡检查什么（全部基于确定性数据，不调模型）：
  1. 落后：你人还停在上一站，时间已经过了下一站的计划开始（需要有位置）
  2. 天气：行程所在地正在下雨，而且后面有点在户外
  3. 收口：下一站有最晚进入时间，快来不及了
  4. 空档：某段通勤预留时间小于真实通勤（会连锁迟到）

输出是"提醒清单"，每条都能带上"能怎么改"（复用 repair），
所以巡检本身就是可执行的，不是只弹个感叹号。
"""

from __future__ import annotations

from typing import Any

from .models import Node, Plan, format_time
from .weather import fetch_weather

RAIN_ALERT = 0.6          # 降雨概率超过这个就提醒
CLOSING_WARN_MIN = 40     # 离最晚进入时间不足这么多分钟就提醒
MIN_SLACK_MIN = 5         # 缓冲小于这个视为"没有缓冲"


def _alert(
    kind: str,
    title: str,
    detail: str,
    node_id: str | None = None,
    severity: str = "info",
    action: str = "",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "detail": detail,
        "nodeId": node_id,
        "severity": severity,      # info | warn | urgent
        "action": action,
    }


def _point(node: Node) -> tuple[float, float] | None:
    poi = getattr(node, "poi", None) or {}
    lat, lng = poi.get("lat"), poi.get("lng")
    if lat and lng:
        return float(lat), float(lng)
    return None


def _check_behind(plan: Plan, now: int, lat: float | None, lng: float | None) -> list[dict]:
    if lat is None or lng is None:
        return []
    from .location import locate

    result = locate(plan, lat, lng, now)
    if result.get("status") != "behind":
        return []
    drift = result.get("driftMinutes") or 0
    return [
        _alert(
            kind="behind",
            title=f"你可能赶不上了：落后 {drift} 分钟",
            detail=result.get("message", ""),
            node_id=result.get("shouldNodeId"),
            severity="urgent" if drift >= 30 else "warn",
            action="我有两套改法，点开看",
        )
    ]


def _check_weather(plan: Plan) -> list[dict]:
    located = [node for node in plan.nodes if not node.dropped and _point(node)]
    if not located:
        return []
    lat, lng = _point(located[0])  # type: ignore[misc]
    try:
        weather = fetch_weather(f"{lat:.6f}", f"{lng:.6f}")
    except Exception:
        return []

    chance = weather.get("rainChance") or 0
    try:
        chance = float(chance)
    except (TypeError, ValueError):
        return []
    if chance < RAIN_ALERT:
        return []

    outdoor = [node for node in located if not node.indoor and not node.confirmed]
    if not outdoor:
        return []

    names = "、".join(node.title for node in outdoor[:3])
    return [
        _alert(
            kind="weather",
            title=f"行程地点降雨概率 {round(chance * 100)}%",
            detail=f"「{names}」是户外点，可能受影响",
            node_id=outdoor[0].id,
            severity="warn",
            action="看看要不要换成室内方案",
        )
    ]


def _check_closing(plan: Plan, now: int) -> list[dict]:
    """来不及了：离最晚进入时间只剩 X 分钟，但逛完它要 Y 分钟。

    这比"还有 40 分钟到点"有用 —— 它回答的是"今天这个点还去得成吗"。
    """
    alerts: list[dict] = []
    candidates = sorted(
        (
            node
            for node in plan.nodes
            if not node.dropped and node.window_latest and node.end > now
        ),
        key=lambda node: node.window_latest or 0,
    )
    for node in candidates[:2]:
        latest = node.window_latest or 0
        remain = latest - now
        need = node.end - node.start
        if remain <= 0:
            continue
        if remain < need:
            alerts.append(
                _alert(
                    kind="closing",
                    title=f"「{node.title}」今天可能去不成了",
                    detail=(
                        f"最晚 {format_time(latest)} 进去，现在只剩 {remain} 分钟，"
                        f"而逛完要 {need} 分钟"
                    ),
                    node_id=node.id,
                    severity="urgent" if remain < need // 2 else "warn",
                    action="要不要去掉或换成附近别的地方",
                )
            )
    return alerts


def _check_tight(plan: Plan) -> list[dict]:
    """全程都没有缓冲才提醒。

    注意：单段 slack=0 是生成器的正常结果（时间刚好等于通勤），
    不能当作异常。只有**所有**相邻段都没有缓冲，才值得说一句
    "今天一处延误就会连锁"。
    """
    nodes = [node for node in plan.nodes if not node.dropped]
    if len(nodes) < 3:
        return []

    slacks: list[int] = []
    for index in range(len(nodes) - 1):
        current, nxt = nodes[index], nodes[index + 1]
        edge = next(
            (e for e in plan.edges if e.src == current.id and e.dst == nxt.id), None
        )
        if edge is None or edge.min_gap <= 0:
            continue
        slacks.append(nxt.start - current.end - edge.min_gap)

    if not slacks or any(slack >= MIN_SLACK_MIN for slack in slacks):
        return []

    return [
        _alert(
            kind="tight",
            title="今天全程没有缓冲",
            detail=f"{len(slacks)} 段通勤都是卡着点排的，任何一处延误都会连锁",
            node_id=nodes[0].id,
            severity="info",
            action="可以整体留一点余量",
        )
    ]


def patrol(
    plan: Plan,
    now_minutes: int,
    lat: float | None = None,
    lng: float | None = None,
) -> dict[str, Any]:
    """跑一遍巡检，返回"要不要打扰用户"以及为什么。"""
    alerts: list[dict] = []
    alerts.extend(_check_behind(plan, now_minutes, lat, lng))
    alerts.extend(_check_closing(plan, now_minutes))
    alerts.extend(_check_weather(plan))
    alerts.extend(_check_tight(plan))

    order = {"urgent": 0, "warn": 1, "info": 2}
    alerts.sort(key=lambda item: order.get(item["severity"], 9))

    top = alerts[0]["severity"] if alerts else "none"
    return {
        "needsAttention": bool(alerts),
        "severity": top,
        "alerts": alerts,
        "checkedAt": format_time(now_minutes),
        "summary": (
            alerts[0]["title"]
            if alerts
            else "一切正常，按计划走就行"
        ),
    }
