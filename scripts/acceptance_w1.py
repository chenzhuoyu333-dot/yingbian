"""W1 acceptance runner: hits the live API and prints a checklist.

Self-contained (starts its own server):
    python scripts/acceptance_w1.py --serve

Against an already running server:
    python -m uvicorn server.app:app --host 127.0.0.1 --port 8000
    python scripts/acceptance_w1.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLAN_ID = "p_sat_guzhen"
RAIN = {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7}


def call(base: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, title: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed += 1
            print(f"  [OK]   {title}")
        else:
            self.failed += 1
            print(f"  [FAIL] {title}")
        if detail:
            for line in detail.splitlines():
                print(f"         {line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=None, help="已运行的服务地址")
    parser.add_argument("--serve", action="store_true", help="自己起一个临时服务再巡检")
    parser.add_argument("--port", type=int, default=8011, help="配合 --serve 使用的端口")
    args = parser.parse_args()

    running = None
    if args.serve:
        import uvicorn

        from server.app import app as api

        running = uvicorn.Server(
            uvicorn.Config(api, host="127.0.0.1", port=args.port, log_level="error")
        )
        threading.Thread(target=running.run, daemon=True).start()
        for _ in range(100):
            if running.started:
                break
            time.sleep(0.1)

    base = (args.base or f"http://127.0.0.1:{args.port}").rstrip("/")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 46)
    print(" 应变 W1 验收：接口级自动巡检")
    print(f" 服务地址 {base}")
    print("=" * 46)

    report = Report()

    try:
        status, body = call(base, f"/api/plan/{PLAN_ID}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n连不上服务：{exc}")
        print("先在项目根目录运行：python -m uvicorn server.app:app --port 8000")
        return 2

    print("\n[1/7] 计划读取")
    data = body.get("data") or {}
    plan = data.get("plan") or {}
    nodes = plan.get("nodes") or []
    edges = plan.get("edges") or []
    titles = {node["id"]: node["title"] for node in nodes}
    report.check(
        "GET /api/plan/{id} 返回完整计划",
        status == 200 and body.get("ok") and len(nodes) == 12 and len(edges) == 11,
        f"{plan.get('title', '?')}｜{len(nodes)} 个节点 / {len(edges)} 条连线｜版本 {plan.get('version')}",
    )

    print("\n[2/7] T1 降雨影响传播")
    status, body = call(base, f"/api/plan/{PLAN_ID}/event", RAIN)
    impact = body.get("data") or {}
    states = impact.get("states") or {}
    hit = {nid: st for nid, st in states.items() if st != "ok"}
    detail = "\n".join(f"{titles.get(nid, nid)}：{st}" for nid, st in hit.items())
    report.check(
        "POST /event 标出受影响节点",
        status == 200
        and states.get("n_sunset") == "at_risk"
        and impact.get("totalCount") == 12,
        f"受影响 {impact.get('affectedCount')}/{impact.get('totalCount')}｜占比 {impact.get('ratio', 0):.0%}\n{detail}",
    )

    print("\n[3/7] T1 三套修复方案")
    status, body = call(base, f"/api/plan/{PLAN_ID}/repair", {"event": RAIN, "schemes": ["A", "B", "C"]})
    repair = body.get("data") or {}
    schemes = repair.get("schemes") or []
    lines = []
    for scheme in schemes:
        actions = "；".join(
            f"{titles.get(item.get('nodeId'), item.get('nodeId'))}→{item.get('action')}：{item.get('reason')}"
            for item in scheme.get("actions") or []
        )
        lines.append(
            f"方案 {scheme.get('id')} {scheme.get('label')}｜改 {scheme.get('changedCount')} 处"
            f"｜保留 {scheme.get('keepRate', 0):.0%}｜{actions}"
        )
    report.check(
        "POST /repair 返回 A/B/C 且状态正常",
        status == 200 and repair.get("status") == "ok" and len(schemes) == 3,
        "\n".join(lines),
    )

    print("\n[4/7] 应用方案并升版本")
    chosen = next((item for item in schemes if item.get("id") == "B"), schemes[-1] if schemes else None)
    if chosen is None:
        report.check("POST /apply 应用所选方案", False, "没有可选方案，跳过")
    else:
        status, body = call(base, f"/api/plan/{PLAN_ID}/apply", {"actions": chosen.get("actions") or []})
        applied = (body.get("data") or {}).get("plan") or {}
        after = {node["id"]: node["title"] for node in applied.get("nodes") or []}
        changed = [f"{nid}：{titles.get(nid)} → {after.get(nid)}" for nid in titles if after.get(nid) and after[nid] != titles[nid]]
        report.check(
            f"POST /apply 应用方案 {chosen.get('id')}，版本 +1",
            status == 200 and (body.get("data") or {}).get("version") == 2 and bool(changed),
            "\n".join(changed) or "计划内容无变化",
        )

    print("\n[5/7] 撤销回到上一版")
    status, body = call(base, f"/api/plan/{PLAN_ID}/undo", {})
    undone = body.get("data") or {}
    report.check(
        "POST /undo 回到版本 1",
        status == 200 and undone.get("version") == 1,
        f"当前版本 {undone.get('version')}",
    )

    print("\n[6/7] 天气接口")
    status, body = call(base, "/api/weather?lat=31.1&lng=121.4")
    weather = body.get("data") or {}
    report.check(
        "GET /weather 带来源与抓取时间",
        status == 200 and bool(weather.get("source")) and bool(weather.get("fetchedAt")),
        f"{weather.get('text')}｜来源 {weather.get('source')}｜抓取 {weather.get('fetchedAt')}",
    )

    print("\n[7/7] T4 锁定节点冲突")
    call(base, "/api/debug/lock", {"planId": PLAN_ID, "nodeId": "n_sunset", "confirmed": True})
    status, body = call(base, f"/api/plan/{PLAN_ID}/repair", {"event": RAIN, "schemes": ["A", "B", "C"]})
    blocked = body.get("data") or {}
    report.check(
        "锁定后重算停在冲突，不擅自改",
        status == 200
        and blocked.get("status") == "blocked"
        and blocked.get("blockedNode") == "n_sunset",
        f"阻断节点 {blocked.get('blockedNode')}｜{blocked.get('message')}",
    )
    call(base, "/api/debug/lock", {"planId": PLAN_ID, "nodeId": "n_sunset", "confirmed": False})

    print("\n" + "=" * 46)
    total = report.passed + report.failed
    if report.failed == 0:
        print(f" 结论：{total}/{total} 项通过，W1 接口验收 OK")
    else:
        print(f" 结论：{report.passed}/{total} 通过，{report.failed} 项需要看")
    print("=" * 46)

    if running is not None:
        running.should_exit = True
        time.sleep(0.3)
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
