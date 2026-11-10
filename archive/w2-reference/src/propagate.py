"""
算法一：影响传播

输入：一张计划图 + 一个事件
输出：每个节点的状态 / 需要后移多少分钟 / 影响比重 / 该走哪条路

核心一句话：依赖只通过时间来传播。
  上游被顶后移 -> 下游最早能开始的时刻被推后 -> 下游不够时间就出问题。

跑法：python -m src.propagate T1
"""
from .models import STATE, REASON, to_min, overlaps, index_by_id, worse
from .rules import RULES


def propagate(plan, event):
    by_id = index_by_id(plan)

    states = {n["id"]: STATE["OK"] for n in plan["nodes"]}
    shifts = {n["id"]: 0 for n in plan["nodes"]}
    reasons = {n["id"]: None for n in plan["nodes"]}

    def put(node, level, reason):
        """
        写入状态（只升不降）。

        关键规则：已锁定的节点一旦受影响，就升级为 conflict，交给用户决定。
        唯一例外：取消/关门这类"节点已经不存在"的事件，允许用备选顶上
                 —— 因为原节点没了，换等价备选正好保住了用户的安排。
        """
        final = level
        if node.get("confirmed"):
            cancel_like = reason == REASON["CANCEL"] and len(node.get("alternatives") or []) > 0
            if not cancel_like:
                final = STATE["CONFLICT"]
        nxt = worse(states[node["id"]], final)
        if nxt != states[node["id"]]:
            states[node["id"]] = nxt
            reasons[node["id"]] = reason
            return True
        return False

    # ── 第一步：直接命中 ──────────────────────────
    for n in plan["nodes"]:
        t = event.get("type")

        if t == "rain":
            prob = event.get("prob", 0)
            if prob < RULES["rain_ignore_prob"]:
                continue
            if n.get("indoor"):
                continue
            ns, ne = to_min(n["start"]), to_min(n["end"])
            rs, re_ = to_min(event["from"]), to_min(event["to"])
            if not overlaps(ns, ne, rs, re_):
                continue
            # 天气只判"有风险"，不判"失效"——预报不是既定事实
            put(n, STATE["AT_RISK"], REASON["RAIN"])
            continue

        if t in ("delay", "memberLate"):
            if n["id"] != event.get("nodeId"):
                continue
            shifts[n["id"]] = event.get("minutes", 0)
            put(n, STATE["AT_RISK"], REASON["DELAY"])
            continue

        if t in ("cancel", "closed"):
            if n["id"] != event.get("nodeId"):
                continue
            put(n, STATE["INVALID"], REASON["CANCEL"])
            continue

    # ── 第二步：沿依赖向后传播，直到不再变化 ────────
    edges = sorted(plan["edges"], key=lambda e: to_min(by_id[e["from"]]["start"]))

    changed = True
    guard = 0
    while changed and guard < 50:
        changed = False
        guard += 1
        for e in edges:
            s = by_id.get(e["from"])
            d = by_id.get(e["to"])
            if not s or not d:
                continue

            # 每条边都要校验，不管上游自己是"没问题"。
            # 反例：某节点被后移到 17:20 结束，下一站 17:10 开始——上游状态是 ok，
            #       但这一对已经错位了。所以约束校验不能依赖上游状态。
            src_end = to_min(s["end"]) + shifts.get(s["id"], 0)
            earliest = src_end + e.get("minGapMin", 0)
            needed = max(0, earliest - to_min(d["start"]))
            if needed <= shifts.get(d["id"], 0):
                continue

            shifts[d["id"]] = needed
            changed = True

            new_start = to_min(d["start"]) + needed
            level = STATE["AT_RISK"]
            latest = d.get("windowLatest")
            if latest and new_start > to_min(latest):
                level = STATE["INVALID"]

            put(d, level, reasons.get(s["id"]) or REASON["DELAY"])

    # ── 第三步：影响比重 -> 走哪条路 ────────────────
    total = len(plan["nodes"])
    affected = sum(1 for s in states.values() if s != STATE["OK"])
    ratio = (affected / total) if total else 0.0
    if ratio <= RULES["ratio_local_max"]:
        path = "local"
    elif ratio <= RULES["ratio_vote_max"]:
        path = "vote"
    else:
        path = "global"

    return {
        "states": states,
        "shifts": shifts,
        "reasons": reasons,
        "ratio": ratio,
        "path": path,
        "total": total,
        "affected": affected,
        "event": event,
    }


# ────────────────────────────────────────────────
# 命令行入口：python -m src.propagate T1
# ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from .cases import CASES
    from .models import load_plan

    case_id = sys.argv[1] if len(sys.argv) > 1 else "T1"
    c = CASES.get(case_id.upper())
    if not c:
        print("没有这个用例：%s（可选：%s）" % (case_id, ", ".join(CASES)))
        sys.exit(1)

    plan = load_plan()
    if c.get("mutate"):
        plan = c["mutate"](plan)

    r = propagate(plan, c["event"])

    print("\n=== %s · %s ===" % (case_id.upper(), c["title"]))
    print("影响 %d/%d 个节点   ratio=%.4f   路径=%s\n" % (r["affected"], r["total"], r["ratio"], r["path"]))
    for n in plan["nodes"]:
        st = r["states"][n["id"]]
        if st == STATE["OK"]:
            continue
        sh = r["shifts"][n["id"]]
        print("  %-18s %-9s %s" % (n["id"], st, ("后移 %d 分" % sh) if sh else ""))
    ok_count = sum(1 for n in plan["nodes"] if r["states"][n["id"]] == STATE["OK"])
    print("\n  ok: %d 个" % ok_count)
