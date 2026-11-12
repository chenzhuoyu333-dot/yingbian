"""AI 接入层：只负责"理解用户说的话"和"解释算出来的结果"。

边界（这条是刻意设计的，也是答辩要讲的）：
    ┌──────────────────────────────┐
    │ 用户说的一句话 / 一串偏好       │
    └───────────────┬──────────────┘
                    ▼
            【 AI：理解意图 】        ← 这里用大模型（本文件）
                    ▼
            结构化事件 / 结构化偏好
                    ▼
            【 确定性算法 】           ← propagate.py / repair.py / generate.py
                    ▼
            方案、保留率、牺牲项
                    ▼
            【 AI：解释结果 】         ← 这里也用大模型
                    ▼
                 人话

为什么决策层不给模型：
  "改哪几处、保留率多少、为什么不动锁定节点"必须可复现、可解释、能追问。
  模型编一个方案出来，我们没法回答"为什么是这三处"。

降级策略（演示不能赌外网）：
  没配 Key / 超时 / 返回不是合法 JSON → 全部退回规则解析，
  并在 source 字段里如实标注 "ai" 还是 "rule"。界面照常可用。

配置（项目根目录 .env，已被 .gitignore 排除）：
  LLM_API_KEY=sk-xxxx
  LLM_BASE_URL=https://api.deepseek.com/v1     # 任何 OpenAI 兼容端点都行
  LLM_MODEL=deepseek-chat
"""

from __future__ import annotations

import json
import re

from .env import key
from .models import format_time, parse_time

DEFAULT_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
TIMEOUT_SECONDS = 5
MAX_TEXT = 200


# ── 底层调用 ──────────────────────────────────────
def _http_post(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    """唯一的网络出口 —— 测试里 mock 它就不会真的调模型"""
    import httpx

    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def available() -> bool:
    return bool(key("LLM_API_KEY"))


def ask(system: str, user: str, timeout: int = TIMEOUT_SECONDS) -> str | None:
    """问模型一句话；任何失败都返回 None（由调用方降级）"""
    api_key = key("LLM_API_KEY")
    if not api_key:
        return None

    base = (key("LLM_BASE_URL") or DEFAULT_BASE).rstrip("/")
    model = key("LLM_MODEL") or DEFAULT_MODEL
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user[:MAX_TEXT]},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        data = _http_post(f"{base}/chat/completions", headers, payload, timeout)
        content = data["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else None
    except Exception:
        return None


def _ask_json(system: str, user: str) -> dict | None:
    """要求模型只吐 JSON；解析失败就当没答（不猜、不修补）"""
    text = ask(system, user)
    if not text:
        return None
    cleaned = text.strip()
    # 容忍 ```json ... ``` 包裹
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


# ── 规则兜底：没有 Key 或模型失败时用 ──────────────
_INTEREST_WORDS = {
    "古镇": ["古镇", "老街", "古街"],
    "公园": ["公园", "绿地", "植物园"],
    "博物馆": ["博物馆", "美术馆", "展览", "纪念馆", "科技馆"],
    "咖啡": ["咖啡", "下午茶", "茶馆"],
    "美食": ["吃", "美食", "小吃", "餐厅", "火锅"],
    "夜景": ["夜景", "夜市", "灯光"],
    "拍照": ["拍照", "出片", "摄影", "打卡"],
    "爬山": ["爬山", "登山", "徒步"],
}

_CITY_WORDS = ["杭州", "上海", "北京", "南京", "苏州", "成都", "广州", "深圳", "西安", "厦门", "青岛", "长沙"]

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _valid_time(value: object) -> bool:
    """
    严格校验 HH:mm。

    不能只用 parse_time —— 它把 "25:99" 算成 1599 分钟不报错，
    结果模型给的坏值会一路流到排程里。
    """
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
    if not match:
        return False
    hour, minute = int(match.group(1)), int(match.group(2))
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _cn_number(text: str) -> int | None:
    """把 "六" / "十二" / "二十" 这类转成数字"""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(text) == 1 and text in _CN_DIGITS:
        return _CN_DIGITS[text]
    return None


_CN_TIME_PATTERN = re.compile(
    r"(?:(?P<pre>上午|下午|中午|晚上|傍晚|凌晨|早上)\s*)?"
    r"(?P<hour>[一二两三四五六七八九十]{1,3}|\d{1,2})\s*[点:：时]\s*"
    r"(?P<minute>半|[0-9]{1,2}|[一二三四五六七八九十]{1,3})?"
)

# 否定语境：这些词出现在某个兴趣词前面时，说明用户想要的是"避开"
_NEGATION_PATTERN = r"(?:不想|不要|不用|不|别|避开|避免|无需|懒得)"


def _is_negated(text: str, word: str) -> bool:
    """判断某个兴趣词是不是出现在否定语境里（"别爬山"、"不想去博物馆"）"""
    return re.search(_NEGATION_PATTERN + r"[^，。；;]{0,4}" + re.escape(word), text) is not None


def _normalize_time_text(text: str) -> str:
    """
    把"晚上六点半"这类说法规范成 "18:30"，后面才能用同一套正则抽时间。

    没有它，规则兜底遇到中文数字就完全失效 —— 而这恰恰是演示时最自然的说法。

    前缀会延续到同一句里的后续时间点：说"晚上六点到七点"时，
    "七点"也应该是 19:00 而不是 07:00。遇到句号/分号就重置。
    """
    text = text or ""
    prefix_state = {"value": "", "end": 0}
    cursor = {"end": 0}

    # 先抓整句里最早出现的时段词作为初始前缀：
    # "下午要下雨了，四点下到六点" 里，"下午"离"四点"很远但语义上管着它。
    leading = re.search(r"上午|下午|中午|晚上|傍晚|凌晨|早上", text)
    if leading:
        prefix_state["value"] = leading.group(0)

    # "轻松一点""稍微慢一点"里的"一点"是量词，不是 1 点钟。
    # 判断依据：前面紧邻的是这些字，且没说"点分"、没有时间前缀。
    _QUANTIFIER_BEFORE = "松慢快多少好高矮大小早点些有再差微儿快"

    def repl(match: re.Match) -> str:
        segment = text[cursor["end"]:match.start()]
        if re.search(r"[。；;！!？?\n]", segment):
            prefix_state["value"] = ""

        explicit = match.group("pre")
        if explicit:
            prefix_state["value"] = explicit
        prefix = prefix_state["value"]
        cursor["end"] = match.end()

        hour = _cn_number(match.group("hour")) or 0
        minute_raw = match.group("minute")
        if minute_raw == "半":
            minute = 30
        elif minute_raw:
            minute = _cn_number(minute_raw) or 0
        else:
            minute = 0

        # 量词守卫：无前缀、无分钟、且"一点"前面是量词字 → 不是时间
        if not explicit and not minute_raw and hour == 1:
            before = text[max(0, match.start() - 1):match.start()]
            if before and before in _QUANTIFIER_BEFORE:
                return match.group(0)

        if prefix in ("下午", "晚上", "傍晚") and hour < 12:
            hour += 12
        elif prefix == "中午" and hour < 11:
            hour += 12
        elif prefix == "凌晨" and hour == 12:
            hour = 0

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return match.group(0)  # 不规范就原样留着，别造出更坏的值
        return f"{hour:02d}:{minute:02d}"

    return _CN_TIME_PATTERN.sub(repl, text)


def _rule_preferences(text: str) -> dict:
    """从中文里抽偏好。粗糙但诚实——抽不到就用默认值，并让 source 标成 rule。"""
    text = _normalize_time_text(text or "")
    interests: list[str] = []
    avoided: list[str] = []
    for name, words in _INTEREST_WORDS.items():
        hit = next((w for w in words if w in text), None)
        if hit is None:
            continue
        if _is_negated(text, hit):
            avoided.append(name)   # "别爬山" 是排除，不是兴趣
        else:
            interests.append(name)

    city = next((c for c in _CITY_WORDS if c in text), "杭州")

    # 时间：显式 HH:mm 优先，其次"下午/早上/不想早起"这类口头说法
    start_time = "09:30"
    explicit = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if explicit:
        start_time = format_time(int(explicit.group(1)) * 60 + int(explicit.group(2)))
    elif any(w in text for w in ["不想早起", "睡到自然醒", "晚点出发", "别太早"]):
        start_time = "10:30"
    elif "早上" in text or "一早" in text:
        start_time = "08:30"
    elif "中午" in text:
        start_time = "11:30"

    end_time = "20:00"
    if any(w in text for w in ["早点回", "不想太晚", "晚上有事", "早结束"]):
        end_time = "17:30"
    elif any(w in text for w in ["全天", "一整天", "从早到晚"]):
        end_time = "21:00"

    pace = "normal"
    if any(w in text for w in ["轻松", "不想赶", "慢慢", "休闲", "放松"]):
        pace = "relaxed"
    elif any(w in text for w in ["紧凑", "多去几个", "尽可能多", "赶"]):
        pace = "packed"

    # "必去" 后面跟的地点名（贪心取到标点或句末）
    must: list[str] = []
    for match in re.finditer(r"(?:必去|一定要去|必须去|想去)\s*([\u4e00-\u9fa5A-Za-z0-9·\-]{2,20})", text):
        name = match.group(1).strip("，。、,.")
        if name:
            must.append(name)

    avoid = avoided
    if any(w in text for w in ["不想爬山", "不爬山", "别爬山", "不想走路", "恐高"]) and "爬山" not in avoid:
        avoid = avoid + ["爬山"]

    return {
        "city": city,
        "startTime": start_time,
        "endTime": end_time,
        "interests": interests or ["景点", "公园", "咖啡"],
        "mustVisit": must,
        "avoid": avoid,
        "pace": pace,
        "maxTransitMin": 45,
    }


_EVENT_RULES = [
    (r"取消|不去了|去不了", "cancel"),
    (r"下雨|降雨|雨天|雨", "rain"),
    (r"晚到|迟到|延误|堵车|推迟", "delay"),
    (r"提前|早到", "delay"),  # 提前也走 delay，minutes 取负
]


def _rule_event(text: str) -> dict | None:
    text = _normalize_time_text(text or "")
    kind = None
    for pattern, value in _EVENT_RULES:
        if re.search(pattern, text or ""):
            kind = value
            break
    if kind is None:
        return None

    if kind == "delay":
        minutes = 30
        found = re.search(r"(\d{1,3})\s*(?:分钟|分)", text or "")
        if found:
            minutes = int(found.group(1))
        if any(w in (text or "") for w in ["提前", "早到"]):
            minutes = -minutes
        return {"type": "delay", "nodeId": "n_meet", "minutes": minutes}

    if kind == "cancel":
        # 规则层猜不出具体取消哪个点，交给上层用默认值并在 source 里标明
        return {"type": "cancel", "nodeId": "n_lunch"}

    # 降雨：默认 15:00–17:00，抽到时间段就覆盖
    start, end = "15:00", "17:00"
    times = re.findall(r"(\d{1,2})[:：](\d{2})", text or "")
    if len(times) >= 2:
        start = format_time(int(times[0][0]) * 60 + int(times[0][1]))
        end = format_time(int(times[1][0]) * 60 + int(times[1][1]))
    elif len(times) == 1:
        start = format_time(int(times[0][0]) * 60 + int(times[0][1]))
        end = format_time(min(parse_time(start) + 120, 23 * 60 + 59))
    elif any(w in (text or "") for w in ["一整天", "全天", "一直下"]):
        start, end = "09:00", "20:00"
    return {"type": "rain", "from": start, "to": end, "prob": 0.8}


# ── 对外两个能力 ──────────────────────────────────
_PREF_SYSTEM = """你是行程偏好解析器。把用户的中文需求解析成 JSON，只输出 JSON，不要解释。
字段：city(字符串)、startTime(HH:mm)、endTime(HH:mm)、interests(字符串数组，
取值只能是 古镇/公园/博物馆/咖啡/美食/夜景/拍照/爬山 之一)、mustVisit(字符串数组)、
avoid(字符串数组)、pace(relaxed|normal|packed)、maxTransitMin(整数分钟，5~120)。
拿不准的字段用默认值：city=杭州, startTime=09:30, endTime=20:00,
interests=["景点","公园","咖啡"], pace=normal, maxTransitMin=45。"""


def parse_preferences(text: str) -> tuple[dict, str]:
    """
    一句话 → 结构化偏好。
    返回 (prefs, source)，source 为 "ai" 或 "rule" —— 界面要如实显示。
    """
    data = _ask_json(_PREF_SYSTEM, text)
    if data is not None:
        merged = _rule_preferences(text)  # 用规则结果做默认值
        for k, v in data.items():
            if v in (None, "", []):
                continue
            merged[k] = v
        # 校验：时间必须是合法 HH:mm（parse_time 对 25:99 不报错，必须自己查），
        # pace 必须在枚举里，maxTransitMin 必须落区间
        fixed = _rule_preferences(text)
        for field in ("startTime", "endTime"):
            if not _valid_time(merged.get(field)):
                merged[field] = fixed[field]
        if merged.get("pace") not in ("relaxed", "normal", "packed"):
            merged["pace"] = fixed["pace"]
        try:
            merged["maxTransitMin"] = max(5, min(120, int(merged.get("maxTransitMin", 45))))
        except (TypeError, ValueError):
            merged["maxTransitMin"] = 45
        return merged, "ai"
    return _rule_preferences(text), "rule"


_EVENT_SYSTEM = """你是行程变化解析器。把用户的中文描述解析成一个 JSON 事件，只输出 JSON。
两种事件：
1) 天气：{"type":"rain","from":"HH:mm","to":"HH:mm","prob":0~1}
2) 延误：{"type":"delay","nodeId":"n_meet","minutes":整数，提前为负数}
3) 取消：{"type":"cancel","nodeId":"n_lunch"}
只输出 JSON，不要解释。规则判断不了时输出 {"type":"unknown"}。"""


def parse_event(text: str) -> tuple[dict | None, str]:
    """一句话 → 结构化事件。返回 (event, source)"""
    data = _ask_json(_EVENT_SYSTEM, text)
    if data and data.get("type") in ("rain", "delay", "cancel"):
        if data["type"] == "rain":
            if not (_valid_time(data.get("from")) and _valid_time(data.get("to"))):
                return _rule_event(text), "rule"
            prob = data.get("prob", 0.8)
            data["prob"] = 0.8 if not isinstance(prob, (int, float)) else max(0.0, min(1.0, float(prob)))
        return data, "ai"
    return _rule_event(text), "rule"


_EXPLAIN_SYSTEM = """你是行程助手的解释模块。基于给定的算法结果，用中文写 1~2 句人话，
说明"改了哪几处、代价是什么"。不要编造没给出的信息，不要给出新方案。
不超过 60 字。"""


def explain_scheme(plan_summary: str) -> tuple[str, str]:
    """
    把算法结果翻译成人话。
    plan_summary 是确定性算法产出的结构化摘要（已包含策略、改动数、牺牲项）。
    """
    text = ask(_EXPLAIN_SYSTEM, plan_summary)
    if text and text.strip():
        return text.strip()[:200], "ai"
    return plan_summary, "rule"
