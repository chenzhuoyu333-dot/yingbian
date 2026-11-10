"""
四个用例自动对答案。

跑法：python -m src.check
全绿 = W1 任务完成，可以开始接接口。
"""
from .models import STATE, load_plan
from .propagate import propagate
from .repair import repair_all
from .cases import CASES

passed = 0
failed = 0
fail_detail = []


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        fail_detail.append("  x %s%s" % (name, ("  (%s)" % detail) if detail else ""))


for case_id, c in CASES.items():
    plan = load_plan()
    if c.get("mutate"):
        plan = c["mutate"](plan)

    prop = propagate(plan, c["event"])
    res = repair_all(plan, prop)

    print("\n--- %s · %s ---" % (case_id, c["title"]))
    print("  影响 %d/%d   ratio=%.4f   path=%s" % (
        prop["affected"], prop["total"], prop["ratio"], prop["path"]))
    for n in plan["nodes"]:
        st = prop["states"][n["id"]]
        if st == STATE["OK"]:
            continue
        sh = prop["shifts"][n["id"]]
        print("    %-18s %-9s %s" % (n["id"], st, ("后移 %d 分" % sh) if sh else ""))

    exp = c["expect"]

    # ── 状态断言 ──
    for nid, want in (exp.get("states") or {}).items():
        ok("%s %s 应为 %s" % (case_id, nid, want),
           prop["states"][nid] == want, "实际 %s" % prop["states"][nid])

    if "ok_count" in exp:
        n_ok = sum(1 for x in plan["nodes"] if prop["states"][x["id"]] == STATE["OK"])
        ok("%s ok 数应为 %d" % (case_id, exp["ok_count"]), n_ok == exp["ok_count"], "实际 %d" % n_ok)

    if "ratio" in exp:
        ok("%s ratio 应约 %.4f" % (case_id, exp["ratio"]),
           abs(prop["ratio"] - exp["ratio"]) < 0.001, "实际 %.4f" % prop["ratio"])

    if "path" in exp:
        ok("%s path 应为 %s" % (case_id, exp["path"]), prop["path"] == exp["path"], "实际 %s" % prop["path"])

    if "conflicts" in exp:
        got = sorted(k for k, v in prop["states"].items() if v == STATE["CONFLICT"])
        ok("%s conflict 集合" % case_id, got == sorted(exp["conflicts"]), "实际 %s" % ",".join(got))

    # ── 修复断言 ──
    er = c.get("expect_repair") or {}
    if er:
        if er.get("status") == "blocked":
            ok("%s 修复应被阻挡" % case_id, res["status"] == "blocked", "实际 %s" % res["status"])
            if er.get("blocked_node"):
                ok("%s 阻挡节点应为 %s" % (case_id, er["blocked_node"]),
                   res["blockedNode"] == er["blocked_node"], "实际 %s" % res["blockedNode"])
            print("  修复：BLOCKED @ %s   %s" % (res["blockedNode"], res.get("message") or ""))
        else:
            b = next(s for s in res["schemes"] if s["schemeId"] == "B")
            ok("%s 修复应成功" % case_id, b["status"] == "ok", "实际 %s" % b["status"])
            if "changed_count" in er:
                ok("%s 改动数应为 %d" % (case_id, er["changed_count"]),
                   b["changedCount"] == er["changed_count"], "实际 %d" % b["changedCount"])
            if "keep_rate" in er:
                ok("%s 保留率应为 %.2f" % (case_id, er["keep_rate"]),
                   abs(b["keepRate"] - er["keep_rate"]) < 0.01, "实际 %.2f" % b["keepRate"])
            for nid, act in (er.get("actions") or {}).items():
                got = next((a for a in b["actions"] if a["nodeId"] == nid), None)
                ok("%s %s 应为 %s" % (case_id, nid, act),
                   got and got["action"] == act, "实际 %s" % (got["action"] if got else "无动作"))
            print("  修复(B)：改 %d 处 · 保留率 %d%% · 牺牲：%s" % (
                b["changedCount"], round(b["keepRate"] * 100), b["sacrifice"]))

print("\n" + "=" * 52)
if failed == 0:
    print("全部通过：%d 项断言" % passed)
    print("A 的 W1 完成 —— 可以开始接接口了。")
else:
    print("通过 %d 项，失败 %d 项：" % (passed, failed))
    for d in fail_detail:
        print(d)
    raise SystemExit(1)
print("=" * 52)
