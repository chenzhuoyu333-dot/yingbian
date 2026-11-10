"""
算法二：最小修复

输入：图 + 传播结果 + 一套权重
输出：动作列表 / 改动数 / 保留率 / 阻挡节点

三条硬要求：
  1. 只要出现 conflict（锁定的节点受影响了），立刻停下问用户，不许自己改
  2. 每应用一个动作就重跑 propagate
  3. 每个候选动作都要"试跑一遍"，会产生新 conflict 的直接否决

跑法：python -m src.repair T3
"""
import copy

from .models import STATE, REASON, to_min, to_hhmm
from .rules import RULES, SCHEME_LABEL
from .propagate import propagate


def apply_action(plan, node_id, act):
    """把一个动作真正作用到图上"""
    idx = next((i for i, n in enumerate(plan["nodes"]) if n["id"] == node_id), -1)
    if idx < 0:
        return False
    n = plan["nodes"][idx]

    if act["action"] == "shift":
        d = act["payload"]["minutes"]
        n["start"] = to_hhmm(to_min(n["start"]) + d)
        n["end"] = to_hhmm(to_min(n["end"]) + d)
        return True

    if act["action"] == "replace":
        alt = next((a for a in n.get("alternatives") or [] if a["id"] == act["payload"]["alternativeId"]), None)
        if not alt:
            return False
        n["title"] = alt["title"]
        n["indoor"] = alt["indoor"]
        n["start"] = alt["start"]
        n["end"] = alt["end"]
        n["source"] = {
            "kind": "alternative",
            "note": "换备选：%s" % alt["title"],
            "at": n["source"]["at"],
        }
        return True

    if act["action"] == "drop":
        plan["nodes"].pop(idx)
        plan["edges"] = [e for e in plan["edges"] if e["from"] != node_id and e["to"] != node_id]
        return True

    return False


def candidates_for(plan, node, prop, w, evt):
    """为一个受影响的节点生成候选动作，并过滤掉"试跑会炸"的"""
    raw = []
    reason = prop["reasons"].get(node["id"])

    # (1) 后移
    if reason != REASON["CANCEL"]:
        minutes = prop["shifts"].get(node["id"], 0)
        if evt.get("type") == "rain":
            rain_end = to_min(evt["to"])
            minutes = max(minutes, rain_end - to_min(node["start"]))
        if minutes > 0:
            new_start = to_min(node["start"]) + minutes
            latest = node.get("windowLatest")
            fits = (not latest) or (new_start <= to_min(latest))
            if fits:
                raw.append({
                    "action": "shift",
                    "payload": {"minutes": minutes},
                    "cost": minutes * w["shift"],
                })

    # (2) 换备选
    for alt in node.get("alternatives") or []:
        raw.append({
            "action": "replace",
            "payload": {"alternativeId": alt["id"]},
            "cost": w["replace"] + (alt.get("travelMin") or 0) * 0.5,
            "_alt": alt,
        })

    # (3) 跳过（锁定的不许删）
    if not node.get("confirmed"):
        raw.append({"action": "drop", "payload": {}, "cost": w["drop"]})

    # (4) 试跑：只要会产生新的 conflict，就否决
    def survives(c):
        trial = copy.deepcopy(plan)
        apply_action(trial, node["id"], c)
        p2 = propagate(trial, evt)
        return STATE["CONFLICT"] not in p2["states"].values()

    return [c for c in raw if survives(c)]


def describe_action(node, act, prop):
    why = "会淋雨" if prop["reasons"].get(node["id"]) == REASON["RAIN"] else ""
    if act["action"] == "shift":
        return "%s，后移 %d 分钟" % (why, act["payload"]["minutes"])
    if act["action"] == "replace":
        return "%s，换成备选「%s」" % (why, (act.get("_alt") or {}).get("title", ""))
    return "%s，跳过这一站" % why


def describe_sacrifice(actions):
    if not actions:
        return "不用改"
    drops = [a for a in actions if a["action"] == "drop"]
    shifts = [a for a in actions if a["action"] == "shift"]
    reps = [a for a in actions if a["action"] == "replace"]
    parts = []
    if drops:
        parts.append("放弃 %d 个点" % len(drops))
    if reps:
        parts.append("换 %d 个备选" % len(reps))
    if shifts:
        parts.append("推迟 %d 处" % len(shifts))
    return "、".join(parts) or "不用改"


def repair_with(plan, prop, scheme_id):
    """用一套权重跑一次修复"""
    w = RULES["weights"][scheme_id]
    work = copy.deepcopy(plan)
    actions = []
    handled = set()          # 同一个节点不重复处理
    evt = dict(prop["event"])  # 事件可以被"消费"
    cur = prop

    for _ in range(RULES["max_repair_rounds"]):
        bad = [
            n for n in work["nodes"]
            if cur["states"].get(n["id"]) != STATE["OK"] and n["id"] not in handled
        ]
        bad.sort(key=lambda n: to_min(n["start"]))
        if not bad:
            break

        node = bad[0]
        cands = sorted(candidates_for(work, node, cur, w, evt), key=lambda c: c["cost"])

        if not cands:
            return {
                "schemeId": scheme_id,
                "label": SCHEME_LABEL[scheme_id],
                "status": "blocked",
                "blockedNode": node["id"],
                "actions": actions,
                "changedCount": len(actions),
                "keepRate": 1.0,
                "sacrifice": "这个节点没有可用的改法",
            }

        best = cands[0]
        apply_action(work, node["id"], best)
        handled.add(node["id"])

        # 取消/关门类事件：处理完就算消费掉，否则替换后的节点会被同一个事件再次打回
        if evt.get("type") in ("cancel", "closed") and evt.get("nodeId") == node["id"]:
            evt = {"type": "none"}

        actions.append({
            "nodeId": node["id"],
            "action": best["action"],
            "payload": best["payload"],
            "cost": round(best["cost"], 1),
            "reason": describe_action(node, best, cur),
        })

        cur = propagate(work, evt)

    before_confirmed = [n["id"] for n in plan["nodes"] if n.get("confirmed")]
    kept = []
    for nid in before_confirmed:
        still = next((n for n in work["nodes"] if n["id"] == nid), None)
        if still and cur["states"].get(nid) == STATE["OK"]:
            kept.append(nid)

    keep_rate = (len(kept) / len(before_confirmed)) if before_confirmed else 1.0

    return {
        "schemeId": scheme_id,
        "label": SCHEME_LABEL[scheme_id],
        "status": "blocked" if STATE["CONFLICT"] in cur["states"].values() else "ok",
        "actions": actions,
        "changedCount": len(actions),
        "keepRate": round(keep_rate, 2),
        "sacrifice": describe_sacrifice(actions),
    }


def repair_all(plan, prop):
    """三个方案一起算"""
    conflicts = [n for n in plan["nodes"] if prop["states"].get(n["id"]) == STATE["CONFLICT"]]

    # 锁定冲突：一律先停下问人
    if conflicts:
        first = conflicts[0]
        return {
            "status": "blocked",
            "blockedNode": first["id"],
            "message": "「%s」是你锁定的，但它会受影响。要解锁吗？" % first["title"],
            "schemes": [],
        }

    schemes = [repair_with(plan, prop, s) for s in ("A", "B", "C")]
    return {"status": "ok", "blockedNode": None, "message": "", "schemes": schemes}


# ────────────────────────────────────────────────
# 命令行入口：python -m src.repair T3
# ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from .cases import CASES
    from .models import load_plan

    case_id = (sys.argv[1] if len(sys.argv) > 1 else "T3").upper()
    c = CASES.get(case_id)
    if not c:
        print("没有这个用例：%s（可选：%s）" % (case_id, ", ".join(CASES)))
        sys.exit(1)

    plan = load_plan()
    if c.get("mutate"):
        plan = c["mutate"](plan)

    prop = propagate(plan, c["event"])
    res = repair_all(plan, prop)

    print("\n=== %s · %s ===" % (case_id, c["title"]))
    if res["status"] == "blocked":
        print("\n  [BLOCKED] %s" % res["message"])
        print("  阻挡节点：%s\n" % res["blockedNode"])
    else:
        for s in res["schemes"]:
            print("\n  【%s %s】 改 %d 处 · 保留率 %d%%" % (
                s["schemeId"], s["label"], s["changedCount"], round(s["keepRate"] * 100)))
            for a in s["actions"]:
                print("    - %s: %s  (%s)" % (a["nodeId"], a["action"], a["reason"]))
            print("    牺牲：%s" % s["sacrifice"])
        print("")
