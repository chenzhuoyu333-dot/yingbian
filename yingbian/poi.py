"""高德 POI 检索：把"想去的类型"变成候选地点池。

设计取舍（重要）：
  · 只做检索 + 分类，不做排序 —— 排序在 generate.py 里，那才是可解释的业务逻辑
  · 排序仍用直线距离估算（避免给每个候选点都调一次路径规划）。
  · 最终排出来的每条边再调一次高德路径规划，拿到真实交通方式和预计时间；
    接口失败时退回估算，并在 transport.source=estimate 里如实标明。
  · 所有网络访问只走 _http_json 一个出口，测试里 mock 它就完全不碰网络。

配置（项目根目录 .env）：
  AMAP_KEY=...   高德 Web服务 Key
"""

from __future__ import annotations

import json
import os
import gzip
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

from .env import key

TIMEOUT_SECONDS = 8
MAX_PER_KEYWORD = 20

# type 字符串里的关键词 → 我们自己的分类
# 高德返回的 type 形如 "风景名胜;风景名胜;国家级景点" / "餐饮服务;咖啡厅;咖啡厅"
_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("咖啡", "茶艺", "茶座", "甜品", "饮品"), "cafe"),
    (("餐饮", "中餐厅", "快餐厅", "外国餐厅", "火锅"), "food"),
    (("购物", "商业街", "步行街", "商场", "超市"), "shop"),
    (("风景名胜", "公园", "广场", "寺庙", "教堂", "观景台", "游乐园"), "sight"),
    (("博物馆", "展览馆", "美术馆", "纪念馆", "图书馆", "科技馆", "文化宫"), "indoor_sight"),
]

# 室内判定：这些分类基本都在室内
_INDOOR_CATEGORIES = {"cafe", "food", "indoor_sight", "shop", "other"}

# 默认停留时长（分钟），没有开放时间数据，只能给经验值
_STAY_MIN = {
    "sight": 90,
    "indoor_sight": 80,
    "food": 60,
    "cafe": 40,
    "shop": 60,
    "other": 45,
}

# 兴趣词 → 高德检索关键词（用户说"古镇"就搜"古镇"）
# 默认只放观光类。以前这里带"咖啡"，导致用户什么也没说也会被排进三家咖啡店。
DEFAULT_INTERESTS = ["景点", "公园", "博物馆"]

# 用户嘴里的"兴趣"不都是能拿去搜 POI 的关键词：
#   "拍照""夜景"是风格诉求，拿去做 keywords 搜不出像样的地点，
#   硬搜的结果就是只排出三四个点，整份计划没法看。
# 所以这里显式区分：能搜的给关键词，不能搜的留空（只当偏好，不影响检索）。
INTEREST_KEYWORDS: dict[str, list[str]] = {
    "景点": ["景点"],
    "古镇": ["古镇", "老街"],
    "公园": ["公园"],
    "博物馆": ["博物馆"],
    "咖啡": ["咖啡"],
    "美食": ["美食"],
    "夜景": ["夜景"],
    "爬山": ["山"],
    "拍照": [],   # 风格词：不参与检索
    "摄影": [],
    "打卡": [],
}


def expand_interests(interests: list[str]) -> list[str]:
    """
    把用户的兴趣词翻译成真正能拿去检索的关键词。
    如果一个都翻译不出来（例如只说"想拍照"），退回默认类别 ——
    否则会搜到极少量地点，生成器只能排出三四个点。
    """
    words: list[str] = []
    for interest in interests or []:
        mapped = INTEREST_KEYWORDS.get(interest)
        if mapped is None:
            # 不在词表里的词，原样当关键词用（用户可能说了具体地名/类型）
            if interest.strip():
                words.append(interest.strip())
        else:
            words.extend(mapped)

    if not words:
        words = list(DEFAULT_INTERESTS)
    # 去重但保序
    seen: set[str] = set()
    unique = [w for w in words if not (w in seen or seen.add(w))]
    return unique


def _to_minutes(value: str) -> int | None:
    """'07:30' → 450；解析失败返回 None"""
    text = (value or "").strip()
    if ":" not in text:
        return None
    try:
        hour_s, minute_s = text.split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


@dataclass
class Poi:
    id: str
    name: str
    category: str
    indoor: bool
    lng: float
    lat: float
    stay_min: int
    # ── 以下来自高德 biz_ext（extensions=all），是"真实店面信息"的来源 ──
    rating: float = 0.0        # 评分，0 表示高德没给
    cost: float = 0.0          # 人均，0 表示高德没给
    open_time: str = ""        # 形如 "07:00-21:00"，空表示没给
    tel: str = ""
    tags: list[str] = field(default_factory=list)   # 招牌菜/标签
    type_text: str = ""
    address: str = ""

    def open_window(self) -> tuple[int, int] | None:
        """把营业时间解析成 (开门分钟, 关门分钟)；解析不了返回 None"""
        if not self.open_time or "-" not in self.open_time:
            return None
        left, _, right = self.open_time.partition("-")
        try:
            open_min = _to_minutes(left)
            close_min = _to_minutes(right)
        except ValueError:
            return None
        if open_min is None or close_min is None:
            return None
        if close_min <= open_min:   # 跨天营业（如 17:00-02:00），不做校验
            return None
        return open_min, close_min

    def data_quality(self) -> str:
        """数据完整度：决定节点该标 high / medium / low"""
        filled = sum(1 for v in (self.rating, self.cost, self.open_time) if v)
        if filled == 3:
            return "high"
        if filled >= 1:
            return "medium"
        return "low"
    type_text: str = ""
    address: str = ""

    @property
    def location(self) -> str:
        return f"{self.lng:.6f},{self.lat:.6f}"


_CACHE: dict[str, list[Poi]] = {}

# 高德个人免费 Key 的 QPS 很低，连发几个请求就会返回 10021 CUQPS_HAS_EXCEEDED_THE_LIMIT。
# 这里做两件事：请求间隔节流 + 遇到 10021 退避重试。
_THROTTLE_SECONDS = 0.55
_last_call_at = 0.0


def _throttle() -> None:
    global _last_call_at
    import time

    wait = _THROTTLE_SECONDS - (time.time() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.time()


# 高德是国内直连接口；绕过环境里的 HTTP(S)_PROXY（本机常见占位值 127.0.0.1:9）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_json(url: str) -> dict:
    """唯一的网络出口 —— 测试里 mock 这一个函数就不会发真实请求"""
    with _OPENER.open(url, timeout=TIMEOUT_SECONDS) as response:
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _get_with_retry(url: str, attempts: int = 3) -> dict:
    """QPS 超限时退避重试；其它错误直接抛"""
    import time
    from urllib.error import HTTPError

    last_error: Exception | None = None
    for i in range(attempts):
        _throttle()
        try:
            payload = _http_json(url)
        except HTTPError as exc:  # 网络层错误
            last_error = exc
            time.sleep(0.8 * (i + 1))
            continue
        if str(payload.get("infocode")) == "10021":  # CUQPS_HAS_EXCEEDED_THE_LIMIT
            last_error = RuntimeError("高德 QPS 超限（10021）")
            time.sleep(1.0 * (i + 1))
            continue
        return payload
    raise RuntimeError(f"高德请求连续失败：{last_error}")


# 商场内的店铺特征：名字/地址里带这些，多半是柜台或商铺，不是独立景点
_MALL_MARKERS = ("百货", "商厦", "购物中心", "层", "A座", "B座", "C座", "专柜", "店中店")


def _looks_like_mall_tenant(name: str, address: str) -> bool:
    haystack = f"{name} {address}"
    return any(marker in haystack for marker in _MALL_MARKERS)


def _classify(type_text: str, name: str = "", address: str = "") -> str:
    # 店名比类型字段更可靠：像 "Ora Coffee" 的 type 是"餐饮服务;餐饮相关场所"，
    # 只看类型会被归成普通餐厅，于是绕过"一天最多两家咖啡"的限制。
    lowered = (name or "").lower()
    if any(word in lowered for word in ("coffee", "cafe", "espresso")):
        return "cafe"
    if any(word in (name or "") for word in ("咖啡", "茶馆", "茶室", "茶社")):
        return "cafe"

    for words, category in _CATEGORY_RULES:
        if any(w in type_text for w in words):
            return category
    # 认不出来就归到 other：室内、短停留、低优先级。
    # 以前兜底成 sight，结果把小商铺当成室外景点排进行程里。
    if _looks_like_mall_tenant(name, address):
        return "shop"
    return "other"


def _to_poi(raw: dict) -> Poi | None:
    location = raw.get("location") or ""
    if "," not in location:
        return None
    try:
        lng_s, lat_s = location.split(",", 1)
        lng, lat = float(lng_s), float(lat_s)
    except ValueError:
        return None

    type_text = raw.get("type") or ""
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    category = _classify(type_text, name, raw.get("address") or "")

    # biz_ext 只有 extensions=all 才返回；缺失就留空，绝不编造默认值
    biz = raw.get("biz_ext") or {}
    if not isinstance(biz, dict):
        biz = {}

    def _num(value) -> float:
        try:
            return float(str(value).replace("￥", "").strip())
        except (TypeError, ValueError):
            return 0.0

    tag_raw = raw.get("tag") or ""
    tags = [t.strip() for t in str(tag_raw).split(",") if t.strip()][:6] if tag_raw else []

    return Poi(
        id="poi_" + str(raw.get("id") or abs(hash(name)) % 10**8),
        name=name,
        category=category,
        indoor=category in _INDOOR_CATEGORIES,
        lng=lng,
        lat=lat,
        stay_min=_STAY_MIN.get(category, 60),
        rating=_num(biz.get("rating")),
        cost=_num(biz.get("cost")),
        open_time=str(biz.get("open_time") or "").strip(),
        tel=str(raw.get("tel") or "").strip(),
        tags=tags,
        type_text=type_text,
        address=(raw.get("address") or ""),
    )


def search_keyword(city: str, keyword: str, limit: int = MAX_PER_KEYWORD) -> list[Poi]:
    """按关键词在某个城市里搜地点"""
    cache_key = f"{city}|{keyword}|{limit}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    amap_key = key("AMAP_KEY")
    if not amap_key:
        raise RuntimeError("未配置 AMAP_KEY，无法检索地点（见 .env.example）")

    query = urllib.parse.urlencode(
        {
            "keywords": keyword,
            "city": city,
            "citylimit": "true",
            "offset": str(min(limit, 25)),
            "page": "1",
            "extensions": "all",
            "key": amap_key,
        }
    )
    payload = _get_with_retry(f"https://restapi.amap.com/v3/place/text?{query}")
    if str(payload.get("status")) != "1":
        raise RuntimeError(f"高德检索失败：{payload.get('info')}（{payload.get('infocode')}）")

    pois: list[Poi] = []
    for raw in payload.get("pois") or []:
        poi = _to_poi(raw)
        if poi:
            pois.append(poi)

    # 同名去重（高德同一地点会有多个条目）
    seen: set[str] = set()
    unique: list[Poi] = []
    for poi in pois:
        if poi.name in seen:
            continue
        seen.add(poi.name)
        unique.append(poi)

    _CACHE[cache_key] = unique
    return unique


def search_interests(city: str, interests: list[str]) -> list[Poi]:
    """按多个兴趣词检索并合并去重（风格词会被翻译掉，翻不出来就退回默认类别）"""
    collected: list[Poi] = []
    seen: set[str] = set()
    for word in expand_interests(list(interests or [])):
        for poi in search_keyword(city, word):
            if poi.name in seen:
                continue
            seen.add(poi.name)
            collected.append(poi)
    return collected


def find_by_name(city: str, name: str) -> Poi | None:
    """必去点：按名字精确检索一次"""
    for poi in search_keyword(city, name, limit=5):
        if name in poi.name or poi.name in name:
            return poi
    return None


# ── 几何 ──────────────────────────────────────────
def distance_m(a: Poi, b: Poi) -> float:
    """球面直线距离（米）"""
    r = 6371000.0
    dlat = radians(b.lat - a.lat)
    dlng = radians(b.lng - a.lng)
    h = sin(dlat / 2) ** 2 + cos(radians(a.lat)) * cos(radians(b.lat)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(h))


def travel_minutes(a: Poi, b: Poi, mode: str = "transit") -> int:
    """
    用直线距离估算通勤分钟数。

    为什么估算而不是调路径规划：
      一次生成 20~30 条边，逐个调接口既慢又吃免费配额。
      估算的偏差由 confidence=low + source=estimate 标注出来，用户可以确认或校准。

    系数偏保守（宁可多留时间，也不要生成走不通的计划）。
    """
    meters = distance_m(a, b)
    if mode == "walk":
        speed = 4.2 * 1000 / 60  # 步行 4.2 km/h → 米/分钟
        overhead = 2
    else:
        # 公交/驾车混合：1.2 倍绕行 + 15 km/h 均速 + 10 分钟候车
        speed = 15 * 1000 / 60
        overhead = 10
    return max(5, int(round(meters * 1.2 / speed)) + overhead)


# ── 高德路径规划：最终方案里"怎么走、多久" ───────────────
_ROUTE_CACHE: dict[str, dict] = {}
# 高德整体不可用（超时 / Key 无效 / 配额耗尽）时，本次生成不要每条边都再等 3 次重试
_ROUTE_RETRY_AFTER = 0.0
# 连续失败计数：单次 QPS 抖动不该把整份计划都锁成估算
_ROUTE_FAILURES = 0


def _route_mode(a: Poi, b: Poi, avoid_walking: bool = False) -> str:
    """按距离与偏好选默认方式。

    用户说过"不想多走路"就直接公交，不再考虑步行/骑行；
    否则近的走路、稍近的骑车、远的打车，中间坐公交/地铁。
    """
    if avoid_walking:
        return "transit"
    meters = distance_m(a, b)
    if meters <= 600:
        return "walk"
    if meters <= 1800:
        return "bicycling"
    if meters >= 6000:
        return "driving"
    return "transit"


def _distance_text(meters: int) -> str:
    if meters <= 0:
        return ""
    if meters < 1000:
        return f"{meters} 米"
    return f"{meters / 1000:.1f} 公里"


def _transit_label(transit: dict) -> str:
    """把高德公交方案压成一句人话：地铁 1 号线 + 步行。"""
    parts: list[str] = []
    for segment in transit.get("segments") or []:
        bus = segment.get("bus") or {}
        for line in (bus.get("buslines") or [])[:1]:
            name = str(line.get("name") or "").strip()
            # "地铁1号线(湘湖--萧山国际机场)" → "地铁1号线"
            name = name.split("(")[0].split("（")[0].strip()
            if name and name not in parts:
                parts.append(name)
        walk = segment.get("walking") or {}
        try:
            walk_m = int(walk.get("distance") or 0)
        except (TypeError, ValueError):
            walk_m = 0
        if walk_m >= 250 and "步行" not in parts:
            parts.append("步行")
    return " + ".join(parts[:3]) or "公交/地铁"


def _estimated_route(a: Poi, b: Poi, mode: str) -> dict:
    duration = _estimate_minutes(a, b, mode)
    label = _MODE_LABEL.get(mode, "公交/地铁")
    return {
        "mode": mode,
        "label": label,
        "distanceM": int(round(distance_m(a, b))),
        "durationMin": duration,
        "walkM": int(round(distance_m(a, b))) if mode == "walk" else 0,
        "source": "estimate",
        "text": f"{label}估算 · 约 {duration} 分钟（地图暂不可用）",
    }


_MODE_LABEL = {
    "walk": "步行",
    "bicycling": "骑行",
    "driving": "驾车/打车",
    "transit": "公交/地铁",
}


def _estimate_minutes(a: Poi, b: Poi, mode: str) -> int:
    """没有地图数据时的保守估算；不同方式用不同速度，不能全按公交算。"""
    meters = distance_m(a, b)
    if mode == "walk":
        speed, overhead = 4.2 * 1000 / 60, 2
    elif mode == "bicycling":
        speed, overhead = 12.0 * 1000 / 60, 3
    elif mode == "driving":
        speed, overhead = 25.0 * 1000 / 60, 5
    else:
        speed, overhead = 15.0 * 1000 / 60, 10
    return max(5, int(round(meters * 1.2 / speed)) + overhead)


def _transit_walk_m(transit: dict) -> int:
    """公交方案里所有步行段的总距离；用来实现“少走路”。"""
    total = 0
    for segment in transit.get("segments") or []:
        walk = segment.get("walking") or {}
        try:
            total += int(float(walk.get("distance") or 0))
        except (TypeError, ValueError):
            continue
    if total == 0:
        try:
            total = int(float(transit.get("walking_distance") or 0))
        except (TypeError, ValueError):
            total = 0
    return total


def route_plan(
    a: Poi,
    b: Poi,
    city: str,
    mode: str | None = None,
    transit_variant: str = "fastest",
    avoid_walking: bool = False,
) -> dict:
    """
    调高德路径规划，返回一段路的交通方式、距离和预计分钟数。

    这里只对**最终排进行程的边**调用，不对候选池里的每个点调用。
    没有 Key、接口失败、返回没有路线时一律退回本地估算，并把来源写成
    estimate —— 前端据此显示“估算”，不把假数据伪装成地图结果。
    """
    global _ROUTE_RETRY_AFTER
    import time

    chosen = mode or _route_mode(a, b, avoid_walking)
    if chosen not in {"walk", "bicycling", "transit", "driving"}:
        chosen = "transit"
    cache_key = f"{city}|{a.location}|{b.location}|{chosen}|{transit_variant}"
    if cache_key in _ROUTE_CACHE:
        return dict(_ROUTE_CACHE[cache_key])

    amap_key = key("AMAP_KEY")
    if not amap_key:
        return _estimated_route(a, b, chosen)
    if time.time() < _ROUTE_RETRY_AFTER:
        return _estimated_route(a, b, chosen)

    base = {
        "origin": a.location,
        "destination": b.location,
        "key": amap_key,
    }
    if chosen == "bicycling":
        # 高德骑行是 v4 接口，返回 errcode/data.paths，不是 v3 的 status/route
        url = f"https://restapi.amap.com/v4/direction/bicycling?{urllib.parse.urlencode(base)}"
    else:
        if chosen == "walk":
            endpoint = "walking"
        elif chosen == "driving":
            endpoint = "driving"
            base["strategy"] = "0"
        else:
            endpoint = "transit/integrated"
            base.update({"city": city, "cityd": city, "strategy": "0"})
        url = f"https://restapi.amap.com/v3/direction/{endpoint}?{urllib.parse.urlencode(base)}"
    try:
        payload = _get_with_retry(url)
        if chosen == "bicycling":
            if str(payload.get("errcode")) != "0":
                _route_failed()
                return _estimated_route(a, b, chosen)
            paths = (payload.get("data") or {}).get("paths") or []
            if not paths:
                return _estimated_route(a, b, chosen)
            path = paths[0]
            label = "骑行"
        else:
            if str(payload.get("status")) != "1":
                _route_failed()
                return _estimated_route(a, b, chosen)
            route = payload.get("route") or {}

            if chosen == "transit":
                transits = route.get("transits") or []
                if not transits:
                    return _estimated_route(a, b, chosen)
                if transit_variant == "least_walking":
                    path = min(
                        transits,
                        key=lambda item: (
                            _transit_walk_m(item),
                            int(float(item.get("duration") or 10**9)),
                        ),
                    )
                else:
                    path = transits[0]
                label = _transit_label(path)
            else:
                paths = route.get("paths") or []
                if not paths:
                    return _estimated_route(a, b, chosen)
                path = paths[0]
                label = _MODE_LABEL.get(chosen, "公交/地铁")

        duration_sec = int(float(path.get("duration") or 0))
        distance = int(float(path.get("distance") or distance_m(a, b)))
        duration = max(1, int(round(duration_sec / 60)))
        walk_m = distance if chosen == "walk" else (_transit_walk_m(path) if chosen == "transit" else 0)
        if chosen == "transit" and transit_variant == "least_walking" and walk_m > 0:
            text = f"{label} · 约 {duration} 分钟（步行 {walk_m} 米，已选少走路方案）"
        elif chosen == "transit" and walk_m > 0:
            text = f"{label} · 约 {duration} 分钟（步行 {walk_m} 米）"
        else:
            text = f"{label} · 约 {duration} 分钟"
        result = {
            "mode": chosen,
            "label": label,
            "distanceM": distance,
            "durationMin": duration,
            "walkM": walk_m,
            "source": "amap",
            "text": text,
        }
        _ROUTE_CACHE[cache_key] = dict(result)
        _route_succeeded()
        return result
    except Exception:
        _route_failed()
        return _estimated_route(a, b, chosen)


def _route_failed() -> None:
    """连续 3 次失败才熔断 20 秒；偶发一次就只影响当下这一段。"""
    global _ROUTE_FAILURES, _ROUTE_RETRY_AFTER
    import time

    _ROUTE_FAILURES += 1
    if _ROUTE_FAILURES >= 3:
        _ROUTE_RETRY_AFTER = time.time() + 20


def _route_succeeded() -> None:
    global _ROUTE_FAILURES
    _ROUTE_FAILURES = 0


def _mark(route: dict, reason: str) -> dict:
    result = dict(route)
    result["chosenBy"] = reason
    return result


def choose_route(
    a: Poi,
    b: Poi,
    city: str,
    avoid_walking: bool = False,
    allow_taxi: bool = True,
) -> dict:
    """
    一段路该走、骑还是坐车。

    默认是“公交优先”：步行/骑行必须明显更快（至少省 5 分钟）才取代公交。
    “少走路”则是硬约束：不做纯步行段，公交也挑步行最少的那版；
    只有当公交下车后还要走很远、或打车能省 10 分钟以上时才打车。
    """
    meters = distance_m(a, b)

    # 同一栋楼/隔壁 350 米内，任何交通工具都不如走过去
    if meters <= 350:
        return _mark(route_plan(a, b, city, "walk"), "短距离接驳，直接步行")

    if avoid_walking:
        transit = route_plan(a, b, city, "transit", transit_variant="least_walking")
        transit_min = int(transit.get("durationMin") or 0)
        transfer_walk = int(transit.get("walkM") or 0)
        options = [("transit", transit)]
        # 只在“下车还要走很远”或“公交确实太慢”时才多查一次打车
        if allow_taxi and (transfer_walk >= 800 or (meters >= 5000 and transit_min >= 40)):
            drive = route_plan(a, b, city, "driving")
            drive_min = int(drive.get("durationMin") or 0)
            long_transfer_walk = transfer_walk >= 800 and drive_min <= transit_min + 10
            saves_enough = drive_min <= transit_min - 10
            if long_transfer_walk or saves_enough:
                options.append(("driving", drive))
        kind, best = min(options, key=lambda item: int(item[1].get("durationMin") or 10**6))
        if kind == "driving":
            return _mark(best, "少走路：公交步行太远或打车明显更快")
        return _mark(best, "少走路：已选步行最少的公交方案")

    # 800 米内步行最直接，不值得等车
    if meters <= 800:
        return _mark(route_plan(a, b, city, "walk"), "800 米内，步行最直接")

    # 中短途：公交为基准，步行/骑行要“明显更快”才换
    if meters <= 4500:
        transit = route_plan(a, b, city, "transit")
        transit_min = int(transit.get("durationMin") or 10**6)
        humans: list[tuple[str, dict]] = []
        if meters <= 2000 and _estimate_minutes(a, b, "walk") <= transit_min - 5:
            humans.append(("walk", route_plan(a, b, city, "walk")))
        if _estimate_minutes(a, b, "bicycling") <= transit_min - 5:
            humans.append(("bicycling", route_plan(a, b, city, "bicycling")))
        if not humans:
            return _mark(transit, "公交优先：步行/骑行没有明显更快")
        kind, best_human = min(humans, key=lambda item: int(item[1].get("durationMin") or 10**6))
        margin = int(best_human.get("durationMin") or 10**6) <= transit_min - 5
        if margin:
            return _mark(best_human, f"比公交快 {transit_min - int(best_human['durationMin'])} 分钟")
        return _mark(transit, "公交优先：快得不够多，不换")

    # 长途：公交太慢时才打车
    transit = route_plan(a, b, city, "transit")
    if not allow_taxi:
        return _mark(transit, "公交优先")
    transit_min = int(transit.get("durationMin") or 10**6)
    if transit_min < 35:
        return _mark(transit, "公交优先：时长可接受，不额外叫车")
    drive = route_plan(a, b, city, "driving")
    drive_min = int(drive.get("durationMin") or 10**6)
    if drive_min <= transit_min - 15 or transit_min >= 50:
        return _mark(drive, "公交太慢，改打车")
    return _mark(transit, "公交优先：打车省得不够多")
