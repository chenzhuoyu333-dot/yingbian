"""性能基准：给 W3 的"程序性能"章节产出真实数字。

跑法（在项目根目录）：
    python scripts/bench.py
    python scripts/bench.py --plan p_sat_guzhen_slack

输出一张可以直接粘进文档的表：
    影响传播 / 最小修复 的 P50、P95 耗时，以及一次演示的典型请求量。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yingbian import Event, load_plan, propagate, repair  # noqa: E402

SCENARIOS = {
    '降雨 15:00–17:00': {'type': 'rain', 'from': '15:00', 'to': '17:00', 'prob': 0.7},
    '短时降雨 15:00–15:40': {'type': 'rain', 'from': '15:00', 'to': '15:40', 'prob': 0.6},
    '集合晚 20 分钟': {'type': 'delay', 'nodeId': 'n_meet', 'minutes': 20},
    '集合晚 60 分钟': {'type': 'delay', 'nodeId': 'n_meet', 'minutes': 60},
    '午餐取消': {'type': 'cancel', 'nodeId': 'n_lunch'},
}


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[idx]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', default='data/plan-saturday.json', help='计划文件路径')
    ap.add_argument('--rounds', type=int, default=200, help='每个场景重复次数')
    args = ap.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    plan = load_plan(plan_path)

    print()
    print('=' * 74)
    print(f'性能基准 · {plan.title}（{plan_path.name}）')
    print(f'节点数 {len(plan.nodes)}   边数 {len(plan.edges)}   锁定 {len(plan.confirmed_nodes())}')
    print(f'每个场景重复 {args.rounds} 次')
    print('=' * 74)
    header = f'{"场景":<22}{"影响":<8}{"传播 P50":>10}{"传播 P95":>10}{"修复 P50":>10}{"修复 P95":>10}'
    print(header)
    print('-' * 74)

    for name, raw in SCENARIOS.items():
        event = Event.from_dict(raw)

        prop_times: list[float] = []
        for _ in range(args.rounds):
            t0 = time.perf_counter()
            report = propagate(plan, event)
            prop_times.append((time.perf_counter() - t0) * 1000)

        repair_times: list[float] = []
        for _ in range(args.rounds):
            t0 = time.perf_counter()
            repair(plan, event, 'B')
            repair_times.append((time.perf_counter() - t0) * 1000)

        mark = f'{report.affected_count}/{report.total_count}'
        print(
            f'{name:<22}{mark:<8}'
            f'{statistics.median(prop_times):>9.2f}ms'
            f'{percentile(prop_times, 95):>9.2f}ms'
            f'{statistics.median(repair_times):>9.2f}ms'
            f'{percentile(repair_times, 95):>9.2f}ms'
        )

    print('-' * 74)
    print('一次完整演示的请求量（估算）：')
    print('  取计划 1 + 发事件 1 + 求方案 1 + 应用 1 + 撤销 1 + 天气 1  = 6')
    print('  加上每个节点检查点 1 次 × 12 节点                         = 12')
    print('  合计约 18 次 / 场演示')
    print()
    print('把上面这张表贴进《测试文档》的"性能分析"章节即可。')
    print('=' * 74)
    print()


if __name__ == '__main__':
    main()
