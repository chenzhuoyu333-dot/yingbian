"""Weather adapter: real 和风天气 when a key is configured, honest demo data otherwise.

The W2 contract only requires `source` and `fetchedAt`. `isDemo` and `note`
exist so demo data can never pretend to be a real forecast.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT_LAT = "30.27"
DEFAULT_LNG = "120.15"
DEMO_TEXT = "15:00 起中雨"
DEMO_PROB = 0.7
TIMEOUT_SECONDS = 6


def _fetched_at() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="minutes")


def _demo(reason: str, fetched_at: str, lat: str, lng: str) -> dict[str, object]:
    return {
        "source": f"演示数据（{reason}）",
        "isDemo": True,
        "fetchedAt": fetched_at,
        "next2hRainProb": DEMO_PROB,
        "text": DEMO_TEXT,
        "note": f"{reason}；这是演示数据，不是真实预报。",
        "lat": lat,
        "lng": lng,
    }


def fetch_weather(lat: str | None = None, lng: str | None = None) -> dict[str, object]:
    lat = str(lat or DEFAULT_LAT)
    lng = str(lng or DEFAULT_LNG)
    fetched_at = _fetched_at()

    key = os.environ.get("QWEATHER_KEY", "").strip()
    if not key:
        return _demo("未配置 QWEATHER_KEY", fetched_at, lat, lng)

    query = urllib.parse.urlencode({"location": f"{lng},{lat}", "key": key})
    url = f"https://devapi.qweather.com/v7/weather/24h?{query}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        hours = (payload.get("hourly") or [])[:2]
        if not hours:
            raise ValueError("和风天气没有返回 hourly 数据")
        prob = max(int(hour.get("pop") or 0) for hour in hours) / 100
        first = hours[0]
        return {
            "source": "和风天气",
            "isDemo": False,
            "fetchedAt": fetched_at,
            "next2hRainProb": round(prob, 2),
            "text": f"{first.get('fxTime', '')[11:16]} 起{first.get('text', '未知')}",
            "note": "",
            "lat": lat,
            "lng": lng,
        }
    except Exception as exc:  # network / quota / bad key all degrade the same way
        return _demo(f"真实天气获取失败：{exc}", fetched_at, lat, lng)
