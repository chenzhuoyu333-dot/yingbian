"""W2 contract server: 6 endpoints over the W1 engine.

Run:
    uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Body, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from yingbian import Event, load_plan, propagate, repair
from yingbian.models import PlanError
from yingbian.repair import apply_actions


app = FastAPI(title="应变 API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = load_plan()
PLANS: dict[str, Any] = {BASE.plan_id: BASE.clone()}
VERSIONS: dict[str, list[Any]] = {BASE.plan_id: [BASE.clone()]}


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
    # W3 will replace this with a real 和风天气 call. Keep source/fetchedAt visible.
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="minutes")
    return _ok({
        "source": "和风天气（W3 待接入）",
        "fetchedAt": now,
        "next2hRainProb": 0.7,
        "text": "15:00 起中雨",
        "lat": lat,
        "lng": lng,
    })


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
