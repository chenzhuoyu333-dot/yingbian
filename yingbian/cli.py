"""CLI for the W1 spec.

    python -m yingbian dump
    python -m yingbian case T1
    python -m yingbian case T1 --repair --scheme B
    python -m yingbian demo
    python -m yingbian check
"""

from __future__ import annotations

import argparse
import json
import sys

from .models import Plan, load_plan
from .notify import render_actions, render_notifications
from .propagate import Event, propagate, render
from .repair import RepairResult, apply_actions, render_result, repair


CASES: dict[str, dict] = {
    "T1": {
        "title": "下雨（局部修复）",
        "event": {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7},
    },
    "T2": {
        "title": "成员晚到 1 小时（全体变更）",
        "event": {"type": "delay", "nodeId": "n_meet", "minutes": 60},
    },
    "T3": {
        "title": "餐厅取消（只改 1 处）",
        "event": {"type": "cancel", "nodeId": "n_lunch"},
    },
    "T4": {
        "title": "锁定冲突（必须停下问用户）",
        "event": {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7},
        "lock": ["n_sunset"],
    },
}


def _prepare(plan: Plan, case: str) -> tuple[Plan, Event]:
    if case not in CASES:
        raise SystemExit(f"未知用例 {case}，可选：{', '.join(CASES)}")
    spec = CASES[case]
    working = plan.clone()
    for node_id in spec.get("lock", []):
        working.node(node_id).confirmed = True
    return working, Event.from_dict(spec["event"])


def _result_json(result: RepairResult) -> dict:
    return result.to_dict()


def cmd_dump(args: argparse.Namespace) -> int:
    plan = load_plan(args.data)
    report = propagate(plan)
    if args.json:
        print(json.dumps({"plan": plan.to_dict(), "report": report.to_dict()}, ensure_ascii=False, indent=2))
        return 0
    print(f"{plan.title}｜{plan.date}｜{len(plan.nodes)} 节点 / {len(plan.edges)} 边 / "
          f"{len(plan.confirmed_nodes())} 个 confirmed")
    print(render(report))
    return 0


def cmd_case(args: argparse.Namespace) -> int:
    plan, event = _prepare(load_plan(args.data), args.case)
    report = propagate(plan, event)
    payload: dict = {"case": args.case, "title": CASES[args.case]["title"], "report": report.to_dict()}
    if args.repair:
        result = repair(plan, event, scheme_key=args.scheme)
        payload["repair"] = result.to_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        print(f"{args.case} · {CASES[args.case]['title']}")
        print(render(report))
        print("")
        print(render_result(result))
        if result.status != "blocked":
            print("")
            print(render_notifications(plan, result))
            print("")
            print(render_actions(plan, result))
        return 0
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"{args.case} · {CASES[args.case]['title']}")
    print(render(report))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    plan = load_plan(args.data)
    report = propagate(plan)
    confirmed = len(plan.confirmed_nodes())
    print(f"schema OK：{len(plan.nodes)} 节点、{len(plan.edges)} 边、{confirmed} 个 confirmed")
    print(f"基线受影响节点：{report.affected_count}")
    return 0 if report.affected_count == 0 else 1


def cmd_demo(args: argparse.Namespace) -> int:
    plan, event = _prepare(load_plan(args.data), "T1")
    report = propagate(plan, event)
    result = repair(plan, event, scheme_key="B")
    bar = "=" * 64
    print(bar)
    print("应变 · 90 秒演示（W1 施工图口径）")
    print(bar)
    print("[0–10s] 打开计划：12 个节点、11 条连线、5 个锁定")
    print(render(propagate(plan)))
    print("")
    print("[10–22s] 点「模拟下雨」：15:00–17:00，概率 70%")
    print(render(report))
    print("")
    print("[22–38s] 三个方案：默认 B 保体验")
    for key in ("A", "B", "C"):
        print(render_result(repair(plan, event, scheme_key=key)))
        print("")
    print("[38–50s] 选 B：只改必要节点，锁定的 5 个不动")
    print(render_result(result))
    print("")
    print("[50–62s] 通知预览")
    print(render_notifications(plan, result))
    print("")
    print("[62–75s] 动作清单")
    print(render_actions(plan, result))
    print("")
    applied = apply_actions(plan, [action.to_dict() for action in result.actions])
    print(f"[75–85s] 应用方案 → v{applied.version}；撤销 → v{plan.version}")
    print("[85–90s] 天气来源：和风天气（W3 接入）；当前事件为手动注入")
    if args.json:
        print(json.dumps({"report": report.to_dict(), "repair": result.to_dict()}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yingbian", description="应变 W1 施工图 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func in (("dump", cmd_dump), ("check", cmd_check), ("demo", cmd_demo)):
        item = sub.add_parser(name)
        item.add_argument("--data", default=None)
        item.add_argument("--json", action="store_true")
        item.set_defaults(func=func)

    case = sub.add_parser("case")
    case.add_argument("case", choices=list(CASES))
    case.add_argument("--repair", action="store_true")
    case.add_argument("--scheme", choices=["A", "B", "C"], default="B")
    case.add_argument("--data", default=None)
    case.add_argument("--json", action="store_true")
    case.set_defaults(func=cmd_case)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
