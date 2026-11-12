"""行程生成器：把"偏好"变成一张可修复的计划图。

核心思路（这也是和"攻略转行程"类产品的根本差别）：

    生成 = 反过来的修复

    我们已有的引擎是"给一张图，算出哪里会崩"。
    生成的时候把它倒过来用：先按偏好排一版，再拿同一套约束检查它是否走得通，
    走不通就换点 / 截断行程。

所以生成出来的不是一篇攻略，而是一张**带依赖、时间窗、缓冲、锁定**的图 ——
它一诞生就知道自己哪里脆弱，后面抗变才有东西可修。

跑法：
    python -m yingbian generate --city 杭州 --interests 古镇,拍照,咖啡 --pace relaxed
    python -m yingbian generate --city 杭州 --must-visit 清河坊历史文化特色街区 --out data/plan-generated.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .env import key
from .models import Plan, format_time, parse_time
from .poi import (
    DEFAULT_INTERESTS,
    Poi,
    find_by_name,
    search_interests,
    travel_minutes,
)
from .propagate import Event, propagate

PACE_FACTOR = {"relaxed": 1.3, "normal": 1.0, "packed": 0.75}
MAX_NODES = 14
MEETING_MINUTES = 20  # 集合点默认占用的时间


@dataclass
class Preferences:
    city: str = "杭州"
    date: str = "2026-11-14"
    start_time: str = "09:30"
    end_time: str = "20:00"
    interests: list[str] = field(default_factory=lambda: list(DEFAULT_INTERESTS))
    must_visit: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    pace: str = "normal"
    max_transit_min: int = 45
    start_place: str = ""


def _blocked(poi: Poi, avoid: list[str]) -> bool:
    haystack = f"{poi.name} {poi.type_text}"
    return any(word and word in haystack for word in avoid)


def _pick_origin(prefs: Preferences, candidates: list[Poi]) -> Poi:
    """起点：优先按用户给的起点名检索，否则用候选池的地理中心造一个虚拟起点"""
    if prefs.start_place:
        found = find_by_name(prefs.city, prefs.start_place)
        if found:
            return found

    if candidates:
        lng = sum(p.lng for p in candidates) / len(candidates)
        lat = sum(p.lat for p in candidates) / len(candidates)
    else:
        lng, lat = 120.155, 30.253

    return Poi(
        id="poi_origin",
        name=prefs.start_place or f"{prefs.city}市中心",
        category="sight",
        indoor=True,
        lng=lng,
        lat=lat,
        stay_min=0,
        type_text="虚拟起点",
    )


def _ordered_pick(
    origin: Poi,
    pool: list[Poi],
    prefs: Preferences,
) -> list[tuple[Poi, int, int]]:
    """
    贪心最近邻 + 时间窗：每一步挑"最近且来得及"的点。

    返回 [(poi, 到达分钟, 离开分钟), ...]
    """
    factor = PACE_FACTOR.get(prefs.pace, 1.0)
    remain = list(pool)
    current = origin
    clock = parse_time(prefs.start_time)
    end_limit = parse_time(prefs.end_time)
    plan: list[tuple[Poi, int, int]] = []

    while remain and len(plan) < MAX_NODES - 1:
        best = None
        best_transit = None
        best_score = None
        last_category = plan[-1][0].category if plan else None

        for poi in remain:
            transit = travel_minutes(current, poi)
            if transit > prefs.max_transit_min:
                continue
            stay = max(20, int(poi.stay_min * factor))
            arrive = clock + transit
            leave = arrive + stay
            if leave > end_limit:
                continue
            # 优先近的；同类已选过要降权，连续同类要重罚
            # （否则会排成"博物馆→博物馆→咖啡馆→咖啡馆"）
            same_kind = sum(1 for p, _, _ in plan if p.category == poi.category)
            score = transit + same_kind * 12
            if poi.category == last_category:
                score += 60
            if best_score is None or score < best_score:
                best, best_transit, best_score = poi, transit, score

        if best is None:
            break

        stay = max(20, int(best.stay_min * factor))
        arrive = clock + best_transit
        leave = arrive + stay
        plan.append((best, arrive, leave))
        remain.remove(best)
        current = best
        clock = leave

    return plan


def _node_from_poi(
    poi: Poi,
    arrive: int,
    leave: int,
    index: int,
    locked: bool,
    prefs: Preferences,
) -> dict:
    return {
        "id": f"n_{index}",
        "type": "reservation" if poi.category == "food" else "place",
        "title": poi.name,
        "start": format_time(arrive),
        "end": format_time(leave),
        "indoor": poi.indoor,
        "confirmed": locked,
        "windowLatest": None,
        "alternatives": [],
        "source": {
            "kind": "api",
            "note": f"高德 POI 检索 · {poi.type_text or poi.category}",
            "at": prefs.date,
        },
        # 没有开放时间和门票数据，所以置信度只能是 low，让用户确认
        "confidence": "low",
        "place": poi.name,
    }


def _feasibility_check(plan: Plan) -> list[str]:
    """
    拿"不会命中任何节点"的事件跑一遍传播：
    如果计划本身就有节点非 ok，说明排得太满 —— 这是生成阶段的自检。
    """
    dummy = Event.from_dict({"type": "rain", "from": "00:00", "to": "00:01", "prob": 0.0})
    report = propagate(plan, dummy)
    return [nid for nid, state in report.states.items() if state != "ok"]


def generate(prefs: Preferences) -> dict:
    """生成 plan dict（结构与本仓库 data/plan-*.json 完全一致）"""
    if not key("AMAP_KEY"):
        raise RuntimeError("未配置 AMAP_KEY，无法生成行程（见 .env.example）")

    # ① 候选池
    candidates = search_interests(prefs.city, prefs.interests)
    candidates = [p for p in candidates if not _blocked(p, prefs.avoid)]

    # ② 必去点
    must_pois: list[Poi] = []
    for name in prefs.must_visit:
        found = find_by_name(prefs.city, name)
        if found and not _blocked(found, prefs.avoid):
            must_pois.append(found)

    if not must_pois and not candidates:
        raise RuntimeError(f"在「{prefs.city}」没搜到符合偏好的地点，换个兴趣词试试")

    origin = _pick_origin(prefs, must_pois + candidates)
    warnings: list[str] = []

    # 集合点占 start_time ~ start_time+20，排序必须从它结束之后开始算
    meeting_min = parse_time(prefs.start_time)
    pick_prefs = Preferences(
        **{**prefs.__dict__, "start_time": format_time(meeting_min + MEETING_MINUTES)}
    )

    # ③ 排序：必去优先，其余按最近邻
    ordered: list[tuple[Poi, int, int]] = []
    pool = list(candidates)
    for poi in must_pois:
        if poi in pool:
            pool.remove(poi)

    # 必去点不受 max_transit_min 限制（用户说"必去"就不能因为远而悄悄丢掉），
    # 只受结束时间约束；实在来不及就记警告，让调用方知道。
    if must_pois:
        must_prefs = Preferences(**{**pick_prefs.__dict__, "max_transit_min": 24 * 60})
        must_ordered = _ordered_pick(origin, must_pois, must_prefs)
        placed = {p.name for p, _, _ in must_ordered}
        for poi in must_pois:
            if poi.name not in placed:
                warnings.append(f"必去点「{poi.name}」来不及排进当天时间窗，已跳过")
        ordered.extend(must_ordered)

    last = ordered[-1][0] if ordered else origin
    clock_shift = ordered[-1][2] if ordered else meeting_min + MEETING_MINUTES
    rest_prefs = Preferences(**{**pick_prefs.__dict__, "start_time": format_time(clock_shift)})
    ordered.extend(_ordered_pick(last, pool, rest_prefs))

    # ④ 组装节点：起点 + 各站
    nodes: list[dict] = [
        {
            "id": "n_meet",
            "type": "place",
            "title": origin.name or f"{prefs.city}集合",
            "start": format_time(meeting_min),
            "end": format_time(meeting_min + MEETING_MINUTES),
            "indoor": True,
            "confirmed": True,
            "windowLatest": None,
            "alternatives": [],
            "source": {"kind": "manual", "note": "生成器自动设定的集合点", "at": prefs.date},
            "confidence": "medium",
            "place": origin.name,
        }
    ]

    locked_names = {p.name for p in must_pois}
    for i, (poi, arrive, leave) in enumerate(ordered, start=1):
        nodes.append(_node_from_poi(poi, arrive, leave, i, poi.name in locked_names, prefs))

    if len(nodes) < 3:
        raise RuntimeError("只排得出不到 3 个点，可能是时间太短或 max_transit_min 太小")

    # ⑤ 连边：minGap = 估算通勤时间
    edges = []
    for i in range(len(nodes) - 1):
        if i == 0:
            from_poi, to_poi = origin, ordered[0][0]
        else:
            from_poi, to_poi = ordered[i - 1][0], ordered[i][0]
        edges.append(
            {
                "from": nodes[i]["id"],
                "to": nodes[i + 1]["id"],
                "type": "precedes",
                "minGapMin": travel_minutes(from_poi, to_poi),
            }
        )

    plan = {
        "planId": "p_generated",
        "title": f"{prefs.date} {prefs.city}一日行程（据偏好生成）",
        "date": prefs.date,
        "nodes": nodes,
        "edges": edges,
        # 生成器自己的说明：界面可以直接展示，评委也能看到这版怎么来的、哪里不确定
        "generation": {
            "city": prefs.city,
            "interests": list(prefs.interests),
            "mustVisit": list(prefs.must_visit),
            "pace": prefs.pace,
            "maxTransitMin": prefs.max_transit_min,
            "warnings": warnings,
            "note": "地点来自高德 POI 检索；停留时长为经验值，通勤为直线距离估算，均标 confidence=low，请用户确认",
        },
    }

    # ⑥ 自检：把生成的图喂给同一套约束引擎
    problems = _feasibility_check(Plan.from_dict(plan))
    if problems:
        trimmed = dict(plan)
        trimmed["nodes"] = plan["nodes"][:-2]
        trimmed["edges"] = plan["edges"][: len(trimmed["nodes"]) - 1]
        if not _feasibility_check(Plan.from_dict(trimmed)):
            trimmed["generation"] = dict(plan["generation"])
            trimmed["generation"]["warnings"] = warnings + [
                f"排得太满，已自动砍掉最后 2 个点（原 {len(plan['nodes'])} 个节点）"
            ]
            plan = trimmed
        else:
            plan["generation"]["warnings"] = warnings + [
                "自检仍有冲突，建议缩短时间窗或降低 pace"
            ]

    return plan


def save(plan: dict, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
