"""Weather adapter: 和风优先 → 高德兜底 → 明确标注的演示数据。

The W2 contract only requires `source` and `fetchedAt`. `isDemo` and `note`
exist so demo data can never pretend to be a real forecast.

为什么要有两级：
  · 和风有逐小时降水概率（pop），是最准的；
  · 但和风现在要求每个账号用专属 API Host，公共域名 devapi.qweather.com 已停用，
    老 Key 会直接 403；
  · 高德天气不需要专属域名，个人 Key 即可用，缺点是没有降水概率、只有天气文字。
    所以我们对文字做保守估计，并把依据写进 `basis` —— 不假装有精确概率。

配置（放在项目根目录 .env，不进 Git）：
  AMAP_KEY=...                                 高德 Web服务 Key
  QWEATHER_HOST=xxxxxxxx.re.qweatherapi.com    和风专属 Host（不带 https://）
  QWEATHER_KEY=...                             和风 Key
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .env import key

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
        "basis": "写死的演示值",
        "note": f"{reason}；这是演示数据，不是真实预报。",
        "lat": lat,
        "lng": lng,
    }


def _get_json(url: str) -> dict:
    """唯一的网络出口 —— 测试里只 mock 这一个函数，就不会真发请求"""
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


# ── 一级：和风（有逐小时降水概率）─────────────────────────────
def _from_qweather(lat: str, lng: str, fetched_at: str) -> dict[str, object] | None:
    host = key("QWEATHER_HOST").replace("https://", "").replace("http://", "").rstrip("/")
    qkey = key("QWEATHER_KEY")
    if not (host and qkey):
        return None

    query = urllib.parse.urlencode({"location": f"{lng},{lat}", "key": qkey})
    payload = _get_json(f"https://{host}/v7/weather/24h?{query}")
    if str(payload.get("code")) != "200":
        raise ValueError(f"和风返回 code={payload.get('code')}")

    hours = (payload.get("hourly") or [])[:2]
    if not hours:
        raise ValueError("和风没有返回 hourly 数据")

    prob = max(int(hour.get("pop") or 0) for hour in hours) / 100
    first = hours[0]
    return {
        "source": "和风天气",
        "isDemo": False,
        "fetchedAt": fetched_at,
        "next2hRainProb": round(prob, 2),
        "text": f"{str(first.get('fxTime', ''))[11:16]} 起{first.get('text', '未知')}",
        "basis": "和风逐小时预报的降水概率 pop",
        "note": "",
        "lat": lat,
        "lng": lng,
    }


# ── 二级：高德（没有概率，只有天气文字，做保守估计）─────────────
def _from_amap(lat: str, lng: str, fetched_at: str) -> dict[str, object] | None:
    amap_key = key("AMAP_KEY")
    if not amap_key:
        return None

    # 高德天气要城市编码，所以先逆地理编码
    query = urllib.parse.urlencode({"location": f"{lng},{lat}", "key": amap_key})
    geo = _get_json(f"https://restapi.amap.com/v3/geocode/regeo?{query}")
    component = (geo.get("regeocode") or {}).get("addressComponent") or {}
    adcode = component.get("adcode")
    if not adcode:
        raise ValueError("高德逆地理编码没拿到 adcode")

    query2 = urllib.parse.urlencode({"city": adcode, "key": amap_key, "extensions": "all"})
    payload = _get_json(f"https://restapi.amap.com/v3/weather/weatherInfo?{query2}")
    if str(payload.get("status")) != "1":
        raise ValueError(f"高德天气 status={payload.get('status')}")

    casts = ((payload.get("forecasts") or [{}])[0].get("casts") or [])
    today = casts[0] if casts else {}
    day = today.get("dayweather", "") or ""
    night = today.get("nightweather", "") or ""
    both = day + night
    text = f"{day}转{night}" if day and night and day != night else (day or night or "未知")

    if "雨" in both:
        prob = 0.8
    elif "雪" in both or "雷" in both:
        prob = 0.7
    elif "阴" in both or "云" in both or "雾" in both:
        prob = 0.3
    else:
        prob = 0.1

    return {
        "source": "高德天气",
        "isDemo": False,
        "fetchedAt": fetched_at,
        "next2hRainProb": prob,
        "text": text,
        "basis": "高德当日预报文字：含雨→0.8，雪/雷→0.7，阴/云/雾→0.3，其余→0.1",
        "note": "高德不提供降水概率，此处为按天气文字的保守估计",
        "lat": lat,
        "lng": lng,
    }


def fetch_weather(lat: str | None = None, lng: str | None = None) -> dict[str, object]:
    lat = str(lat or DEFAULT_LAT)
    lng = str(lng or DEFAULT_LNG)
    fetched_at = _fetched_at()

    errors: list[str] = []
    for provider in (_from_qweather, _from_amap):
        try:
            got = provider(lat, lng, fetched_at)
        except Exception as exc:  # 网络 / 配额 / Key 失效 / 返回异常，统一降级
            errors.append(f"{provider.__name__.replace('_from_', '')}: {exc}")
            continue
        if got:
            return got

    if errors:
        reason = "真实天气获取失败：" + "；".join(errors)
    else:
        reason = "未配置天气 Key（AMAP_KEY / QWEATHER_KEY）"
    return _demo(reason, fetched_at, lat, lng)
