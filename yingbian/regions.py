"""省市清单：从高德行政区划接口拉一次，缓存到本地文件。

为什么缓存：
  · 完整数据约 3000 个市，每次打开新建对话框都拉一遍既慢又费配额
  · 缓存文件放 data/regions.json（已 gitignore），首次启动自动生成

取不到时返回空列表，界面就只让用户手输城市 —— 不假装有数据。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from .env import key

TIMEOUT_SECONDS = 10
ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / "data" / "regions.json"


def _fetch() -> dict:
    """调高德区划接口，取省 → 市两级"""
    ak = key("AMAP_KEY")
    if not ak:
        raise RuntimeError("未配置 AMAP_KEY，无法获取省市清单")

    url = "https://restapi.amap.com/v3/config/district?" + urllib.parse.urlencode(
        {"subdistrict": "2", "extensions": "base", "key": ak}
    )
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if str(payload.get("status")) != "1":
        raise RuntimeError(f"高德区划接口失败：{payload.get('info')}")

    provinces = []
    for item in payload.get("districts") or []:
        # 顶层是"中华人民共和国"，它的 districts 才是省
        for province in item.get("districts") or []:
            name = (province.get("name") or "").strip()
            if not name:
                continue
            cities = [
                (city.get("name") or "").strip()
                for city in (province.get("districts") or [])
                if (city.get("name") or "").strip()
            ]
            provinces.append({"name": name, "cities": cities})

    return {"provinces": provinces, "updatedAt": ""}


def load_regions(force: bool = False) -> dict:
    """优先读缓存；没有或 force 时重新拉一次并写回"""
    if not force and CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if data.get("provinces"):
                return data
        except Exception:
            pass

    data = _fetch()
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass   # 写不进去也要能把数据返回给前端
    return data
