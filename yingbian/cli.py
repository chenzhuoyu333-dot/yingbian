"""Command line entry points.

    python -m yingbian plan
    python -m yingbian impact --event rain --from 15:00 --to 17:00
    python -m yingbian repair --event rain --from 15:00 --to 17:00
    python -m yingbian demo
    python -m yingbian check
"""

from __future__ import annotations

import argparse
import json
import sys

from .models import Plan, format_time, load_plan, parse_time
from .notify import build_preview, render_actions, render_notifications, render_preview
from .propagate import Event, analyze, render
from .repair import RepairError, RepairResult, apply_repair, repair, render_results


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data", default=None, help="计划 JSON 路径")
    parser.add_argument("--no-cpsat", action="store_true", help="使用贪心回退，不调用 CP-SAT")
    parser.add_argument("--time-limit", type=float, default=2.0, help="单方案求解上限（秒）")
    parser.add_argument("--json", action="store_true", help="输出 JSON，便于接入 UI 或测试")


def _event_from_args(args: argparse.Namespace) -> Event | None:
    event_type = getattr(args, "event", "none")
    if event_type == "none":
        return None
    start = parse_time(args.start) if getattr(args, "start", None) else None
    end = parse_time(args.end) if getattr(args, "end", None) else None
    node_ids = tuple(getattr(args, "node", []) or ())
    if event_type == "closure" and not node_ids:
        raise SystemExit("closure 事件需要用 --node 指定节点")
    return Event(type=event_type, start=start, end=end, node_ids=node_ids)


def _event_json(event: Event | None) -> dict | None:
    if event is None:
        return None
    return {
        "type": event.type,
        "start": format_time(event.start) if event.start is not None else None,
        "end": format_time(event.end) if event.end is not None else None,
        "node_ids": list(event.node_ids),
        "label": event.summary(),
    }


def _report_json(plan: Plan, report) -> dict:
    return {
        "event": _event_json(report.event),
        "impact_ratio": round(report.impact_ratio, 4),
        "severity": report.severity,
        "affected": report.affected,
        "affected_persons": report.affected_persons,
        "critical_path": report.critical_path,
        "locked_preserved": report.locked_preserved,
        "nodes": {
            node_id: {
                "title": item.title,
                "state": item.state,
                "planned_start": format_time(item.planned_start),
                "start": format_time(item.start),
                "finish": format_time(item.finish),
                "slack": item.slack,
                "reason": item.reason,
            }
            for node_id, item in report.nodes.items()
            if item.state != "inactive"
        },
    }


def _result_json(result: RepairResult) -> dict:
    return {
        "scheme": result.scheme.key,
        "name": result.scheme.name,
        "status": result.status,
        "solve_ms": round(result.solve_ms, 1),
        "changed_count": result.changed_count,
        "changed_persons": result.changed_persons,
        "locked_preserved": result.locked_preserved,
        "changes": [
            {
                "node_id": change.node_id,
                "title": change.title,
                "old_start": format_time(change.old_start),
                "new_start": format_time(change.new_start),
                "old_active": change.old_active,
                "new_active": change.new_active,
                "describe": change.describe(),
            }
            for change in result.changes
        ],
        "note": result.note,
    }


def cmd_plan(args: argparse.Namespace) -> int:
    plan = load_plan(args.data)
    report = analyze(plan)
    if args.json:
        print(json.dumps(_report_json(plan, report), ensure_ascii=False, indent=2))
        return 0
    print(f"{plan.title}｜{len(plan.nodes)} 节点 / {len(plan.active_nodes())} 活动节点｜v{plan.version}")
    print(f"成员：{'、'.join(m.name for m in plan.members)}")
    print("")
    print(render(report, plan))
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    plan = load_plan(args.data)
    event = _event_from_args(args)
    report = analyze(plan, event)
    if args.json:
        print(json.dumps(_report_json(plan, report), ensure_ascii=False, indent=2))
        return 0
    print(render(report, plan))
    return 0


def _solve(plan: Plan, event: Event | None, args: argparse.Namespace) -> list[RepairResult]:
    return repair(
        plan,
        event,
        time_limit=args.time_limit,
        use_cpsat=not args.no_cpsat,
    )


def cmd_repair(args: argparse.Namespace) -> int:
    plan = load_plan(args.data)
    event = _event_from_args(args)
    report = analyze(plan, event)
    try:
        results = _solve(plan, event, args)
    except RepairError as exc:
        print(f"无法自动修复：{exc}")
        return 2

    if args.json:
        payload = {
            "impact": _report_json(plan, report),
            "results": [_result_json(result) for result in results],
        }
        notifications, actions = build_preview(plan, results[0])
        payload["notification_preview"] = [
            {"person": n.person_id, "name": n.person_name, "level": n.level, "text": n.text}
            for n in notifications
        ]
        payload["actions"] = [
            {"text": a.text, "kind": a.kind, "phone": a.phone, "script": a.script}
            for a in actions
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(render(report, plan))
    print("")
    print(render_results(plan, results))
    print("")
    print(render_preview(plan, results[0]))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    plan = load_plan(args.data)
    report = analyze(plan)
    bad = [item for item in report.nodes.values() if item.state == "at_risk"]
    print(f"schema OK：{len(plan.nodes)} 节点、{len(plan.edges)} 条边、{len(plan.members)} 人")
    print(f"活动节点：{len(plan.active_nodes())}｜备选组：{len(plan.alt_groups())}")
    print(f"关键路径：{' → '.join(report.critical_path)}")
    print(f"基线风险节点：{len(bad)}")
    return 1 if bad else 0


def cmd_demo(args: argparse.Namespace) -> int:
    plan = load_plan(args.data)
    baseline = analyze(plan)
    event = Event(type="rain", start=15 * 60, end=17 * 60, label="古镇 15:00 起中雨，持续 2 小时")
    report = analyze(plan, event)
    try:
        results = _solve(plan, event, args)
    except RepairError as exc:
        print(f"无法自动修复：{exc}")
        return 2
    best = results[0]
    next_plan = apply_repair(plan, best)
    notifications, actions = build_preview(plan, best)

    bar = "=" * 66
    print(bar)
    print("应变 · 90 秒演示链路（W1 + W2 原型，真实求解）")
    print(bar)
    print("")
    print("[0–10s] 打开 App：一张知道依赖关系的日程图")
    print(f"  {plan.title}｜{len(plan.nodes)} 节点｜锁定节点："
          f"{', '.join(n.id for n in plan.nodes if n.locked)}")
    print(render(baseline, plan))
    print("")
    print("[10–22s] 点“下雨 15:00”：影响沿依赖边传播")
    print(render(report, plan))
    print("")
    print("[22–38s] 三个方案，各有一行“牺牲”")
    print(render_results(plan, results))
    print("[38–50s] 选方案 A：只有必要节点变化，锁定项不动")
    print(f"  版本 v{plan.version} → v{next_plan.version}")
    print(f"  {best.summary()}")
    for change in best.changes:
        print(f"  - {change.describe()}")
    print("")
    print("[50–62s] 通知预览：只打扰需要动作的人")
    print(render_notifications(plan, best))
    print("")
    print(f"[62–75s] 动作清单：共 {len(actions)} 项，系统不替人执行")
    print(render_actions(plan, best))
    print("")
    print(f"[75–85s] 撤销：v{next_plan.version} → v{plan.version}，恢复上一版本")
    print("[85–90s] 真实天气横幅：待接和风天气 API（W4），当前事件为手动注入")
    print("")
    print(bar)
    print(f"求解耗时：A {results[0].solve_ms:.0f} ms / B {results[1].solve_ms:.0f} ms"
          f" / C {results[2].solve_ms:.0f} ms")
    if args.json:
        print(json.dumps({"results": [_result_json(r) for r in results]}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yingbian", description="应变：变化处理原型")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="打印计划与基线状态")
    _add_common(plan_parser)
    plan_parser.set_defaults(func=cmd_plan)

    impact_parser = sub.add_parser("impact", help="注入事件并做影响分析")
    _add_common(impact_parser)
    impact_parser.add_argument("--event", choices=["none", "rain", "closure"], default="rain")
    impact_parser.add_argument("--from", dest="start", default="15:00")
    impact_parser.add_argument("--to", dest="end", default=None)
    impact_parser.add_argument("--node", action="append", default=[])
    impact_parser.set_defaults(func=cmd_impact)

    repair_parser = sub.add_parser("repair", help="影响分析 + 最小修复 + 通知预览")
    _add_common(repair_parser)
    repair_parser.add_argument("--event", choices=["none", "rain", "closure"], default="rain")
    repair_parser.add_argument("--from", dest="start", default="15:00")
    repair_parser.add_argument("--to", dest="end", default=None)
    repair_parser.add_argument("--node", action="append", default=[])
    repair_parser.set_defaults(func=cmd_repair)

    demo_parser = sub.add_parser("demo", help="跑一遍 90 秒演示剧本")
    _add_common(demo_parser)
    demo_parser.set_defaults(func=cmd_demo)

    check_parser = sub.add_parser("check", help="校验数据文件，可接 CI")
    _add_common(check_parser)
    check_parser.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
