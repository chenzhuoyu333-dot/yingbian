# 应变 · W1 算法 + W2 接口 / Android 客户端

按 `W1施工图` 实现的 schema、四态传播、`shift/replace/drop` 修复，加上 `W2施工图` 的 6 个接口。
天气已接和风（`QWEATHER_KEY`，没配就返回明确标注的演示数据）。
Android 端在 `android/`，分 emulator（离线 mock）和 lan（连后端）两个包；
地址可在 App 的「连接设置」里改并测试连接，不用为换 IP 重新打包。

**唯一数据源是 `data/plan-saturday.json`**；`archive/w2-reference/` 是组员的独立参考实现，
数据与主实现不同，不参与构建、测试和演示，详见 `archive/README.md`。

## 30 秒跑起来

不会敲命令：直接双击根目录的 `check-W1.bat`，它会跑完 23 个单元测试和 7 项接口巡检，
最后一行显示「7/7 项通过」就是 W1 验收 OK。

```powershell
python -m pip install -r requirements.txt
python -m yingbian check
python -m yingbian case T1 --repair --scheme B
```

## W1 怎么验收

W1 是服务端的算法，没有自己的界面。验收分两层：

| 层 | 看什么 | 命令 / 入口 |
|---|---|---|
| 规则层 | T1–T4 四个用例的期望状态、方案动作、保留率 | `python -m yingbian case T1 --repair --scheme B` |
| 接口层 | 6 个接口串起来能否读计划→算影响→出方案→应用→撤销 | `python scripts\acceptance_w1.py --serve` |
| 界面层 | 手机上看得见的影响面板、方案对比、通知、待办 | `android/` 安装后点「模拟下雨」 |

接口巡检会自己起一个临时服务（默认 8011 端口），跑完自动关闭，不需要另开窗口；
也可以先 `python -m uvicorn server.app:app --port 8000`，再
`python scripts\acceptance_w1.py --base http://127.0.0.1:8000` 对着常驻服务跑。

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

当前 23 个测试：schema、T1–T4、6 个接口、天气（演示/真实/失败降级）、自测页与重置。

## Android 客户端

`android/` 是 Compose 单 Activity 客户端，已实现 W2 的 S1–S5：
计划图、三方案对比、影响面板、通知预览、待办清单，以及空/加载/失败/阻断/离线状态。

```powershell
cd android
.\make-apks.ps1
# 产物：dist/yingbian-emulator.apk（离线演示）、dist/yingbian-lan.apk（真机联调）
```

`make-apks.ps1` 打包时会把本机局域网 IP 写进 LAN 包的默认地址；详细打开方式、设置页用法和演示路径见 `android/README.md`。

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
  候选先试跑：会制造新 conflict 的直接淘汰
  剩下的选最小代价，改完立刻重跑 propagate
```

所有阈值和权重都在 `yingbian/rules.py`，改参数不用翻算法。

| 方案 | shift | replace | drop | 性格 |
|---|---|---|---|---|
| A 保时间 | 0.2 | 100 | 100 | 宁可挪，也不换点 |
| B 保体验 | 1 | 50 | 100 | 优先换备选，尽量不删 |
| C 保少改动 | 3 | 60 | 200 | 能不动就不动 |

返回：`actions + keepRate + sacrifice + changedCount`。

## 接口

```powershell
python -m server.app
# 或 uvicorn server.app:app --host 0.0.0.0 --port 8000
```

启动后会打印本机、自测页和局域网地址；手机真机联调时用局域网那条。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | 网页自测台，点按钮看每个接口的返回 |
| GET | `/api/plan/{planId}` | 取计划 |
| POST | `/api/plan/{planId}/event` | 四态、shifts、ratio、path |
| POST | `/api/plan/{planId}/repair` | 三方案 / blocked |
| POST | `/api/plan/{planId}/apply` | 应用方案，版本 +1 |
| POST | `/api/plan/{planId}/undo` | 撤销 |
| GET | `/api/weather?lat=&lng=` | 天气（真实优先，失败降级并标注） |
| POST | `/api/reset` | 复位到版本 1，演示前清场用 |

演示 T4 时先用 `POST /api/debug/lock` 锁日落点，再发降雨。

## 天气

```powershell
$env:QWEATHER_KEY = "你的和风天气 Key"
python -m server.app
```

没配 Key 或调用失败时，返回 `source: "演示数据（原因）"`、`isDemo: true`、`note` 说明原因，
不会把演示数据伪装成真实预报。真实数据返回 `source: "和风天气"`、`isDemo: false`。

## Android mock

```
fixtures/plan-saturday.json     # GET /plan
fixtures/event-rain-T1.json     # T1 四态
fixtures/repair-T1.json         # 三方案 + actions
fixtures/event-cancel-T3.json   # T3 餐厅取消
fixtures/repair-T3.json         # T3 只改 1 处
fixtures/blocked-T4.json        # blocked 弹窗
fixtures/weather.json           # 标注 isDemo 的演示天气
```

改完算法执行 `python scripts/make_fixtures.py` 重新生成；它会同时写入
`fixtures/` 和 `android/app/src/main/assets/fixtures/`，两边不会再对不上。

## 两处口径说明

施工图内部有两处矛盾，代码按“让 T1–T4 全部通过”落地：

1. T2 写日落点 `windowLatest 16:40`，但集合晚到 60 分钟后新开始是 16:30，`16:30 > 16:40` 不成立；为命中 T2 的 `invalid`，fixture 把日落点设为 **16:00**。
2. §2.2 写“概率 ≥0.6 且完全覆盖 → invalid”，但 T1 的降雨完全覆盖日落点却期望 `at_risk`；第一版按 T1 实现为 `at_risk`，`invalid` 只来自 cancel/closed 和窗口超时。

要改回原文，只改 `propagate.py` 的 `_direct_hit` 和 fixture 的 `windowLatest`，T4 阻断不受影响。

## W3：能演（缓冲 / 天气 / 自检 / 性能）

### 1. 两份演示计划

```
data/plan-saturday.json    p_sat_guzhen        零缓冲：用来证明"一延误就全崩"
data/plan-slack.json       p_sat_guzhen_slack  有缓冲：用来演示"缓冲吸收延误"
```

启动时自动加载 `data/plan-*.json`，用 `planId` 路径参数选择。
两者节点 id 相同，App 只需换 base 里的计划 id。

**为什么需要两份**：零缓冲的计划里，任何延误都会顶穿整条链，导致
最小修复永远没得选、三个方案算出同一个结果 —— 屏 2 演出来会被问"这不是重复吗"。

### 2. 缓冲现在真的会吸收延误

`propagate.py` 的边传播改成先吃缓冲：

```python
slack  = max(0, (dst.start - src.end) - edge.min_gap)   # 这条边的天然余量
needed = max(0, shifts[src] - slack)                     # 吸不完的部分才顶到下游
```

实测对比（集合晚 30 分钟）：

| 计划 | 影响 | path |
|---|---|---|
| 零缓冲 `p_sat_guzhen` | 12/12 | global |
| 宽松版 `p_sat_guzhen_slack` | 3/12 | local |

### 3. 天气：和风 → 高德 → 演示数据

```powershell
# 项目根目录建 .env（已被 .gitignore 排除，永不提交）
AMAP_KEY=你的高德Web服务Key
QWEATHER_HOST=xxxxxxxx.re.qweatherapi.com   # 可选，和风专属域名
QWEATHER_KEY=你的和风Key
```

- 和风有逐小时降水概率 `pop`，最准；但**必须用账号专属 Host**，公共域名 `devapi.qweather.com` 已停用（老 Key 会 403）
- 高德不需要专属域名，但没有概率，只有天气文字 → 按文字保守估计，依据写进 `basis`
- 都拿不到 → `source: "演示数据（原因）"`、`isDemo: true`、`note` 说明原因，**绝不伪装**

`GET /api/config` 可以查配置状态（只报布尔值，不返回密钥）。

### 4. 两条命令收口 W3

```powershell
python scripts/w3_check.py --base http://127.0.0.1:8000   # 27 项后端自检
python scripts/bench.py                                   # 性能表，直接贴文档
```

`w3_check.py` 覆盖：服务可用、两份计划、全链路（取/事件/方案/应用/撤销）、
锁定冲突必须 blocked、天气真伪与标注、缓冲是否生效。

`bench.py` 实测（12 节点，100 次）：

| 场景 | 影响 | 传播 P50 | 修复 P95 |
|---|---|---|---|
| 降雨 15:00–17:00 | 2/12 | 0.02 ms | 0.87 ms |
| 集合晚 60 分钟 | 12/12 | 0.04 ms | 0.39 ms |
| 午餐取消 | 1/12 | 0.02 ms | 0.75 ms |

一次完整演示约 18 次请求。

### 5. App 侧还差什么

后端已就绪。App 侧的 W3 事项：**真机连一次真实后端 → 录 90 秒 → 彩排**。
五态（空/加载/失败/阻断/离线）和离线缓存已在 Compose 客户端里实现。

## 目录

```
yingbian-core/
├─ data/
│  ├─ plan-saturday.json          标准计划（零缓冲）
│  └─ plan-slack.json             宽松版（有缓冲，演示用）
├─ fixtures/                      Android 离线 mock
├─ yingbian/
│  ├─ models.py                   schema 与时间工具
│  ├─ env.py                      .env 读取（不覆盖已有环境变量）
│  ├─ rules.py                    阈值与三套方案权重
│  ├─ propagate.py                四态传播（含缓冲吸收）
│  ├─ repair.py                   最小修复
│  ├─ weather.py                  和风 → 高德 → 演示数据 三级链
│  ├─ notify.py                   通知文案
│  └─ cli.py                      python -m yingbian ...
├─ server/app.py                  六接口 + 自测页 + 多计划加载
├─ scripts/
│  ├─ make_fixtures.py            从算法重新生成 fixtures
│  ├─ acceptance_w1.py            W1 接口巡检
│  ├─ w3_check.py                 W3 收口自检（27 项）
│  └─ bench.py                    性能基准
├─ tests/                         27 个 unittest
├─ android/                       Compose 客户端
├─ archive/w2-reference/          组员独立参考实现（不参与构建）
├─ check-W1.bat                   双击验收
└─ .github/workflows/ci.yml       push 自动跑测试
```

## 下一步

W3 剩余（全部是 App 侧）：真机连一次真实后端 → 五态走查 → 录 90 秒视频 → 彩排。
W4：性能表定稿、原型图、分工表、匿名自查、打包交件。

