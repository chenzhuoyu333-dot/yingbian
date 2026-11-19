"""景点之间的交通：用高德路径规划算真实耗时，并选择交通方式。

为什么必须调真实接口：
  直线距离估算对同城短途偏差很大。实测同一对点：
    步行 28 分钟 / 骑行 8 分钟 / 公交 36 分钟（含 1.7 公里步行、2 次换乘）
  直线估算会给出"约 20 分钟"，既不是步行也不是公交，谁都不对。

方式选择规则（按用户偏好）：
  · avoid_walking=True（说过"不想多走路"）→ 一律按公共交通
  · 否则优先公共交通；步行或骑行更快时用更快的那个
  · 超过 3 公里不考虑步行；1 公里内不查公交（公交反而慢且要等）

调用量控制：
  一条边最多查 2 个方式，而不是 3 个；结果按坐标缓存；
  接口失败退回直线估算并标注 source=estimate，不假装准确。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from .env import key

TIMEOUT_SECONDS = 8

# 设 YINGBIAN_OFFLINE_ROUTE=1 时只做直线估算，不发请求（单元测试用）
def _remote_enabled() -> bool:
    import os as _os
    return (_os.environ.get("YINGBIAN_OFFLINE_ROUTE") or "") not in ("1", "true", "yes")
_TRANSIT_CITY = "330100"      # 高德公交接口需要城市编码；杭州西湖区
_MAX_CACHE = 512

_last_call_at = 0.0
_THROTTLE_SECONDS = 0.35


@dataclass
class Route:
    minutes: int
    mode: str            # transit | walking | bicycling | estimate
    distance_m: int = 0
    source: str = "amap"  # amap | estimate

    def to_edge(self) -> dict:
        return {
            "minGapMin": self.minutes,
            "travelMode": self.mode,
            "travelSource": self.source,
            "travelDistanceM": self.distance_m,
        }


_CACHE: dict[str, Route] = {}


def _throttle() -> None:
    global _last_call_at
    wait = _THROTTLE_SECONDS - (time.time() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.time()


def _http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(h))


def _key(lat1: float, lng1: float, lat2: float, lng2: float, mode: str) -> str:
    return f"{lat1:.4f},{lng1:.4f}|{lat2:.4f},{lng2:.4f}|{mode}"


def _fetch(mode: str, lat1: float, lng1: float, lat2: float, lng2: float) -> Route | None:
    if not _remote_enabled():
        return None
    cache_key = _key(lat1, lng1, lat2, lng2, mode)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    ak = key("AMAP_KEY")
    if not ak:
        return None

    origin = f"{lng1:.6f},{lat1:.6f}"
    dest = f"{lng2:.6f},{lat2:.6f}"
    if mode == "walking":
        url = (
            "https://restapi.amap.com/v3/direction/walking?"
            + urllib.parse.urlencode({"origin": origin, "destination": dest, "key": ak})
        )
    elif mode == "bicycling":
        url = (
            "https://restapi.amap.com/v4/direction/bicycling?"
            + urllib.parse.urlencode({"origin": origin, "destination": dest, "key": ak})
        )
    else:
        url = (
            "https://restapi.amap.com/v3/direction/transit/integrated?"
            + urllib.parse.urlencode(
                {
                    "origin": origin,
                    "destination": dest,
                    "city": _TRANSIT_CITY,
                    "key": ak,
                }
            )
        )

    _throttle()
    try:
        payload = _http_json(url)
    except Exception:
        return None

    try:
        if mode == "bicycling":
            paths = (payload.get("data") or {}).get("paths") or []
            if not paths:
                return None
            seconds = int(paths[0]["duration"])
            dist = int(paths[0].get("distance") or 0)
        elif mode == "walking":
            if str(payload.get("status")) != "1":
                return None
            paths = (payload.get("route") or {}).get("paths") or []
            if not paths:
                return None
            seconds = int(paths[0]["duration"])
            dist = int(paths[0].get("distance") or 0)
        else:
            if str(payload.get("status")) != "1":
                return None
            transits = (payload.get("route") or {}).get("transits") or []
            if not transits:
                return None
            seconds = int(transits[0]["duration"])
            dist = int(transits[0].get("walking_distance") or 0)
    except (KeyError, TypeError, ValueError):
        return None

    route = Route(
        minutes=max(1, round(seconds / 60)),
        mode=mode,
        distance_m=dist,
        source="amap",
    )
    if len(_CACHE) >= _MAX_CACHE:
        _CACHE.clear()
    _CACHE[cache_key] = route
    return route


def _estimate(lat1: float, lng1: float, lat2: float, lng2: float, mode: str) -> Route:
    meters = _distance_m(lat1, lng1, lat2, lng2) * 1.2
    if mode == "walking":
        speed = 4.2 * 1000 / 60
        overhead = 2
    elif mode == "bicycling":
        speed = 12 * 1000 / 60
        overhead = 3
    else:
        speed = 15 * 1000 / 60
        overhead = 10
    return Route(
        minutes=max(5, round(meters / speed) + overhead),
        mode=mode,
        distance_m=int(meters),
        source="estimate",
    )


def best_route(
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
    avoid_walking: bool = False,
) -> Route:
    """按偏好选交通方式并返回真实耗时。"""
    straight = _distance_m(lat1, lng1, lat2, lng2)

    # 明显不方便走路时，一律公共交通
    if avoid_walking:
        return _fetch("transit", lat1, lng1, lat2, lng2) or _estimate(
            lat1, lng1, lat2, lng2, "transit"
        )

    # 很近：只考虑步行/骑行（公交还要等车，一定更慢）
    if straight <= 1000:
        walk = _fetch("walking", lat1, lng1, lat2, lng2)
        bike = _fetch("bicycling", lat1, lng1, lat2, lng2)
        options = [r for r in (walk, bike) if r is not None]
        if options:
            return min(options, key=lambda r: r.minutes)
        return _estimate(lat1, lng1, lat2, lng2, "walking")

    # 很远：不考虑步行
    if straight > 3000:
        return _fetch("transit", lat1, lng1, lat2, lng2) or _estimate(
            lat1, lng1, lat2, lng2, "transit"
        )

    # 中间距离：先看有没有更快的步行/骑行，否则走公交
    transit = _fetch("transit", lat1, lng1, lat2, lng2)
    bike = _fetch("bicycling", lat1, lng1, lat2, lng2)
    walk = _fetch("walking", lat1, lng1, lat2, lng2) if straight <= 1500 else None

    if transit is None:
        options = [r for r in (bike, walk) if r is not None]
        if options:
            return min(options, key=lambda r: r.minutes)
        return _estimate(lat1, lng1, lat2, lng2, "transit")

    faster = [
        r for r in (bike, walk) if r is not None and r.minutes < transit.minutes
    ]
    if faster:
        return min(faster, key=lambda r: r.minutes)
    return transit
