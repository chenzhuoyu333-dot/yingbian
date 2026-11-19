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
from datetime import date as Date, timedelta
from pathlib import Path

from .env import key
from .models import Plan, format_time, parse_time
from .poi import (
    DEFAULT_INTERESTS,
    Poi,
    choose_route,
    find_by_name,
    route_plan,
    search_interests,
    travel_minutes,
)
from .propagate import Event, propagate

PACE_FACTOR = {"relaxed": 1.3, "normal": 1.0, "packed": 0.75}
MAX_NODES = 14
MEETING_MINUTES = 20  # 集合点默认占用的时间

# 同类地点一天最多几个：不然"咖啡 + 博物馆"会排出四家咖啡馆
MAX_PER_CATEGORY = {
    "cafe": 2,
    "food": 2,
    "shop": 1,
    "other": 1,
    "indoor_sight": 3,
    "sight": 4,
}

# 更粗的分组：cafe 和 food 都算"吃喝"，合起来限 3 个。
# 只按 category 限会被绕过 —— 一家咖啡店如果 type 缺"咖啡"字样就会被归成 food。
MAX_PER_GROUP = {"eat": 3, "shop": 1, "sight": 4}


def _group(category: str) -> str:
    if category in ("cafe", "food"):
        return "eat"
    if category in ("shop", "other"):
        return "shop"
    return "sight"


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
    # 行程天数：1 = 当天往返，>1 会按天切开并补住宿节点
    days: int = 1
    # "不想多走路"：不做长距离步行，公交挑步行最少的方案
    avoid_walking: bool = False
    # 由 AI 从"人均 100 以内""想去评价好的"这类话里解析出来
    budget_per_person: int = 0      # 0 表示不限
    prefer_high_rating: bool = False
    # 住宿：用户指定的酒店名或区域；空表示待定
    lodging: str = ""


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


def _score_poi(
    poi: Poi,
    transit: int,
    prefs: Preferences,
    plan: list[tuple[Poi, int, int, int]],
) -> tuple[float, list[str], bool]:
    """
    把"AI 解析出的偏好"和"高德给的真实字段"合成一个分数。

    返回 (分数, 选择理由, 是否允许)。分数越低越优先。
    这是"AI 条件 × 高德数据"真正结合的地方：
      · 通勤时间来自坐标（高德）
      · 评分/人均来自 biz_ext（高德）
      · 预算/节奏/避雷来自 AI 解析（ai.py）
    """
    reasons: list[str] = []
    score = float(transit)
    if transit <= 15:
        reasons.append(f"顺路（{transit} 分钟）")

    last_category = plan[-1][0].category if plan else None
    same_kind = sum(1 for p, _, _, _ in plan if p.category == poi.category)

    # 同类数量上限：一天不该去四家咖啡馆
    cap = MAX_PER_CATEGORY.get(poi.category, 2)
    if same_kind >= cap:
        return score, [f"同类已经排了 {same_kind} 个"], False

    # 大类上限：cafe 与 food 合起来限 3 个，堵住"分类不同但都是喝咖啡"的漏洞
    group = _group(poi.category)
    same_group = sum(1 for p, _, _, _ in plan if _group(p.category) == group)
    if same_group >= MAX_PER_GROUP[group]:
        return score, [f"{group} 类已经排了 {same_group} 个"], False

    score += same_kind * 12
    if poi.category == last_category:
        score += 60   # 连续同类重罚

    # 评分：高有加分（满分 5），没有评分数据不加不减
    if poi.rating > 0:
        score -= (poi.rating - 3.5) * 8
        if poi.rating >= 4.3:
            reasons.append(f"评分 {poi.rating}")

    # 人均：超预算直接判死；在预算内且便宜有小加分
    if prefs.budget_per_person > 0 and poi.cost > 0:
        if poi.cost > prefs.budget_per_person:
            return score + 1000, [f"人均 ¥{poi.cost:.0f} 超出预算 ¥{prefs.budget_per_person}"], False
        score -= 6
        reasons.append(f"人均 ¥{poi.cost:.0f}")

    # 商场店铺/未分类点：排在真景点和吃喝之后（不是不要，是最后才考虑）
    if poi.category in ("shop", "other"):
        score += 80

    # 明确要"评价好的"时，没有评分数据的点要降权
    if prefs.prefer_high_rating and poi.rating <= 0:
        score += 25

    # 有招牌菜的店更容易被选中（说明数据完整、也确实是个有内容的点）
    if poi.tags:
        reasons.append("招牌：" + "、".join(poi.tags[:3]))

    return score, reasons, True


def _ordered_pick(
    origin: Poi,
    pool: list[Poi],
    prefs: Preferences,
) -> list[tuple[Poi, int, int, int]]:
    """
    贪心最近邻 + 时间窗 + 硬约束（通勤上限 / 营业时间 / 预算 / 同类数量）。

    返回 [(poi, 到达分钟, 离开分钟, 通勤分钟), ...]
    """
    factor = PACE_FACTOR.get(prefs.pace, 1.0)
    remain = list(pool)
    current = origin
    clock = parse_time(prefs.start_time)
    end_limit = parse_time(prefs.end_time)
    plan: list[tuple[Poi, int, int, int]] = []

    while remain and len(plan) < MAX_NODES - 1:
        best = None
        best_transit = None
        best_score = None

        for poi in remain:
            transit = travel_minutes(current, poi)
            if transit > prefs.max_transit_min:
                continue
            stay = max(20, int(poi.stay_min * factor))
            arrive = clock + transit
            leave = arrive + stay
            if leave > end_limit:
                continue

            # 营业时间硬约束：到店时还没开门、或逛到打烊之后，都不排
            window = poi.open_window()
            if window is not None:
                open_min, close_min = window
                if arrive < open_min or leave > close_min:
                    continue

            score, _reasons, allowed = _score_poi(poi, transit, prefs, plan)
            if not allowed:
                continue
            if best_score is None or score < best_score:
                best, best_transit, best_score = poi, transit, score

        if best is None:
            break

        stay = max(20, int(best.stay_min * factor))
        arrive = clock + best_transit
        leave = arrive + stay
        plan.append((best, arrive, leave, best_transit))
        remain.remove(best)
        current = best
        clock = leave

    return plan


def _node_from_poi(
    poi: Poi,
    arrive: int,
    leave: int,
    transit: int,
    index: int,
    locked: bool,
    prefs: Preferences,
) -> dict:
    # 最晚开始时间 = 打烊时间 - 停留时长。
    # 直接拿打烊时间当 windowLatest 是错的：那只保证"能进门"，
    # 减掉停留时长才等于"能玩完"。这样约束引擎判的是同一件事。
    window = poi.open_window()
    stay_minutes = max(1, leave - arrive)
    window_latest = format_time(window[1] - stay_minutes) if window else None

    detail = {
        "name": poi.name,
        "category": poi.category,
        "address": poi.address,
        # 坐标要留着：天气按"这份行程在哪"来查，而不是查一个写死的默认城市
        "lng": round(poi.lng, 6),
        "lat": round(poi.lat, 6),
        "rating": poi.rating or None,
        "cost": poi.cost or None,
        "openTime": poi.open_time or None,
        "tel": poi.tel or None,
        "tags": poi.tags,
        # 数据来自哪里必须写清楚，缺什么也要说
        "missing": [
            label
            for label, value in (
                ("评分", poi.rating),
                ("人均", poi.cost),
                ("营业时间", poi.open_time),
            )
            if not value
        ],
    }

    return {
        "id": f"n_{index}",
        "type": "reservation" if poi.category == "food" else "place",
        "title": poi.name,
        "start": format_time(arrive),
        "end": format_time(leave),
        "indoor": poi.indoor,
        "confirmed": locked,
        "windowLatest": window_latest,
        "alternatives": [],
        "source": {
            "kind": "api",
            "note": f"高德 POI · {poi.type_text or poi.category}",
            "at": prefs.date,
        },
        # 置信度按高德实际给出的字段数量决定，不再一律 low
        "confidence": poi.data_quality(),
        # 高德原始字段 + 缺失项，前端可以直接显示"评分 4.4 · 人均 ¥39 · 07:30-22:00"
        "poi": detail,
        "reason": "；".join(
            _score_poi(poi, transit, prefs, [])[1]
        ) or "按偏好排序入选",
        "place": poi.name,
    }


def _temporal_violations(plan: Plan) -> list[str]:
    """
    真正的时间校验：不依赖任何事件，直接看计划自身的时间关系。

    为什么不能只靠 propagate 自检：
      传播的语义是"上游被顶 → 下游后移"，needed = max(0, shifts[src] - slack)。
      没有事件时 shifts 全是 0，于是 needed 恒为 0 —— 一份节点互相重叠的计划
      也会被判定为"没问题"。生成阶段必须自己查时间，这是生成器的职责。
    """
    problems: list[str] = []

    # ① 节点自身：时长必须为正，且不能晚于最晚开始时间
    for node in plan.nodes:
        if getattr(node, "dropped", False):
            continue
        if node.end <= node.start:
            problems.append(
                f"{node.id}「{node.title}」时长不合法："
                f"{format_time(node.start)}–{format_time(node.end)}"
            )
        if node.window_latest is not None and node.start > node.window_latest:
            problems.append(
                f"{node.id}「{node.title}」开始于 {format_time(node.start)}，"
                f"晚于最晚 {format_time(node.window_latest)}"
            )

    # ② 相邻两站：实际间隔必须 ≥ minGap（间隔为负就是重叠）
    for edge in plan.edges_of("precedes", "requires"):
        src = plan.find(edge.src)
        dst = plan.find(edge.dst)
        if src is None or dst is None:
            continue
        if getattr(src, "dropped", False) or getattr(dst, "dropped", False):
            continue
        gap = dst.start - src.end
        if gap < edge.min_gap:
            kind = "时间重叠" if gap < 0 else "间隔不足"
            problems.append(
                f"{edge.src}→{edge.dst} {kind}：实际 {gap} 分，要求 ≥ {edge.min_gap} 分"
            )

    return problems


def _feasibility_check(plan: Plan) -> list[str]:
    """
    生成阶段的自检 = 时间校验 + 引擎复核。

    · 时间校验：由 _temporal_violations 负责，能发现重叠、间隔不足、时长为负
    · 引擎复核：确认引擎没有把任何节点判成 at_risk/invalid/conflict
    两者都必要：前者补上了引擎在没有事件时查不出来的问题。
    """
    problems = _temporal_violations(plan)

    dummy = Event.from_dict({"type": "rain", "from": "00:00", "to": "00:01", "prob": 0.0})
    report = propagate(plan, dummy)
    for node_id, state in report.states.items():
        if state != "ok":
            problems.append(f"{node_id} 被约束引擎判为 {state}")

    return problems


def _parse_trip_start(value: str) -> Date:
    try:
        return Date.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("日期格式应为 YYYY-MM-DD，例如 2026-11-19") from exc


def _date_range(start: Date, days: int) -> list[str]:
    return [(start + timedelta(days=offset)).isoformat() for offset in range(days)]


def _brand(name: str) -> str:
    """去掉括号里的分店名，用来做连锁去重。
    "星巴克(杭州来福士店)" 和 "星巴克(市民中心店)" 视为同一个品牌。
    """
    base = name.split("(")[0].split("（")[0].strip()
    return base or name


def _quality_filter(candidates: list[Poi], interests: list[str]) -> list[Poi]:
    """
    候选点质量过滤。按"宁可少而准"的原则：

      · 同一品牌只保留评分最高的那家（避免一天排 4 家星巴克）
      · 有评分且低于 4.0 的吃喝类直接剔除（评分是最便宜的噪声信号）
      · 购物/其他类（商场里的店、被误判的小铺）降到最后，
        只有在别的类不够时才用
    """
    kept: list[Poi] = []
    seen_brand: dict[str, Poi] = {}

    for poi in candidates:
        rating = poi.rating or 0.0
        # 低分吃喝不要
        if poi.category in ("cafe", "food") and 0 < rating < 4.0:
            continue
        # 任何类别里评分特别低的也不要（但没评分的留着，小城市常常没数据）
        if 0 < rating < 3.6:
            continue

        if poi.category in ("cafe", "food", "shop"):
            brand = _brand(poi.name)
            prev = seen_brand.get(brand)
            if prev is not None:
                # 同品牌：留评分高的；评分相同留人均低的
                better = (rating, -(poi.cost or 0)) > (prev.rating or 0.0, -(prev.cost or 0))
                if not better:
                    continue
                kept = [p for p in kept if p.name != prev.name]
            seen_brand[brand] = poi

        kept.append(poi)

    # 购物/其他类（含商场里的店铺）垫底：
    # 真景点和吃喝足够时直接不要它们，不够时才作为补充
    sightish = [p for p in kept if p.category not in ("shop", "other")]
    others = [p for p in kept if p.category in ("shop", "other")]
    if len(sightish) >= 6:
        return sightish
    return sightish + others


def generate(prefs: Preferences) -> dict:
    """生成 plan dict（结构与本仓库 data/plan-*.json 完全一致）"""
    if not key("AMAP_KEY"):
        raise RuntimeError("未配置 AMAP_KEY，无法生成行程（见 .env.example）")

    # ① 候选池
    candidates = search_interests(prefs.city, prefs.interests)
    candidates = [p for p in candidates if not _blocked(p, prefs.avoid)]
    candidates = _quality_filter(candidates, list(prefs.interests))

    # ② 必去点：搜不到或被排除词挡掉，都要留下痕迹，不能当没发生
    must_pois: list[Poi] = []
    unresolved: list[str] = []
    for name in prefs.must_visit:
        found = find_by_name(prefs.city, name)
        if found is None:
            unresolved.append(name)
            continue
        if _blocked(found, prefs.avoid):
            unresolved.append(name)
            continue
        must_pois.append(found)

    if not must_pois and not candidates:
        raise RuntimeError(f"在「{prefs.city}」没搜到符合偏好的地点，换个兴趣词试试")

    origin = _pick_origin(prefs, must_pois + candidates)
    warnings: list[str] = []

    # ③ 住宿：用户给了酒店/区域就把它当地理锚点，第二天从酒店出发，
    #    晚上回酒店，酒店通勤按真实路径算。没给就还是过夜占位，不编时间。
    lodging_poi: Poi | None = None
    if prefs.lodging.strip() and int(prefs.days or 1) > 1:
        lodging_poi = find_by_name(prefs.city, prefs.lodging.strip())
        if lodging_poi is None:
            warnings.append(
                f"住宿「{prefs.lodging.strip()}」没搜到，已按待定处理；"
                "可以换成具体酒店名或附近的地标"
            )
    if int(prefs.days or 1) > 1 and lodging_poi is None and not prefs.lodging.strip():
        warnings.append(
            "住宿未指定：只放了过夜占位，入住时间和酒店通勤未计入行程；"
            "在新建行程里填「住哪儿」可以按酒店排"
        )

    # 未解析的必去点必须显式告知：用户说了"必去"，结果没排进去，
    # 静默丢掉会让用户以为计划里已经有它了。
    for name in unresolved:
        warnings.append(f"必去点「{name}」没搜到（或与排除条件冲突），已标记为待确认，请手动确认是否需要加回")

    # 集合点占 start_time ~ start_time+20，排序必须从它结束之后开始算
    meeting_min = parse_time(prefs.start_time)
    pick_prefs = Preferences(
        **{**prefs.__dict__, "start_time": format_time(meeting_min + MEETING_MINUTES)}
    )

    # ③ 按天排：每天独立一条链，用完的点不再重复排
    days = max(1, min(7, int(prefs.days or 1)))
    start_date = _parse_trip_start(prefs.date)
    dates = _date_range(start_date, days)
    meeting_min = parse_time(prefs.start_time)
    day_start = meeting_min + MEETING_MINUTES
    day_end = parse_time(prefs.end_time)

    pool = list(candidates)
    for poi in must_pois:
        if poi in pool:
            pool.remove(poi)

    locked_names = {p.name for p in must_pois}
    nodes: list[dict] = []
    edges: list[dict] = []
    used_names: set[str] = set()
    current = origin
    meet_title = origin.name or f"{prefs.city}集合"

    for day in range(1, days + 1):
        day_date = dates[day - 1]
        day_prefs = Preferences(
            **{
                **prefs.__dict__,
                "date": day_date,
                "start_time": format_time(day_start),
                "end_time": format_time(day_end),
            }
        )

        # 第 2 天起从昨晚的酒店出发；没填酒店就沿用上一站
        day_origin = current if day == 1 else (lodging_poi or current)

        picks: list[tuple[Poi, int, int, int]] = []
        if day == 1 and must_pois:
            # 必去点不受通勤上限限制，只受当天时间窗约束
            must_prefs = Preferences(**{**day_prefs.__dict__, "max_transit_min": 24 * 60})
            must_ordered = _ordered_pick(day_origin, must_pois, must_prefs)
            picks.extend(must_ordered)

        rest = [p for p in pool if p.name not in used_names and p.name not in locked_names]
        picks.extend(_ordered_pick(day_origin, rest, day_prefs))

        if day > 1:
            current = day_origin

        if not picks:
            break   # 后面的天排不出东西了，就到此为止

        # 用高德路径规划校准当天时间：调度原来按直线估算排，
        # 这里把每段真实/回退后的通勤时间代入，避免“计划里写 20 分钟、地图要 35 分钟”。
        day_stops: list[tuple[Poi, int, int, dict]] = []
        clock = day_start
        prev_poi = day_origin
        placed_must: set[str] = set()
        for poi, old_arrive, old_leave, _old_transit in picks:
            route = choose_route(prev_poi, poi, prefs.city, avoid_walking=prefs.avoid_walking)
            stay = max(20, old_leave - old_arrive)
            arrive = clock + int(route.get("durationMin") or travel_minutes(prev_poi, poi))

            window = poi.open_window()
            if window is not None:
                open_min, close_min = window
                arrive = max(arrive, open_min)
                if arrive + stay > close_min:
                    continue
            if arrive + stay > day_end:
                break

            day_stops.append((poi, arrive, arrive + stay, route))
            clock = arrive + stay
            prev_poi = poi
            if poi.name in locked_names:
                placed_must.add(poi.name)

        if not day_stops:
            break

        if day == 1:
            for poi in must_pois:
                if poi.name not in placed_must:
                    warnings.append(f"必去点「{poi.name}」来不及排进行程，已跳过")

        # 每天一个集合/出发节点
        meet_id = f"d{day}_meet"
        if day == 1:
            meet_label = meet_title
            meet_place = origin.name
            meet_note = "生成器设定的集合点"
        elif lodging_poi is not None:
            meet_label = f"{lodging_poi.name}出发（第 {day} 天）"
            meet_place = lodging_poi.name
            meet_note = "从昨晚的住宿出发"
        else:
            meet_label = f"{prefs.city}出发（第 {day} 天）"
            meet_place = ""
            meet_note = "住宿待定，沿用上一站作为出发点"
        nodes.append(
            {
                "id": meet_id,
                "type": "place",
                "title": meet_label,
                "start": format_time(meeting_min),
                "end": format_time(day_start),
                "indoor": True,
                "confirmed": True,
                "windowLatest": None,
                "alternatives": [],
                "source": {"kind": "manual", "note": meet_note, "at": day_date},
                "confidence": "medium",
                "place": meet_place,
                "date": day_date,
            }
        )

        prev_poi = current
        prev_id = meet_id
        for i, (poi, arrive, leave, route) in enumerate(day_stops, start=1):
            node = _node_from_poi(
                poi,
                arrive,
                leave,
                int(route.get("durationMin") or travel_minutes(prev_poi, poi)),
                i,
                poi.name in locked_names,
                day_prefs,
            )
            node["id"] = f"d{day}_n{i}"
            node["date"] = day_date
            nodes.append(node)
            edges.append(
                {
                    "from": prev_id,
                    "to": node["id"],
                    "type": "precedes",
                    "minGapMin": int(route.get("durationMin") or travel_minutes(prev_poi, poi)),
                    "transport": route,
                }
            )
            prev_poi, prev_id = poi, node["id"]
            used_names.add(poi.name)

        # 除最后一天外，补一个住宿节点（第二天从酒店出发）
        if day < days:
            last_leave = day_stops[-1][2]
            hotel_id = f"d{day}_hotel"

            if lodging_poi is not None:
                # 住哪儿是确定的：到店时间 = 最后一站离开 + 真实路径时长
                hotel_route = choose_route(
                    prev_poi,
                    lodging_poi,
                    prefs.city,
                    avoid_walking=prefs.avoid_walking,
                )
                hotel_start = last_leave + int(hotel_route.get("durationMin") or 0)
                hotel_end = 23 * 60 + 59
                if hotel_start >= hotel_end:
                    hotel_start = hotel_end - 1
                hotel_title = f"{lodging_poi.name} · 住宿（第 {day} 晚）"
                hotel_place = lodging_poi.name
                hotel_note = "用户指定的住宿，已作为第二天的出发点"
                hotel_confidence = lodging_poi.data_quality()
                hotel_poi_info = {
                    "name": lodging_poi.name,
                    "address": lodging_poi.address,
                    "rating": lodging_poi.rating or None,
                    "cost": lodging_poi.cost or None,
                }
            else:
                # 没指定住宿：只放一个过夜占位，绝不编入住时长和酒店通勤
                hotel_start = last_leave
                hotel_end = min(hotel_start + 1, 23 * 60 + 59)
                hotel_route = {
                    "mode": "placeholder",
                    "label": "住宿待定",
                    "distanceM": 0,
                    "durationMin": 0,
                    "source": "placeholder",
                    "text": "酒店待定，通勤时间未估算",
                }
                hotel_title = f"{prefs.city}住宿 · 过夜（第 {day} 晚，酒店待定）"
                hotel_place = ""
                hotel_note = "多日行程自动补的过夜占位"
                hotel_confidence = "low"
                hotel_poi_info = None

            nodes.append(
                {
                    "id": hotel_id,
                    "type": "place",
                    "title": hotel_title,
                    "start": format_time(hotel_start),
                    "end": format_time(hotel_end),
                    "indoor": True,
                    "confirmed": False,
                    "windowLatest": None,
                    "alternatives": [],
                    "source": {"kind": "manual", "note": hotel_note, "at": day_date},
                    "confidence": hotel_confidence,
                    "place": hotel_place,
                    "date": day_date,
                    "overnight": True,
                    "poi": hotel_poi_info,
                }
            )
            edges.append(
                {
                    "from": prev_id,
                    "to": hotel_id,
                    "type": "precedes",
                    "minGapMin": int(hotel_route.get("durationMin") or 0),
                    "transport": hotel_route,
                }
            )
            current = lodging_poi or prev_poi

    if len(nodes) < 3:
        raise RuntimeError("只排得出不到 3 个点，可能是时间太短或 max_transit_min 太小")

    actual_dates = sorted({str(node.get("date") or prefs.date) for node in nodes})
    actual_days = len(actual_dates) or 1
    end_date = actual_dates[-1] if actual_dates else prefs.date
    transport_amap = sum(
        1 for edge in edges if (edge.get("transport") or {}).get("source") == "amap"
    )
    transport_estimate = sum(
        1 for edge in edges if (edge.get("transport") or {}).get("source") == "estimate"
    )

    plan = {
        "planId": "p_generated",
        "title": (
            f"{prefs.date} {prefs.city}一日行程（据偏好生成）"
            if actual_days == 1
            else f"{prefs.date}—{end_date} {prefs.city} {actual_days} 日行程（据偏好生成）"
        ),
        "date": prefs.date,
        "endDate": end_date,
        "days": actual_days,
        "nodes": nodes,
        "edges": edges,
        # 生成器自己的说明：界面可以直接展示，评委也能看到这版怎么来的、哪里不确定
        "generation": {
            "city": prefs.city,
            "interests": list(prefs.interests),
            "mustVisit": list(prefs.must_visit),
            # 用户点名但没排进去的必去点，界面上要标"待确认"
            "unresolvedMustVisit": list(unresolved),
            "pace": prefs.pace,
            "days": actual_days,
            "startDate": prefs.date,
            "endDate": end_date,
            "dayDates": actual_dates,
            "maxTransitMin": prefs.max_transit_min,
            "avoidWalking": prefs.avoid_walking,
            "lodging": (
                {
                    "requested": prefs.lodging,
                    "resolved": lodging_poi is not None,
                    "name": lodging_poi.name if lodging_poi is not None else "",
                    "place": lodging_poi.address if lodging_poi is not None else "",
                }
                if prefs.lodging.strip()
                else None
            ),
            # 给界面用的一句话：让用户看到"AI 到底理解成什么"
            "humanSummary": " · ".join(
                part
                for part in (
                    f"{actual_days} 天" if actual_days > 1 else "当天往返",
                    f"{prefs.date} 起" if actual_days > 1 else prefs.date,
                    prefs.city,
                    ("想" + "、".join(prefs.interests)) if prefs.interests else "",
                    ("避开" + "、".join(prefs.avoid)) if prefs.avoid else "",
                    (f"人均 {prefs.budget_per_person} 以内" if prefs.budget_per_person else ""),
                    (f"住{lodging_poi.name}" if lodging_poi is not None else ""),
                    ("少走路" if prefs.avoid_walking else ""),
                )
                if part
            ),
            "warnings": warnings,
            "transportSources": {"amap": transport_amap, "estimate": transport_estimate},
            "note": "地点来自高德 POI 检索；交通方式按“公交优先 + 步行/骑行明显更快才换 + 少走路约束”选择，时长来自高德路径规划，接口不可用时才退回估算并用 transport.source 标注；停留时长仍是经验值，请用户确认",
        },
    }

    # ⑥ 自检：时间校验 + 引擎复核（两者都必要，见 _feasibility_check 注释）
    problems = _feasibility_check(Plan.from_dict(plan))
    if problems:
        trimmed = dict(plan)
        trimmed["nodes"] = plan["nodes"][:-2]
        # 多日行程里每天是独立的链，边数不等于节点数-1；
        # 必须按"两端节点都还在"筛边，不能按数量截断（否则会出现悬空边）
        _keep = {n["id"] for n in trimmed["nodes"]}
        trimmed["edges"] = [
            e for e in plan["edges"] if e["from"] in _keep and e["to"] in _keep
        ]
        if not _feasibility_check(Plan.from_dict(trimmed)):
            trimmed["generation"] = dict(plan["generation"])
            trimmed["generation"]["warnings"] = warnings + [
                f"排得太满，已自动砍掉最后 2 个点（原 {len(plan['nodes'])} 个节点）"
            ] + problems
            plan = trimmed
        else:
            # 砍点也救不回来：把具体哪条出了问题原样带出去，不要只说"有冲突"
            plan["generation"]["warnings"] = warnings + problems

    return plan


def save(plan: dict, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
