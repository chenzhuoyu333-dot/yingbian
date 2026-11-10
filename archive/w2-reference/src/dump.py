"""
第 1 步：证明"环境通了"。

跑法：python -m src.dump
期望：nodes: 12 / edges: 11 / confirmed: 5
顺便把"缓冲"算出来 —— 这就是"计划有多脆弱"的来源。
"""
from .models import load_plan, to_min

LINE = "=" * 52

plan = load_plan()

print(LINE)
print("%s   %s" % (plan["title"], plan["date"]))
print(LINE)
print("nodes:", len(plan["nodes"]))
print("edges:", len(plan["edges"]))
print("confirmed:", sum(1 for n in plan["nodes"] if n.get("confirmed")))
print("-" * 52)

for n in plan["nodes"]:
    lock = "[LOCK]" if n.get("confirmed") else "      "
    latest = ("  最晚 %s" % n["windowLatest"]) if n.get("windowLatest") else ""
    alt = ("  (备选 %d)" % len(n["alternatives"])) if n.get("alternatives") else ""
    print("%s-%s  %s  %s%s%s" % (n["start"], n["end"], lock, n["title"], latest, alt))

print("-" * 52)

by_id = {n["id"]: n for n in plan["nodes"]}

# 只看"需要衔接"的边（minGapMin > 0），这些地方才会产生缓冲
rows = []
for e in plan["edges"]:
    if e.get("minGapMin", 0) <= 0:
        continue
    a, b = by_id.get(e["from"]), by_id.get(e["to"])
    if not a or not b:
        continue
    actual = to_min(b["start"]) - to_min(a["end"])
    rows.append((e, actual, actual - e["minGapMin"]))
rows.sort(key=lambda r: r[2])

print("需要衔接的地方，缓冲有多大：")
for e, actual, buffer in rows:
    flag = "   <-- 卡死" if buffer <= 0 else ""
    print("  %-16s -> %-16s 间隙 %3d 分 / 需要 %3d 分 / 缓冲 %3d 分%s" % (
        e["from"], e["to"], actual, e["minGapMin"], buffer, flag))

tight = sum(1 for r in rows if r[2] <= 0)
print("-" * 52)
if rows and tight == len(rows):
    print("全部 %d 处衔接的缓冲都是 0 —— 这张计划一延误就全崩。" % len(rows))
    print("这不是 bug，这就是我们要解决的问题。")
print(LINE)
print("如果上面 12 / 11 / 5 都对，第 1 步完成。")
