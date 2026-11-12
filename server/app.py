"""W2 contract server: 6 endpoints over the W1 engine.

Run:
    uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
import socket
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
from yingbian.generate import Preferences, generate
from yingbian.models import Plan, PlanError
from yingbian.repair import apply_actions
from yingbian.weather import fetch_weather


app = FastAPI(title="应变 API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = load_plan()

# 同时加载 data/plan-*.json：标准版（零缓冲，用于说明"一延误就全崩"）
# 和宽松版（有缓冲，用于演示"缓冲吸收延误"与三个方案分化）。
# 计划 id 以文件里的 planId 为准，前端通过 plan_id 路径参数选择。
PLANS: dict[str, Any] = {}
VERSIONS: dict[str, list[Any]] = {}
for _f in sorted((Path(__file__).resolve().parent.parent / "data").glob("plan-*.json")):
    try:
        _p = load_plan(_f)
    except Exception as _exc:  # 单个文件坏了不影响启动
        print(f"[warn] 跳过 {_f.name}: {_exc}")
        continue
    PLANS[_p.plan_id] = _p.clone()
    VERSIONS[_p.plan_id] = [_p.clone()]
    print(f"[plan] 已加载 {_p.plan_id:<24} {_f.name}  {len(_p.nodes)} 节点")

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
      {"city":"杭州","date":"2026-11-14","startTime":"09:30","endTime":"20:00",
       "interests":["景点","公园","咖啡"],"mustVisit":["清河坊历史文化特色街区"],
       "avoid":["爬山"],"pace":"normal","maxTransitMin":45,"startPlace":""}

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
        prefs = Preferences(
            city=str(body.get("city") or "杭州"),
            date=str(body.get("date") or "2026-11-14"),
            start_time=str(body.get("startTime") or "09:30"),
            end_time=str(body.get("endTime") or "20:00"),
            interests=list(body.get("interests") or []),
            must_visit=list(body.get("mustVisit") or []),
            avoid=list(body.get("avoid") or []),
            pace=str(body.get("pace") or "normal"),
            max_transit_min=int(body.get("maxTransitMin") or 45),
            start_place=str(body.get("startPlace") or ""),
        )
        raw_plan = generate(prefs)
    except Exception as exc:  # 没配 Key / 搜不到地点 / 网络失败，都给出可读原因
        return _error("GENERATE_FAILED", str(exc))

    parsed = Plan.from_dict(raw_plan)
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


@app.get("/api/plan/{plan_id}")
def get_plan(plan_id: str):
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    return _ok({"plan": plan.to_dict(), "version": plan.version})


@app.post("/api/plan/{plan_id}/event")
def post_event(plan_id: str, body: dict = Body(...)):
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    event = Event.from_dict(body)
    report = propagate(plan, event)
    return _ok(report.to_dict())


@app.post("/api/plan/{plan_id}/repair")
def post_repair(plan_id: str, body: dict = Body(...)):
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    raw_event = body.get("event") or body
    event = Event.from_dict(raw_event)
    schemes = body.get("schemes") or ["A", "B", "C"]
    results = [repair(plan, event, key) for key in schemes]
    blocked = next((item for item in results if item.status == "blocked"), None)
    if blocked is not None:
        return _ok({
            "status": "blocked",
            "schemes": [],
            "blockedNode": blocked.blocked_node,
            "message": blocked.message,
        })
    return _ok({
        "status": "ok",
        "schemes": [item.to_dict() for item in results],
        "blockedNode": None,
        "message": "",
    })


@app.post("/api/plan/{plan_id}/apply")
def post_apply(plan_id: str, body: dict = Body(...)):
    plan = _plan_or_404(plan_id)
    if plan is None:
        return _error("NOT_FOUND", "计划不存在", 404)
    actions = body.get("actions") or []
    new_plan = apply_actions(plan, actions)
    new_plan.version = len(VERSIONS[plan_id]) + 1
    PLANS[plan_id] = new_plan
    VERSIONS[plan_id].append(new_plan.clone())
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
