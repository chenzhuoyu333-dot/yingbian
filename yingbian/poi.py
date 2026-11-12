"""高德 POI 检索：把"想去的类型"变成候选地点池。

设计取舍（重要）：
  · 只做检索 + 分类，不做排序 —— 排序在 generate.py 里，那才是可解释的业务逻辑
  · 通勤时间**不在这里调路径规划**：一次生成会用到二三十条边，逐个调接口既慢又吃配额。
    generate.py 用直线距离 + 分速度估算，并标 confidence=low/source=estimate，
    需要精确时再单独校准 —— 这也是"数据诚实"的一部分。
  · 所有网络访问只走 _http_json 一个出口，测试里 mock 它就完全不碰网络。

配置（项目根目录 .env）：
  AMAP_KEY=...   高德 Web服务 Key
"""

from __future__ import annotations

import json
import os
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
DEFAULT_INTERESTS = ["景点", "公园", "博物馆", "咖啡"]

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
        words = ["景点", "公园", "博物馆", "咖啡"]
    # 去重但保序
    seen: set[str] = set()
    unique = [w for w in words if not (w in seen or seen.add(w))]
    return unique


@dataclass
class Poi:
    id: str
    name: str
    category: str
    indoor: bool
    lng: float
    lat: float
    stay_min: int
    type_text: str = ""
    address: str = ""

    @property
    def location(self) -> str:
        return f"{self.lng:.6f},{self.lat:.6f}"


_CACHE: dict[str, list[Poi]] = {}

# 高德个人免费 Key 的 QPS 很低，连发几个请求就会返回 10021 CUQPS_HAS_EXCEEDED_THE_LIMIT。
# 这里做两件事：请求间隔节流 + 遇到 10021 退避重试。
_THROTTLE_SECONDS = 0.4
_last_call_at = 0.0


def _throttle() -> None:
    global _last_call_at
    import time

    wait = _THROTTLE_SECONDS - (time.time() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.time()


def _http_json(url: str) -> dict:
    """唯一的网络出口 —— 测试里 mock 这一个函数就不会发真实请求"""
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


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


def _classify(type_text: str) -> str:
    for words, category in _CATEGORY_RULES:
        if any(w in type_text for w in words):
            return category
    # 认不出来就归到 other：室内、短停留、低优先级。
    # 以前兜底成 sight，结果把小商铺当成室外景点排进行程里。
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
    category = _classify(type_text)
    name = (raw.get("name") or "").strip()
    if not name:
        return None

    return Poi(
        id="poi_" + str(raw.get("id") or abs(hash(name)) % 10**8),
        name=name,
        category=category,
        indoor=category in _INDOOR_CATEGORIES,
        lng=lng,
        lat=lat,
        stay_min=_STAY_MIN.get(category, 60),
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
            "extensions": "base",
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
