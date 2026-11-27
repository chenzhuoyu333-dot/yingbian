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
import re
from dataclasses import dataclass, field
from datetime import date as Date, timedelta
from pathlib import Path

from .env import key
from .models import Plan, format_time, parse_time
from .poi import (
    DEFAULT_INTERESTS,
    MAX_PER_KEYWORD,
    Poi,
    choose_route,
    distance_m,
    find_by_name,
    route_plan,
    search_interests,
    search_keyword,
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

# 城市必看池：用户说"想去长沙玩四天"时，不该只排到小店和普通公园。
# 这两个关键词能拿到城市里真正的招牌景点，只用来标记优先级，
# 不改变用户偏好本身 —— 偏好负责加减，城市必看负责兜底。
CORE_SEARCH_WORDS = ["5A景区", "风景名胜"]
# 每天至少安排几个城市必看点；同时最多 3 个，避免一天全被大景点占满。
CORE_PER_DAY_MIN = 2
CORE_PER_DAY_MAX = 3


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
    max_transit_min: int = 60
    start_place: str = ""
    # 出发点坐标（用户在新建页"用当前定位"时传进来）
    start_lat: float = 0.0
    start_lng: float = 0.0
    # 行程天数：1 = 当天往返，>1 会按天切开并补住宿节点
    days: int = 1
    # "不想多走路"：不做长距离步行，公交挑步行最少的方案
    avoid_walking: bool = False
    # 由 AI 从"人均 100 以内""想去评价好的"这类话里解析出来
    budget_per_person: int = 0      # 0 表示不限
    # 默认就优先高评分，但不硬性排除没有评分的地点（小店/公园常常没有数据）。
    prefer_high_rating: bool = True
    # 住宿：用户指定的酒店名或区域；空表示待定
    lodging: str = ""
    # 按天的住宿（第 1 晚、第 2 晚…）；为空则整趟用 lodging
    lodgings: list[str] = field(default_factory=list)


def _blocked(poi: Poi, avoid: list[str]) -> bool:
    haystack = f"{poi.name} {poi.type_text}"
    return any(word and word in haystack for word in avoid)


def _city_center(candidates: list[Poi]) -> Poi | None:
    if not candidates:
        return None
    lng = sum(p.lng for p in candidates) / len(candidates)
    lat = sum(p.lat for p in candidates) / len(candidates)
    return Poi(
        id="poi_origin",
        # 不谎称"市中心"：用户没指定出发点，就老实叫"出发点"
        name="出发点",
        category="sight",
        indoor=True,
        lng=lng,
        lat=lat,
        stay_min=0,
        type_text="虚拟起点",
    )


def _transit_times(
    start: Poi,
    candidates: list[Poi],
    exempt_names: set[str],
) -> list[int]:
    """从 start 到各候选点的预估通勤分钟数，已排序；必去点单独豁免。"""
    times: list[int] = []
    for poi in candidates:
        if poi.name in exempt_names:
            continue
        try:
            times.append(travel_minutes(start, poi))
        except Exception:
            continue
    times.sort()
    return times


def _first_leg_limit(
    start: Poi,
    candidates: list[Poi],
    configured: int,
    exempt_names: set[str],
) -> int:
    """首段通勤上限：按最近 3 个点单独放宽，最多 120 分钟。"""
    times = _transit_times(start, candidates, exempt_names)
    if not times:
        return configured
    third = times[min(2, len(times) - 1)]
    return max(configured, min(120, third + 10))



_DAY_MARK = re.compile(r"(?:第\s*(\d{1,2})\s*[天晚]|d(\d{1,2})\b|[Dd]ay\s*(\d{1,2}))", re.IGNORECASE)


def _unique_lodging_names(names: list[str]) -> int:
    """有几个不同的住宿名（用于决定摘要怎么说）。"""
    return len({n for n in (names or []) if n})


def parse_lodging(text: str, days: int) -> list[str]:
    """把住宿输入解析成"按天的列表"。

    支持这几种写法（都能识别）：
        如家酒店                      → 整趟都住它
        第1天 A，第2天 B               → 第1晚 A、第2晚 B
        A / B / B                     → 按顺序一天一个
        A；B                          → 同上
    返回值长度 = days；缺的用最后一个已知值补齐，仍没有则为空字符串。
    """
    raw = (text or "").strip()
    if not raw:
        return []

    # 按换行/分号/斜杠/逗号切段，但保留"第N天"这类记号以便绑定
    segments = [seg.strip(" 　·、,，;；/|") for seg in re.split(r"[\n\r；;|/]+|，|,", raw)]
    segments = [seg for seg in segments if seg]

    by_day: dict[int, str] = {}
    sequential: list[str] = []
    for seg in segments:
        mark = _DAY_MARK.search(seg)
        name = _DAY_MARK.sub("", seg).strip(" 　:：-·、,，")
        if not name:
            continue
        if mark:
            index = next((int(g) for g in mark.groups() if g), None)
            if index and 1 <= index <= days:
                by_day[index] = name
            else:
                sequential.append(name)
        else:
            sequential.append(name)

    if by_day:
        # 有明确天号：按天填，缺的用最近一次出现的名字向前/向后补
        last = ""
        result: list[str] = []
        for day in range(1, days + 1):
            name = by_day.get(day) or ""
            if name:
                last = name
            result.append(name or last)
        # 前面缺的用后面第一个补
        first_known = next((n for n in result if n), "")
        return [n or first_known for n in result]

    if len(sequential) == 1:
        return [sequential[0]] * days

    if sequential:
        # 没写天号但给了多个：按顺序一天一个，不够就沿用最后一个
        result = []
        for day in range(1, days + 1):
            if day <= len(sequential):
                result.append(sequential[day - 1])
            else:
                result.append(sequential[-1])
        return result

    return []


def _pick_origin(
    prefs: Preferences,
    candidates: list[Poi],
    warnings: list[str] | None = None,
    must_pois: list[Poi] | None = None,
) -> Poi:
    """起点：优先用用户给的坐标/地点；只有跨城或搜不到时才退回市区中心。"""
    center = _city_center(candidates)
    exempt_names = {p.name for p in (must_pois or [])}
    start: Poi | None = None
    label = ""

    if prefs.start_lat and prefs.start_lng:
        start = Poi(
            id="poi_origin",
            name=prefs.start_place or "我的位置",
            category="sight",
            indoor=False,
            lng=prefs.start_lng,
            lat=prefs.start_lat,
            stay_min=0,
        )
        label = prefs.start_place or "当前定位"
        if center is not None:
            distance_km = distance_m(start, center) / 1000
            # 人在北京、行程排杭州时，跨城段本来就不由这份行程负责。
            if distance_km > 80:
                if warnings is not None:
                    warnings.append(
                        f"你选的出发点离「{prefs.city}」约 {distance_km:.0f} 公里，"
                        "已按市区默认出发点排；跨城交通请单独安排"
                    )
                return center
    elif prefs.start_place:
        label = prefs.start_place
        start = find_by_name(prefs.city, prefs.start_place)
        if start is None and warnings is not None:
            warnings.append(
                f"出发点「{prefs.start_place}」没搜到，已按{prefs.city}市区默认出发点排"
            )
        elif start is not None and center is not None:
            # 搜到了、但在别的城市（从广州出发去南阳）：当天行程不可能从那儿开始，
            # 否则每一站都会"太远"导致整份计划排不出来。
            distance_km = distance_m(start, center) / 1000
            if distance_km > 80:
                if warnings is not None:
                    warnings.append(
                        f"出发点「{prefs.start_place}」离{prefs.city}约 {distance_km:.0f} 公里，"
                        "已按市区默认出发点排；当天的行程从抵达后开始，跨城交通请单独安排"
                    )
                start = None

    if start is None:
        if center is not None:
            return center
        return Poi(
            id="poi_origin",
            name="出发点",
            category="sight",
            indoor=True,
            lng=120.155,
            lat=30.253,
            stay_min=0,
            type_text="虚拟起点",
        )

    # 起点已经确定：不再因为“第一段远”把它换成市区中心。
    # 第一段会在 _ordered_pick 里单独放宽；这里只负责把原因说清楚。
    if center is not None:
        times = _transit_times(start, candidates, exempt_names)
        if times and times[0] > prefs.max_transit_min and warnings is not None:
            warnings.append(
                f"从「{label}」出发，最近的地点约需 {times[0]} 分钟，"
                f"超过你设置的 {prefs.max_transit_min} 分钟；已保留这个起点，"
                "第一段按实际距离单独放宽，后面几段仍按原上限排"
            )
    return start


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

    # 城市必看：在同样通勤和评分条件下优先入选。
    if getattr(poi, "core", False):
        score -= 45
        reasons.append("城市必看")

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

    # 默认优先高评分：没有评分数据只轻降权，不能把新店/公园一刀切掉
    if prefs.prefer_high_rating and poi.rating <= 0:
        score += 5

    # 有招牌菜的店更容易被选中（说明数据完整、也确实是个有内容的点）
    if poi.tags:
        reasons.append("招牌：" + "、".join(poi.tags[:3]))

    return score, reasons, True


def _ordered_pick(
    origin: Poi,
    pool: list[Poi],
    prefs: Preferences,
    first_leg_limit: int | None = None,
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

    def _best_in(subset: list[Poi]):
        """在当前时间/位置上，从 subset 里挑分数最低且走得通的一个。"""
        best = None
        best_transit = None
        best_score = None
        for poi in subset:
            transit = travel_minutes(current, poi)
            # 第一段单独放宽：用户选定的起点要优先保留，不能因为进市区远就
            # 把所有候选都跳过。后续段仍然遵守用户设置的通勤上限。
            limit = first_leg_limit if (not plan and first_leg_limit) else prefs.max_transit_min
            if transit > limit:
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
        return best, best_transit, best_score

    while remain and len(plan) < MAX_NODES - 1:
        core_in_plan = sum(1 for p, _, _, _ in plan if getattr(p, "core", False))
        core_remaining = [p for p in remain if getattr(p, "core", False)]

        # 每天先保证城市必看点：至少 2 个；到 3 个后让位给偏好点，
        # 剩下的必看点留到后面几天，避免一天全是大景点。
        subset = remain
        require_core = bool(core_remaining) and core_in_plan < CORE_PER_DAY_MIN
        if require_core:
            subset = core_remaining
        elif core_in_plan >= CORE_PER_DAY_MAX:
            subset = [p for p in remain if not getattr(p, "core", False)]

        best, best_transit, _best_score = _best_in(subset)
        # 必看点因为距离/营业时间排不进来时，不能把这一天直接判死，
        # 退回普通候选继续排，保证用户至少得到一份能走的计划。
        if best is None and require_core:
            best, best_transit, _best_score = _best_in(remain)
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
        # 停留时长是经验值，不是高德给的营业数据。界面上必须说清楚，
        # 并且允许用户按自己的节奏改（改完由服务端顺延同一天后面的点）。
        "stayMin": stay_minutes,
        "stayBasis": "经验值：按地点类型估算",
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
        "stayBasis": "经验值：按地点类型估算",
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
    # 第一层：城市基础观光点。用户偏好是在此基础上做加减，不能因为
    # 只说了“咖啡/拍照”就排出一份没有景点的行程。
    base_interests = ["景点", "名胜古迹", "公园", "博物馆"]
    search_words = list(
        dict.fromkeys(base_interests + CORE_SEARCH_WORDS + list(prefs.interests or []))
    )
    # 候选池随天数扩容：3 天以内用基础 20 条/词，长行程逐步加到高德单页上限 25。
    per_keyword = min(25, MAX_PER_KEYWORD + max(0, int(prefs.days or 1) - 3))
    candidates = search_interests(prefs.city, search_words, limit=per_keyword)
    candidates = [p for p in candidates if not _blocked(p, prefs.avoid)]
    candidates = _quality_filter(candidates, list(prefs.interests))

    # 城市必看池：5A 景区 / 风景名胜命中的观光点，加上城市基础池里
    # 评分很高的博物馆类地标。只做优先级标记，不硬塞用户明确避开的点。
    core_names: set[str] = set()
    for word in CORE_SEARCH_WORDS:
        try:
            core_names.update(
                p.name
                for p in search_keyword(prefs.city, word, limit=per_keyword)
                if p.category in ("sight", "indoor_sight")
            )
        except RuntimeError:
            # 单个关键词失败不影响整份计划：基础候选已经足够生成。
            continue
    for poi in candidates:
        poi.core = poi.name in core_names or (
            poi.category == "indoor_sight" and poi.rating >= 4.6
        )

    # 用户没有明确提咖啡/下午茶时，候选池里不要出现咖啡馆。
    interest_text = " ".join(str(item) for item in (prefs.interests or []))
    if not any(word in interest_text for word in ("咖啡", "下午茶", "茶馆", "茶室", "甜品", "饮品")):
        candidates = [p for p in candidates if p.category != "cafe"]

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

    warnings: list[str] = []
    origin = _pick_origin(prefs, must_pois + candidates, warnings, must_pois)
    first_leg_limit = _first_leg_limit(
        origin,
        must_pois + candidates,
        prefs.max_transit_min,
        {p.name for p in must_pois},
    )

    # ③ 住宿：用户给了酒店/区域就把它当地理锚点，第二天从酒店出发，
    #    晚上回酒店，酒店通勤按真实路径算。没给就还是过夜占位，不编时间。
    #
    # 支持按天换酒店：只写一家 → 天天住它；写"第1天A，第2天B" →
    # 第 1 晚 A、第 2 晚 B，第二天早上从 A 出发、晚上到 B。
    days_total = int(prefs.days or 1)
    lodging_names: list[str] = list(prefs.lodgings or [])
    if not lodging_names and prefs.lodging.strip():
        lodging_names = parse_lodging(prefs.lodging, days_total)

    # 每晚住哪（索引 0 = 第 1 晚）；None 表示待定
    lodging_pois: list[Poi | None] = []
    for night in range(days_total):
        name = lodging_names[night] if night < len(lodging_names) else ""
        name = (name or "").strip()
        if not name:
            lodging_pois.append(None)
            continue
        poi = find_by_name(prefs.city, name)
        if poi is None:
            warnings.append(
                f"住宿「{name}」没搜到，已按待定处理；"
                "可以换成具体酒店名或附近的地标"
            )
        lodging_pois.append(poi)

    # 兼容旧代码里"只有一个 lodging_poi"的写法：用第 1 晚的那个
    lodging_poi: Poi | None = lodging_pois[0] if lodging_pois else None
    if days_total > 1 and not any(lodging_pois) and not prefs.lodging.strip():
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
    days = max(1, min(14, int(prefs.days or 1)))
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

        # 第 2 天起从"昨晚住的那家"出发；没填酒店就沿用上一站
        last_night = lodging_pois[day - 2] if day >= 2 and day - 2 < len(lodging_pois) else None
        day_origin = current if day == 1 else (last_night or current)

        picks: list[tuple[Poi, int, int, int]] = []
        if day == 1 and must_pois:
            # 必去点不受通勤上限限制，只受当天时间窗约束
            must_prefs = Preferences(**{**day_prefs.__dict__, "max_transit_min": 24 * 60})
            must_ordered = _ordered_pick(day_origin, must_pois, must_prefs)
            picks.extend(must_ordered)

        rest = [p for p in pool if p.name not in used_names and p.name not in locked_names]
        picks.extend(
            _ordered_pick(
                day_origin,
                rest,
                day_prefs,
                first_leg_limit if day == 1 else None,
            )
        )

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
        transit_dropped: list[str] = []
        for poi, old_arrive, old_leave, _old_transit in picks:
            route = choose_route(prev_poi, poi, prefs.city, avoid_walking=prefs.avoid_walking)
            stay = max(20, old_leave - old_arrive)
            route_min = int(route.get("durationMin") or travel_minutes(prev_poi, poi))

            # 直线估算只是粗排；高德真实路径如果超了上限，就在这一步换掉，
            # 不能把“计划写 20 分钟、地图要 50 分钟”的行程交给用户。
            limit = (
                first_leg_limit
                if (day == 1 and not day_stops and first_leg_limit)
                else prefs.max_transit_min
            )
            if route_min > limit and poi.name not in locked_names:
                transit_dropped.append(f"{poi.name}（{route_min} 分钟）")
                continue

            arrive = clock + route_min

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

        if transit_dropped:
            warnings.append(
                f"第 {day} 天有 {len(transit_dropped)} 个点按高德真实通勤超过 "
                f"{prefs.max_transit_min} 分钟，已换成更近的点："
                + "、".join(transit_dropped[:3])
            )

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
        elif last_night is not None:
            meet_label = f"{last_night.name}出发（第 {day} 天）"
            meet_place = last_night.name
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
            if poi.name in locked_names:
                node["selectionReason"] = "必去"
            elif getattr(poi, "core", False):
                node["selectionReason"] = "城市必看"
            elif prefs.interests:
                node["selectionReason"] = "偏好"
            else:
                node["selectionReason"] = "顺路"
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
            # 这一晚住哪儿（注意：按天住宿时第 N 晚可能和前后都不同）
            tonight = lodging_pois[day - 1] if day - 1 < len(lodging_pois) else None

            if tonight is not None:
                # 住哪儿是确定的：到店时间 = 最后一站离开 + 真实路径时长
                hotel_route = choose_route(
                    prev_poi,
                    tonight,
                    prefs.city,
                    avoid_walking=prefs.avoid_walking,
                )
                hotel_start = last_leave + int(hotel_route.get("durationMin") or 0)
                # 到店可能已过午夜：保留真实时间，不再伪装成 23:58。
                # 用户需要知道"今晚可能赶不到"，而不是看到一个人造时间。
                if hotel_start >= 23 * 60 + 59:
                    warnings.append(
                        f"第 {day} 晚预计 "
                        f"{hotel_start // 60:02d}:{hotel_start % 60:02d} 才到住宿"
                        "（已过午夜），请确认是否调整最后一站或换近一点的住处"
                    )
                hotel_end = max(hotel_start + 1, 23 * 60 + 59)
                hotel_title = f"{tonight.name} · 住宿（第 {day} 晚）"
                hotel_place = tonight.name
                # 逐晚换店时要说清楚：第二天从这家出发
                if day < days and any(p is not None and p.name != tonight.name for p in lodging_pois[day:]):
                    hotel_note = "第 " + str(day) + " 晚住这里，第 " + str(day + 1) + " 天从这家出发"
                else:
                    hotel_note = "用户指定的住宿，已作为第二天的出发点"
                hotel_confidence = tonight.data_quality()
                hotel_poi_info = {
                    "name": tonight.name,
                    "address": tonight.address,
                    "rating": tonight.rating or None,
                    "cost": tonight.cost or None,
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
            current = tonight or prev_poi

    stop_count = sum(
        1 for node in nodes
        if node.get("poi") and not node.get("overnight")
    )
    if stop_count == 0:
        raise RuntimeError("没排到任何可执行的地点，换个兴趣词或放宽通勤上限再试")
    if stop_count < 3:
        warnings.append(
            f"这次只排到 {stop_count} 个地点：起点较远或时间太短。"
            "计划仍然保留，不会因为点少而加载失败；可以晚点出发、放宽通勤或减少必去点"
        )

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
            # 城市必看池：池子里有什么、实际排进去了哪些，界面上可以解释
            # “这版为什么像一份旅行计划”，也方便验收覆盖度。
            "mustSeePool": sorted(p.name for p in candidates if getattr(p, "core", False)),
            "mustSeeVisited": [
                node["title"] for node in nodes if node.get("selectionReason") == "城市必看"
            ],
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
                    "requested": ", ".join(lodging_names) if lodging_names else prefs.lodging,
                    "resolved": any(p is not None for p in lodging_pois),
                    "name": lodging_poi.name if lodging_poi is not None else "",
                    "place": lodging_poi.address if lodging_poi is not None else "",
                    # 逐晚清单：界面按这个显示"第 1 晚 A / 第 2 晚 B"
                    "byDay": [
                        {
                            "night": index + 1,
                            "name": poi.name if poi is not None else "",
                            "resolved": poi is not None,
                        }
                        for index, poi in enumerate(lodging_pois)
                    ],
                }
                if (prefs.lodging.strip() or lodging_names)
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
                    (
                        # 只住一家：显示店名（没解析出来就显示用户写的那串）；
                        # 换店：按晚列出，让用户确认系统没理解错
                        "住" + lodging_poi.name
                        if (lodging_poi is not None and _unique_lodging_names(lodging_names) == 1)
                        else (
                            "住宿 " + " / ".join(
                                f"第{i + 1}晚 {n}" for i, n in enumerate(lodging_names) if n
                            )
                            if _unique_lodging_names(lodging_names) > 1
                            else ("住" + next((n for n in lodging_names if n), ""))
                        )
                    ),
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
