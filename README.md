# 应变 · W1 算法 + W2 接口 / Android 客户端

按 `W1施工图` 重写的 schema、四态传播、`shift/replace/drop` 修复，加上 `W2施工图` 的 6 个接口。
Android 端在 `android/`，默认吃 `fixtures/` 里的 mock，不用等后端。

## 30 秒跑起来

```powershell
python -m pip install -r requirements.txt
python -m yingbian check
python -m yingbian case T1 --repair --scheme B
```

## 四个验收用例

```powershell
python -m yingbian case T1
python -m yingbian case T2
python -m yingbian case T3
python -m yingbian case T4
python -m yingbian case T1 --repair --scheme B
```

| 用例 | 输入 | 期望 | 当前结果 |
|---|---|---|---|
| T1 | 降雨 15:00–17:00，概率 70% | 2/12，局部修复，改 2 处，保留率 100% | ✅ |
| T2 | 集合点延后 60 分钟 | 12/12，`blocked` 在集合点 | ✅ |
| T3 | 取消午餐 | 1/12，只改 1 处（换江畔小厨） | ✅ |
| T4 | 锁定日落点 + 降雨 | 日落点 `conflict`，`blocked` | ✅ |

```powershell
python -m unittest discover -s tests -v
```

当前 17 个测试：schema、T1–T4、6 个接口。

## Android 客户端

`android/` 是 Compose 单 Activity 客户端，已实现 W2 的 S1–S5：
计划图、三方案对比、影响面板、通知预览、待办清单，以及空/加载/失败/阻断/离线状态。

```powershell
cd android
.\gradlew.bat :app:assembleDebug
```

详细打开方式、真机联调和演示路径见 `android/README.md`。

## 数据模型

`data/plan-saturday.json` 严格按 W1 §1：

```jsonc
{
  "planId": "p_sat_guzhen",
  "title": "周六古镇一日游",
  "date": "2026-11-14",
  "nodes": [{ "id": "n_sunset", "type": "place", "title": "湖边日落点",
    "start": "15:30", "end": "16:40", "indoor": false, "confirmed": false,
    "windowLatest": "16:00", "confidence": "high",
    "alternatives": [{ "id": "a_museum", "title": "市美术馆", "indoor": true,
      "start": "15:30", "end": "16:40", "travelMin": 20, "sacrifice": "看不到日落" }],
    "source": { "kind": "consensus", "note": "3 篇攻略推荐", "at": "2026-11-13" } }],
  "edges": [{ "from": "n_river", "to": "n_sunset", "type": "precedes", "minGapMin": 30 }]
}
```

约定：时间只写 `HH:mm`；`confirmed` 就是锁定；备选写在节点里；缓冲 = 实际间隙 − `minGapMin`。

## 四态与传播

| 状态 | 含义 | 系统动作 |
|---|---|---|
| `ok` | 正常 | — |
| `at_risk` | 受影响，能改 | 自动修复 |
| `invalid` | 失效，必须改 | 自动修复 |
| `conflict` | 锁定节点被影响 | 停下问用户 |

`yingbian/propagate.py` 的规则：

1. `rain`：室外 + 时间重叠 + 概率 ≥0.3 → `at_risk`。
2. `cancel` / `closed` → `invalid`。
3. `delay` → 该节点 `shift = minutes`。
4. 下游后移：`needed = max(0, 上游结束 + 上游 shift + minGapMin − 下游开始)`。
5. `新开始 > windowLatest` → `invalid`。
6. `confirmed` 收到 `at_risk` → `conflict`；已经 `invalid` 的保持 `invalid`。
7. `ratio`：≤30% 局部、30–60% 投票、>60% 全体。

## 修复

不是 CP-SAT，是 W1 §3 的规则修复，保证动作可解释、可复现：

```text
先扫 conflict → 有就 blocked，不修
按时间顺序处理非 ok 节点：
  shift   = 后移分钟 × w_shift
  replace = w_replace + travelMin × 0.5
  drop    = w_drop
  选最小代价，改完立刻重跑 propagate
```

| 方案 | shift | replace | drop | 性格 |
|---|---|---|---|---|
| A 保时间 | 0.2 | 100 | 100 | 宁可挪，也不换点 |
| B 保体验 | 1 | 50 | 100 | 优先换备选，尽量不删 |
| C 保少改动 | 3 | 60 | 200 | 能不动就不动 |

返回：`actions + keepRate + sacrifice + changedCount`。

## 6 个接口

```powershell
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/plan/{planId}` | 取计划 |
| POST | `/api/plan/{planId}/event` | 四态、shifts、ratio、path |
| POST | `/api/plan/{planId}/repair` | 三方案 / blocked |
| POST | `/api/plan/{planId}/apply` | 应用方案，版本 +1 |
| POST | `/api/plan/{planId}/undo` | 撤销 |
| GET | `/api/weather?lat=&lng=` | 天气占位（W3 接和风） |

演示 T4 时先用 `POST /api/debug/lock` 锁日落点，再发降雨。

## Android mock

```
fixtures/plan-saturday.json     # GET /plan
fixtures/event-rain-T1.json     # T1 四态
fixtures/repair-T1.json         # 三方案 + actions
fixtures/blocked-T4.json        # blocked 弹窗
fixtures/weather.json
```

改完算法执行 `python scripts/make_fixtures.py` 重新生成。

## 两处口径说明

施工图内部有两处矛盾，代码按“让 T1–T4 全部通过”落地：

1. T2 写日落点 `windowLatest 16:40`，但集合晚到 60 分钟后新开始是 16:30，`16:30 > 16:40` 不成立；为命中 T2 的 `invalid`，fixture 把日落点设为 **16:00**。
2. §2.2 写“概率 ≥0.6 且完全覆盖 → invalid”，但 T1 的降雨完全覆盖日落点却期望 `at_risk`；第一版按 T1 实现为 `at_risk`，`invalid` 只来自 cancel/closed 和窗口超时。

要改回原文，只改 `propagate.py` 的 `_direct_hit` 和 fixture 的 `windowLatest`，T4 阻断不受影响。

## 目录

```
yingbian-core/
├─ data/plan-saturday.json
├─ fixtures/
├─ yingbian/{models,propagate,repair,notify,cli}.py
├─ server/app.py
├─ scripts/make_fixtures.py
└─ tests/
```

## 下一步

W3：接和风天气、补错误处理与降级；W4：真机打包、崩溃兜底和演示脚本。
