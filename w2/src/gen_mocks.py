"""
生成交给 B 的 4 份 mock JSON。

跑法：python -m src.gen_mocks
输出：mock/state-rain.json / repair-3.json / blocked.json / plan-applied.json

作用：B 不需要等接口，拿着这 4 个文件就能开始写界面。
而且这 4 个文件是**从真实算法跑出来的**，字段一定和接口一致。
"""
import copy
import json
import os

from .models import load_plan, ROOT
from .propagate import propagate
from .repair import repair_all, apply_action

OUT_DIR = os.path.join(ROOT, "mock")
RAIN = {"type": "rain", "from": "15:00", "to": "17:00", "prob": 0.7}
CANCEL = {"type": "cancel", "nodeId": "n_lunch"}


def write(name, payload):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ok": True, "data": payload}, f, ensure_ascii=False, indent=2)
    print("  写入 %s" % path)


def main():
    print("生成 mock ...")

    # 1) 下雨 → 三态
    plan = load_plan()
    prop = propagate(plan, RAIN)
    write("state-rain.json", {
        "states": prop["states"],
        "shifts": prop["shifts"],
        "ratio": round(prop["ratio"], 4),
        "path": prop["path"],
        "affectedCount": prop["affected"],
        "totalCount": prop["total"],
    })

    # 2) 三个方案
    res = repair_all(plan, prop)
    write("repair-3.json", res)

    # 3) 锁定冲突（把日落点锁上再下雨）
    plan2 = load_plan()
    for n in plan2["nodes"]:
        if n["id"] == "n_sunset":
            n["confirmed"] = True
    prop2 = propagate(plan2, RAIN)
    write("blocked.json", repair_all(plan2, prop2))

    # 4) 应用方案 B 之后的新 plan
    b = next(s for s in res["schemes"] if s["schemeId"] == "B")
    work = copy.deepcopy(plan)
    for a in b["actions"]:
        apply_action(work, a["nodeId"], a)
    write("plan-applied.json", {"plan": work, "version": 2, "applied": len(b["actions"])})

    # 5) 餐厅取消（给 B 做单个变化的对照组）
    plan3 = load_plan()
    prop3 = propagate(plan3, CANCEL)
    write("state-cancel.json", {
        "states": prop3["states"],
        "shifts": prop3["shifts"],
        "ratio": round(prop3["ratio"], 4),
        "path": prop3["path"],
        "affectedCount": prop3["affected"],
        "totalCount": prop3["total"],
    })

    print("完成。5 份 mock 已就绪。")


if __name__ == "__main__":
    main()
