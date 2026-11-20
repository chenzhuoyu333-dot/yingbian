"""W2 contract server: 6 endpoints over the W1 engine.

Run:
    uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from yingbian import Event, load_plan, propagate, repair
from yingbian.ai import (
    available as ai_available,
    explain_scheme,
    parse_event as ai_parse_event,
    parse_preferences as ai_parse_preferences,
)
from yingbian.collab import SCHEMES, STATE as COLLAB
from yingbian.generate import Preferences, generate
from yingbian.location import checkin as location_checkin
from yingbian.location import locate as location_locate
from yingbian.models import Plan, PlanError, parse_time
from yingbian.regions import load_regions
from yingbian.patrol import patrol as run_patrol
from yingbian.discovery import start as start_discovery
from yingbian.repair import RepairResult, apply_actions
from yingbian.weather import fetch_weather


app = FastAPI(title="应变 API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = load_plan()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# 内置示范计划放 data/plan-*.json；用户生成/保存的计划放 data/plans/，
# 这样"我的计划"首页在重启后仍然有历史记录，演示不会一重启就清空。
PLAN_DIR = DATA_DIR / "plans"
PLAN_DIR.mkdir(parents=True, exist_ok=True)

PLANS: dict[str, Any] = {}
VERSIONS: dict[str, list[Any]] = {}


def _register(plan: Any, source: str) -> None:
    PLANS[plan.plan_id] = plan.clone()
    VERSIONS[plan.plan_id] = [plan.clone()]
    count = len([n for n in plan.nodes if not getattr(n, "dropped", False)])
    print(f"[plan] 已加载 {plan.plan_id:<24} {source:<20} {count} 节点")


def persist(plan: Any) -> Path:
    """把计划写进 data/plans/，让首页的"历史记录"是真的存下来的"""
    path = PLAN_DIR / f"{plan.plan_id}.json"
    path.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


for _f in sorted(DATA_DIR.glob("plan-*.json")):
    try:
        _p = load_plan(_f)
    except Exception as _exc:  # 单个文件坏了不影响启动
        print(f"[warn] 跳过 {_f.name}: {_exc}")
        continue
    _register(_p, _f.name)

for _f in sorted(PLAN_DIR.glob("*.json")):
    try:
        _p = load_plan(_f)
    except Exception as _exc:
        print(f"[warn] 跳过 {_f.name}: {_exc}")
        continue
    _register(_p, "data/plans/" + _f.name)

if BASE.plan_id not in PLANS:
    PLANS[BASE.plan_id] = BASE.clone()
    VERSIONS[BASE.plan_id] = [BASE.clone()]


INDEX_HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>应变 · 接口自测</title>
<style>
body{font-family:-apple-system,"Segoe UI",sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#222}
h1{font-size:20px}button{margin:4px 6px 4px 0;padding:8px 14px;border:1px solid #1565C0;background:#fff;color:#1565C0;border-radius:8px;cursor:pointer}
button:hover{background:#1565C0;color:#fff}
pre{background:#f5f5f5;padding:14px;border-radius:8px;overflow:auto;max-height:520px;font-size:12px;line-height:1.5}
.muted{color:#888;font-size:13px}
</style></head><body>
<h1>应变 · 接口自测</h1>
<p class="muted">点按钮看返回，字段和手机端一致。</p>
<div>
  <button onclick="go('GET','/api/plan/__PLAN__')">1 取计划</button>
  <button onclick="go('POST','/api/plan/__PLAN__/event',{type:'rain',from:'15:00',to:'17:00',prob:0.7})">2 下雨 → 影响</button>
  <button onclick="go('POST','/api/plan/__PLAN__/repair',{event:{type:'rain',from:'15:00',to:'17:00',prob:0.7}})">
3 求三方案</button>
  <button onclick="go('POST','/api/plan/__PLAN__/event',{type:'cancel',nodeId:'n_lunch'})">4 餐厅取消</button>
  <button onclick="applyB()">5 应用方案 B</button>
  <button onclick="go('POST','/api/plan/__PLAN__/undo',{})">6 撤销</button>
  <button onclick="go('GET','/api/weather?lat=30.27&lng=120.15')">7 天气</button>
  <button onclick="go('POST','/api/generate',{city:'杭州',interests:['景点','公园','咖啡'],mustVisit:['清河坊历史文化特色街区'],pace:'normal',maxTransitMin:45})">9 生成行程</button>
  <button onclick="go('POST','/api/reset',{})">8 重置</button>
</div>
<pre id="out">点上面任意按钮</pre>
<script>
const PLAN = "__PLAN__";
async function call(method, path, body){
  const res = await fetch(path, {method: method, headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined});
  return {status: res.status, data: await res.json()};
}
async function go(method, path, body){
  const out = await call(method, path, body);
  document.getElementById('out').textContent = out.status + "\\n" + JSON.stringify(out.data, null, 2);
}
async function applyB(){
  const rep = await call('POST', '/api/plan/' + PLAN + '/repair',
    {event: {type: 'rain', from: '15:00', to: '17:00', prob: 0.7}});
  const schemes = (rep.data.data && rep.data.data.schemes) || [];
  const pick = schemes.find(function(s){ return s.id === 'B'; }) || schemes[0] || {actions: []};
  await go('POST', '/api/plan/' + PLAN + '/apply', {actions: pick.actions});
}
</script></body></html>"""


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _plan_or_404(plan_id: str):
    plan = PLANS.get(plan_id)
    if plan is None:
        return None
    return plan


def _error(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"ok": False, "error": {"code": code, "message": message}},
    )


@app.exception_handler(PlanError)
async def plan_error_handler(_, exc: PlanError):
    return _error("PLAN_INVALID", str(exc))


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML.replace("__PLAN__", BASE.plan_id)


@app.post("/api/interpret")
def post_interpret(body: dict = Body(...)):
    """
    一句话 → 结构化意图。这是 AI 站在"理解输入"这一头的地方。

      POST /api/interpret {"text":"想拍照、不想早起，别爬山"}
      → {"intent":"generate","preferences":{...},"source":{"preferences":"ai"}}

      POST /api/interpret {"text":"下午要下雨了"}
      → {"intent":"event","event":{"type":"rain",...},"source":{"event":"ai"}}

    source 如实告诉调用方这次是模型解析（ai）还是规则兜底（rule），
    界面应该显示出来 —— 不能把规则结果伪装成模型结果。
    """
    text = str(body.get("text") or "").strip()
    if not text:
        return _error("EMPTY_TEXT", "先说一句话，例如「想拍照、不想早起，别爬山」或「下午要下雨了」")

    # 意图判定用规则做，不用模型：这一步必须稳定可复现
    event_candidate, event_source = ai_parse_event(text)
    preferences, pref_source = ai_parse_preferences(text)

    intent = "event" if event_candidate and event_candidate.get("type") in ("rain", "delay", "cancel") else "generate"

    return _ok(
        {
            "intent": intent,
            "text": text,
            "preferences": preferences if intent == "generate" else None,
            "event": event_candidate if intent == "event" else None,
            "source": {"preferences": pref_source, "event": event_source},
            "aiAvailable": ai_available(),
            "note": (
                "模型解析" if (pref_source == "ai" or event_source == "ai")
                else "规则解析（未配 LLM_API_KEY 或模型调用失败），功能降级但可用"
            ),
        }
    )


@app.post("/api/generate")
def post_generate(body: dict = Body(...)):
    """
    按偏好生成一份行程，并直接注册进计划表 —— 生成完就能发事件、求方案、应用、撤销。

    请求体（全部可选，缺省用默认值）：
      {"city":"杭州","startDate":"2026-11-19","days":2,"startTime":"09:30","endTime":"20:00",
       "interests":["景点","公园","咖啡"],"mustVisit":["清河坊历史文化特色街区"],
       "avoid":["爬山"],"pace":"normal","maxTransitMin":45,"startPlace":"",
       "lodging":"杭州东站","avoidWalking":true}

    日期也可以传 date / endDate；date 是 startDate 的兼容别名。
    lodging 是酒店名或区域；avoidWalking 表示“少走路”。

    也可以只给一句话，由 AI 解析成偏好：
      {"text":"想拍照、不想早起、别爬山"}

    为什么要注册进来：生成不是终点。用户看到行程后马上要能"下雨了怎么办"，
    所以生成的计划必须和内置计划享受同一套 /event、/repair、/apply、/undo。
    """
    interpretation = None
    text = str(body.get("text") or "").strip()
    if text:
        # AI 解析；显式给了的字段优先，其余由解析结果补
        parsed, source = ai_parse_preferences(text)
        for field, value in parsed.items():
            if field not in body or body.get(field) in (None, "", []):
                body[field] = value
        interpretation = {"text": text, "source": source}

    try:
        trip_date = str(
            body.get("startDate")
            or body.get("date")
            or datetime.now().strftime("%Y-%m-%d")
        )
        trip_days = int(body.get("days") or 1)
        end_text = str(body.get("endDate") or "").strip()
        if end_text:
            try:
                start_dt = datetime.strptime(trip_date, "%Y-%m-%d")
                end_dt = datetime.strptime(end_text, "%Y-%m-%d")
                trip_days = max(1, (end_dt - start_dt).days + 1)
            except ValueError:
                pass
        prefs = Preferences(
            city=str(body.get("city") or "杭州"),
            date=trip_date,
            start_time=str(body.get("startTime") or "09:30"),
            end_time=str(body.get("endTime") or "20:00"),
            interests=list(body.get("interests") or []),
            must_visit=list(body.get("mustVisit") or []),
            avoid=list(body.get("avoid") or []),
            pace=str(body.get("pace") or "normal"),
            max_transit_min=int(body.get("maxTransitMin") or 45),
            start_place=str(body.get("startPlace") or ""),
            start_lat=float(body.get("startLat") or 0.0),
            start_lng=float(body.get("startLng") or 0.0),
            budget_per_person=int(body.get("budgetPerPerson") or 0),
            prefer_high_rating=bool(body.get("preferHighRating") or False),
            lodging=str(body.get("lodging") or "").strip(),
            avoid_walking=bool(body.get("avoidWalking") or False),
            days=trip_days,
        )
        raw_plan = generate(prefs)
    except Exception as exc:  # 没配 Key / 搜不到地点 / 网络失败，都给出可读原因
        return _error("GENERATE_FAILED", str(exc))

    parsed = Plan.from_dict(raw_plan)

    # 每次生成给一个唯一 id：否则都叫 p_generated 会互相覆盖，
    # 首页"我的计划"里也就只有一条。
    stamp = datetime.now().strftime("%m%d-%H%M%S")
    parsed.plan_id = f"p_gen_{stamp}"
    parsed.version = 1
    persist(parsed)

    PLANS[parsed.plan_id] = parsed.clone()
    VERSIONS[parsed.plan_id] = [parsed.clone()]

    return _ok(
        {
            "plan": parsed.to_dict(),
            "version": 1,
            "generation": raw_plan.get("generation", {}),
            # 这次偏好是怎么来的：模型解析还是规则解析，界面要如实显示
            "interpretation": interpretation,
            "hint": f"接下来可以 POST /api/plan/{parsed.plan_id}/event 试试下雨",
        }
    )


@app.post("/api/reset")
def reset():
    for _pid in list(PLANS.keys()):
        _orig = PLANS[_pid]
        # 用版本栈最底部那版做原始快照
        _base = VERSIONS[_pid][0].clone()
        PLANS[_pid] = _base.clone()
        VERSIONS[_pid] = [_base.clone()]
    return _ok({"reset": True, "plans": list(PLANS.keys())})


# App 用 UDP 广播找我们；IP 变了也不用改配置。
# 放在模块级，uvicorn 导入时就会启动，不依赖生命周期事件。
start_discovery()


@app.get("/api/plan/{plan_id}")
def get_plan(plan_id: str):
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    return _ok({"plan": plan.to_dict(), "version": plan.version})


def _member_of(plan_id: str, body: dict):
    """从请求体里取成员；没有就返回 (None, 错误响应)"""
    member_id = str(body.get("memberId") or "").strip()
    if not member_id:
        return None, _error("NO_MEMBER", "缺少 memberId：多人协作要先加入行程")
    member = COLLAB.member(plan_id, member_id)
    if member is None:
        return None, _error("NOT_JOINED", "你还没加入这次行程，请先调用 members 加入")
    return member, None


def _version_guard(plan, body: dict):
    """
    乐观锁：客户端带上它看到的版本号，对不上就拒绝，防止两人同改时悄悄覆盖。
    """
    expected = body.get("expectedVersion")
    if expected is None:
        return None
    try:
        expected = int(expected)
    except (TypeError, ValueError):
        return _error("BAD_VERSION", "expectedVersion 必须是整数")
    if expected != plan.version:
        return _error(
            "VERSION_CONFLICT",
            f"计划已被别人改到 v{plan.version}（你看到的是 v{expected}），请刷新后再操作",
            409,
        )
    return None


def _local_ipv4() -> list[dict[str, object]]:
    """本机所有非回环 IPv4（给 /api/netinfo 用）"""
    import socket as _socket

    found: list[dict[str, object]] = []
    try:
        hostname = _socket.gethostname()
        for info in _socket.getaddrinfo(hostname, None, _socket.AF_INET):
            address = info[4][0]
            if address.startswith("127.") or address.startswith("169.254."):
                continue
            if all(item["ip"] != address for item in found):
                found.append({"ip": address, "url": f"http://{address}:8000"})
    except Exception:
        pass
    return found


@app.get("/api/netinfo")
def get_netinfo():
    """自报家门：手机用浏览器打开这个接口，就能判断网络通不通。

    协议 -> 端口 -> 应用，一层层排除：
      · 浏览器都打不开  → 网络/防火墙/AP 隔离问题，跟 App 无关
      · 浏览器能打开 App 不行 → App 的地址配置问题
    """
    return _ok(
        {
            "app": "yingbian",
            "port": 8000,
            "discoveryPort": 8001,
            "addresses": _local_ipv4(),
            "hint": "手机浏览器打开任意一个 url + /api/plans，能看到 JSON 就说明网络是通的",
        }
    )


@app.get("/api/regions")
def get_regions(force: bool = Query(default=False)):
    """省 → 市两级清单，供新建行程时选目的地。

    数据来自高德行政区划接口，首次调用后缓存到 data/regions.json，
    之后秒回。取不到就返回空列表，界面退回手输城市，不编数据。
    """
    try:
        data = load_regions(force=force)
    except Exception as exc:
        return _error("REGIONS_FAILED", str(exc))
    return _ok(data)


@app.get("/api/plans")
def list_plans():
    """
    "我的计划"首页的数据源。按更新时间倒序，最近改过的排在最前面。

    builtin=true 的是仓库内置的示范计划（用来讲"零缓冲会全崩""有缓冲能吸收"），
    用户可以删掉自己生成的，内置的不建议删。
    """
    items = []
    for plan_id, plan in PLANS.items():
        path = PLAN_DIR / f"{plan_id}.json"
        stored = path.exists()
        items.append(
            {
                "planId": plan_id,
                "title": plan.title,
                "date": plan.date,
                "nodeCount": len([n for n in plan.nodes if not getattr(n, "dropped", False)]),
                "confirmedCount": len(plan.confirmed_nodes()),
                "version": plan.version,
                "updatedAt": (
                    datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
                    if stored
                    else ""
                ),
                "builtin": not stored,
            }
        )
    items.sort(key=lambda item: (item["updatedAt"], item["planId"]), reverse=True)
    return _ok({"plans": items})


@app.delete("/api/plans/{plan_id}")
def delete_plan(plan_id: str):
    if plan_id not in PLANS:
        return _error("NOT_FOUND", "计划不存在", 404)
    path = PLAN_DIR / f"{plan_id}.json"
    if path.exists():
        path.unlink()
    PLANS.pop(plan_id, None)
    VERSIONS.pop(plan_id, None)
    return _ok({"deleted": plan_id, "remaining": list(PLANS)})


@app.post("/api/plans")
def post_plans(body: dict = Body(...)):
    return _error("USE_GENERATE", "新建行程请用 POST /api/generate", 400)


@app.post("/api/plan/{plan_id}/members")
def post_member(plan_id: str, body: dict = Body(...)):
    """加入这次行程（可重复调用，幂等）"""
    if _plan_or_404(plan_id) is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    member_id = str(body.get("memberId") or "").strip()
    if not member_id:
        return _error("NO_MEMBER", "缺少 memberId")
    member = COLLAB.join(plan_id, member_id, str(body.get("name") or ""))
    return _ok({"member": member.to_dict(), "members": [m.to_dict() for m in COLLAB.roster(plan_id)]})


@app.get("/api/plan/{plan_id}/members")
def get_members(plan_id: str):
    return _ok({"members": [m.to_dict() for m in COLLAB.roster(plan_id)]})


@app.get("/api/plan/{plan_id}/activity")
def get_activity(plan_id: str):
    """谁在什么时候改了什么 —— 替代群聊刷屏"""
    return _ok({"activity": COLLAB.feed(plan_id)})


@app.post("/api/plan/{plan_id}/vote/start")
def post_vote_start(plan_id: str, body: dict = Body(...)):
    """
    发起投票。影响大的变化不该由"谁手快"决定，而是少数服从多数 + 超时兜底。
    """
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    member, err = _member_of(plan_id, body)
    if err is not None:
        return err
    event = body.get("event") or {}
    round_ = COLLAB.start_vote(
        plan_id,
        event,
        ttl_sec=int(body.get("ttlSec") or 300),
        default_scheme=str(body.get("defaultScheme") or "B"),
        initiator=member,
    )
    return _ok(round_.to_dict())


@app.post("/api/plan/{plan_id}/vote")
def post_vote(plan_id: str, body: dict = Body(...)):
    """投一票"""
    if _plan_or_404(plan_id) is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    member_id = str(body.get("memberId") or "").strip()
    scheme = str(body.get("schemeId") or body.get("scheme") or "").upper()
    if scheme and scheme not in SCHEMES:
        return _error("BAD_SCHEME", f"只能投 {'/'.join(SCHEMES)}")
    round_, message = COLLAB.cast_vote(plan_id, member_id, scheme)
    if round_ is None:
        return _error("NO_VOTE", message)
    if message:
        return _error("VOTE_REJECTED", message, 409)
    return _ok(round_.to_dict())


@app.get("/api/plan/{plan_id}/vote")
def get_vote(plan_id: str):
    round_ = COLLAB.current_vote(plan_id)
    if round_ is None:
        return _ok({"vote": None})
    return _ok({"vote": round_.to_dict(), "members": [m.to_dict() for m in COLLAB.roster(plan_id)]})


@app.post("/api/plan/{plan_id}/event")
def post_event(plan_id: str, body: dict = Body(...)):
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    member_id = str(body.get("memberId") or "").strip()
    if member_id:
        member = COLLAB.member(plan_id, member_id)
        if member is not None:
            COLLAB.record(
                plan_id,
                member.id,
                member.name,
                f"{member.name} 提出变化：{_describe_event(body)}",
            )
    event = Event.from_dict(body)
    report = propagate(plan, event)
    return _ok(report.to_dict())


@app.get("/api/plan/{plan_id}/patrol")
def get_patrol(
    plan_id: str,
    now: str = Query(default=""),
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
):
    """主动巡检：不等用户开口，先发现"该改计划了"。

    返回提醒清单（落后 / 天气 / 临近最晚进入 / 没有缓冲），
    每条都带 nodeId 和 severity，前端据此决定打扰力度。

    纯确定性判断，不调模型 —— 所以可以在 App 里每隔一段时间调一次。
    """
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)

    text = (now or "").strip()
    if text:
        try:
            now_minutes = parse_time(text)
        except Exception:
            return _error("BAD_TIME", "now 需要 HH:mm 格式")
    else:
        stamp = datetime.now()
        now_minutes = stamp.hour * 60 + stamp.minute

    try:
        result = run_patrol(plan, now_minutes, lat, lng)
    except Exception as exc:
        return _error("PATROL_FAILED", str(exc))
    return _ok(result)


@app.post("/api/plan/{plan_id}/locate")
def post_locate(plan_id: str, body: dict = Body(...)):
    """按当前位置 + 当前时间判断是否落后，落后就给改法。

    场景：17:00 本该到下一个点，人还在上一个点。
    位置只在这一刻用一次，不做持续定位、不留轨迹。

    请求：{lat, lng, now?: "HH:mm"}
      now 可选 —— 演示时可以传"假时间"，把"下午五点"这个场景演出来。
    """
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)

    try:
        lat = float(body.get("lat"))
        lng = float(body.get("lng"))
    except (TypeError, ValueError):
        return _error("BAD_POSITION", "需要 lat 和 lng")

    now_text = str(body.get("now") or "").strip()
    if now_text:
        try:
            now_minutes = parse_time(now_text)
        except Exception:
            return _error("BAD_TIME", "now 需要 HH:mm 格式")
    else:
        stamp = datetime.now()
        now_minutes = stamp.hour * 60 + stamp.minute

    try:
        result = location_locate(plan, lat, lng, now_minutes)
    except Exception as exc:
        return _error("LOCATE_FAILED", str(exc))

    member = COLLAB.member(plan_id, str(body.get("memberId") or "").strip())
    if member is not None and result.get("status") == "behind":
        COLLAB.record(
            plan_id, member.id, member.name,
            f"{member.name} 定位检查：落后 {result.get('driftMinutes')} 分钟（在「{result.get('atNodeTitle')}」）",
        )
    return _ok(result)


@app.post("/api/plan/{plan_id}/checkin")
def post_checkin(plan_id: str, body: dict = Body(...)):
    """到达打卡：准时只确认；晚到则返回影响和可执行方案。

    位置只作为用户主动打卡的上下文，不在这里做持续定位或轨迹共享。
    """
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    try:
        minutes = int(body.get("minutes") or 0)
    except (TypeError, ValueError):
        return _error("BAD_MINUTES", "晚到分钟数必须是整数")
    if minutes < 0 or minutes > 180:
        return _error("BAD_MINUTES", "晚到分钟数应在 0–180 之间")

    node_id = str(body.get("nodeId") or "").strip() or None
    person_id = str(body.get("personId") or "").strip() or None
    try:
        result = location_checkin(plan, node_id, minutes, person_id)
    except ValueError as exc:
        return _error("BAD_CHECKIN", str(exc))

    member = COLLAB.member(plan_id, str(body.get("memberId") or "").strip())
    if member is not None:
        where = result.get("nodeTitle") or "行程"
        detail = "准时到达" if minutes == 0 else f"晚到 {minutes} 分钟"
        COLLAB.record(plan_id, member.id, member.name, f"{member.name} 在「{where}」打卡：{detail}")
    return _ok(result)


def _describe_event(body: dict) -> str:
    kind = str(body.get("type") or "")
    if kind == "rain":
        return f"{body.get('from', '?')}–{body.get('to', '?')} 降雨"
    if kind == "delay":
        return f"{body.get('nodeId', '')} 延后 {body.get('minutes', 0)} 分钟"
    if kind == "cancel":
        return f"{body.get('nodeId', '')} 取消"
    return kind or "未知变化"


def _repair_signature(result: RepairResult) -> tuple:
    """用最终计划判断两套方案是否真的相同，而不是只比方案名字。"""
    return (
        result.status,
        tuple(
            (node.id, node.title, node.start, node.end, node.dropped, node.place, node.indoor)
            for node in result.plan.nodes
        ),
    )


def _dedupe_repairs(results: list[RepairResult]) -> list[RepairResult]:
    if len(results) < 2:
        return results
    unique: list[RepairResult] = []
    seen: dict[tuple, RepairResult] = {}
    for result in results:
        signature = _repair_signature(result)
        first = seen.get(signature)
        if first is None:
            seen[signature] = result
            unique.append(result)
        else:
            first.label = "两种偏好结果一致"
    return unique


def _select_repairs(results: list[RepairResult]) -> tuple[list[RepairResult], RepairResult | None]:
    """只把 blocked 当成阻断；如果还有可用方案，就不要把它一起藏掉。"""
    usable = [item for item in results if item.status != "blocked"]
    if usable:
        return _dedupe_repairs(usable), None
    blocked = next((item for item in results if item.status == "blocked"), None)
    return [], blocked


@app.post("/api/plan/{plan_id}/repair")
def post_repair(plan_id: str, body: dict = Body(...)):
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    raw_event = body.get("event") or body
    event = Event.from_dict(raw_event)
    schemes = body.get("schemes") or ["A", "B"]
    results = [repair(plan, event, key) for key in schemes]
    usable, blocked = _select_repairs(results)
    if not usable and blocked is not None:
        return _ok({
            "status": "blocked",
            "schemes": [],
            "blockedNode": blocked.blocked_node,
            "message": blocked.message,
        })
    return _ok({
        "status": "ok",
        "schemes": [item.to_dict() for item in usable],
        "blockedNode": None,
        "message": "",
    })


@app.post("/api/plan/{plan_id}/apply")
def post_apply(plan_id: str, body: dict = Body(...)):
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)

    # 多人同时改时，宁可让后到的那个人刷新一次，也不要悄悄覆盖别人的改动
    conflict = _version_guard(plan, body)
    if conflict is not None:
        return conflict

    actions = body.get("actions") or []
    new_plan = apply_actions(plan, actions)
    new_plan.version = len(VERSIONS[plan_id]) + 1
    PLANS[plan_id] = new_plan
    VERSIONS[plan_id].append(new_plan.clone())
    # 用户自己生成的计划要落盘，首页的"更新时间"才准
    if (PLAN_DIR / f"{plan_id}.json").exists():
        persist(new_plan)

    member = COLLAB.member(plan_id, str(body.get("memberId") or "").strip())
    if member is not None:
        COLLAB.record(
            plan_id,
            member.id,
            member.name,
            f"{member.name} 应用了方案（v{new_plan.version}，改了 {len(actions)} 处）",
        )
    return _ok({"plan": new_plan.to_dict(), "version": new_plan.version})


@app.post("/api/plan/{plan_id}/undo")
def post_undo(plan_id: str):
    versions = VERSIONS.get(plan_id)
    if not versions:
        return _error("NOT_FOUND", "计划不存在", 404)
    if len(versions) <= 1:
        return _ok({"plan": versions[0].to_dict(), "version": versions[0].version})
    versions.pop()
    plan = versions[-1].clone()
    plan.version = len(versions)
    PLANS[plan_id] = plan
    return _ok({"plan": plan.to_dict(), "version": plan.version})


@app.get("/api/plan/{plan_id}/weather")
def get_plan_weather(plan_id: str):
    """
    按"这份行程实际在哪"查天气。

    取消默认地点的原因：写死一个杭州坐标，会让宁波的行程显示杭州天气 ——
    数据是真的，但和用户无关，比没有更糟。
    找不到坐标就明确返回 available=false，界面不展示天气。
    """
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)

    point = None
    for node in plan.nodes:
        if getattr(node, "dropped", False):
            continue
        poi = getattr(node, "poi", None) or {}
        if poi.get("lat") and poi.get("lng"):
            point = poi
            break

    if point is None:
        return _ok(
            {
                "available": False,
                "reason": "这份行程没有地点坐标（内置示范计划），所以不给天气 —— 不拿默认城市冒充",
                "planId": plan_id,
            }
        )

    data = fetch_weather(point["lat"], point["lng"])
    data["available"] = True
    data["place"] = point.get("name") or ""
    data["planId"] = plan_id
    return _ok(data)


@app.get("/api/weather")
def get_weather(lat: float | None = Query(default=None), lng: float | None = Query(default=None)):
    return _ok(fetch_weather(lat, lng))


@app.post("/api/debug/lock")
def debug_lock(body: dict = Body(...)):
    """Demo-only helper for T4: lock a node before triggering rain."""
    plan = _plan_or_404(body.get("planId", BASE.plan_id))
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    node = plan.find(body.get("nodeId", ""))
    if node is None:
        return _error("NOT_FOUND", "节点不存在", 404)
    node.confirmed = bool(body.get("confirmed", True))
    return _ok({"plan": plan.to_dict(), "version": plan.version})


def _lan_ip() -> str:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print("")
    print("=" * 52)
    print("应变 · 接口服务已启动")
    print("=" * 52)
    print(f"本机：    http://127.0.0.1:{port}")
    print(f"自测页：  http://127.0.0.1:{port}/")
    print(f"局域网：  http://{_lan_ip()}:{port}   <- 手机用这个")
    print(f"计划 ID： {BASE.plan_id}")
    print(
        "天气：    "
        + ("已配置 QWEATHER_KEY，使用真实数据" if os.environ.get("QWEATHER_KEY") else "未配置 Key，返回演示数据（会明确标注）")
    )
    print("按 Ctrl+C 停止")
    print("=" * 52)
    print("")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
