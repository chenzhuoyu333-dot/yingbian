# 应变 · W1 + W2 算法原型

把「计划图 → 变化 → 影响分析 → 最小改动修复 → 通知/动作清单」这条主线先在命令行跑通。

这是《两个月双赛程实施计划》里 **W1（schema + 12 节点剧本 + 影响传播）** 和 **W2（锁定 + 最小修复 + 三方案 + 保留率）** 的可运行实现。界面（W3）和真实天气（W4）还没接，CLI 就是它们的替身。

## 30 秒跑起来

```powershell
python -m pip install -r requirements.txt
python -m yingbian demo
```

没有 OR-Tools 也能跑（自动退回贪心修复）：

```powershell
python -m yingbian repair --no-cpsat --event rain --from 15:00
```

## 能验什么

| 验收项（来自计划表） | 命令 | 当前结果 |
|---|---|---|
| 12 节点「古镇一日游」JSON | `python -m yingbian check` | 12 节点 / 16 条边 / 11 个活动节点 |
| 输入降雨事件，输出三态 | `python -m yingbian impact --event rain --from 15:00` | 1 个 `invalid`、4 个 `at_risk`，影响面 45% |
| 锁定不动 + 只改必要节点 | `python -m yingbian repair --event rain --from 15:00` | 改 2 个节点，锁定项 3/3 未动 |
| 三个方案 | 同上 | A 最小改动 / B 最少打扰 / C 最稳妥 |
| 求解 < 2 秒 | 同上 | 单方案约 15–120 ms |
| 只打扰需要动作的人 | 同上 | 4 人中只打断 2 人 |

关键结果：降雨 15:00 时，`n07 游船` 被判为 `invalid`，系统把它换成室内备选 `n08 桌游`；`n01 集合`、`n04 午餐`、`n10 日落` 三个锁定节点的时间与状态完全不动；通知只发给小A、小B，小C、小D 不被弹窗。

## 命令

```powershell
# 打印计划与基线状态
python -m yingbian plan

# 只做影响分析
python -m yingbian impact --event rain --from 15:00 --to 17:00

# 分析 + 修复 + 通知预览
python -m yingbian repair --event rain --from 15:00 --to 17:00

# 直接封闭某个节点（演示“临时闭店/封路”）
python -m yingbian repair --event closure --node n07

# 90 秒演示剧本
python -m yingbian demo

# 数据自检，适合接 CI
python -m yingbian check

# 给 UI 用的机器可读输出
python -m yingbian repair --json
```

## 数据模型

一个计划就是一个 DAG，数据在 `data/guzhen_day.json`。

**6 类节点**：`place`｜`slot`｜`transit`｜`reservation`｜`person`｜`task`

**5 类边**：`precedes`｜`requires`｜`same_place`｜`shared_with`｜`alternative_to`

只有 `precedes` 和 `requires` 参与时间传播；`alternative_to` 只在修复时作为候选；`same_place` / `shared_with` 只用于通知分组。

节点里最关键的几个字段：

| 字段 | 含义 |
|---|---|
| `start` / `duration` | 计划开始时间与时长（分钟） |
| `window` | **允许开始的窗口**，不是结束窗口 |
| `deadline` | 最晚结束时间（用于日落、晚餐、返程） |
| `locked` | 勾选=锁定；修复时是硬约束，绝不移动 |
| `outdoor` + `weather_risk` | `none` 不受影响；`degrade` 变 `at_risk`；`cancel` 变 `invalid` |
| `active` | `false` 表示备选未启用（如室内桌游） |
| `alt_group` | 同一组内必须恰好启用一个节点 |
| `persons` | 这个节点涉及谁，决定通知集 |

`travel` 是 12×12 的通行时间矩阵。**这张表是算法正确性的地基**：先用高德 ETA 拉真实值，拉不到就手填，不要用直线距离。

## 算法

### 1. 影响传播（`yingbian/propagate.py`）

按拓扑序做一遍 CPM/PERT：

1. 事件直接命中：`closure` 指定节点，或降雨与室外节点的时间区间相交；`cancel` → `invalid`，`degrade` → `at_risk`。
2. 前向计算最早开始：`max(计划开始, max(前驱结束 + 通行时间))`。
3. 超出 `window` / `deadline` → `at_risk`。
4. 上游 `invalid` 或 `at_risk` → 下游 `at_risk`，形成影响链。
5. 影响比重 = 受影响节点数 ÷ 活动节点数：`≤30%` 局部、`30–60%` 投票、`>60%` 全体变更。

复杂度 O(V+E)，12 节点是微秒级；输出同时给 `slack`（窗口剩余量）和关键路径。

### 2. 最小修复（`yingbian/repair.py`）

用 OR-Tools CP-SAT 建模，核心不是“重排”，是**少改**：

- 锁定节点：`start == 原时间`，硬约束，永不放宽。
- 时间边：`start[dst] >= end[src] + travel`，只在两端都启用时生效。
- 备选组：`AddExactlyOne`，同一时间只能选一个活动。
- `changed[n]`：开始时间是否变化；`switched[n]`：启用状态是否变化；两者取或得到 `touched[n]`。
- 通知人数：每个成员一个 `bool`，只要他相关的任一节点被触碰就置 1。
- 目标：`改动数 × 权重 + 通知人数 × 权重 + 迟到 × 权重 + 位移 − 缓冲`。

三组权重就是三个方案：

| 方案 | 偏好 | 本次结果 |
|---|---|---|
| A 最小改动 | 改动权重 100 | 改 2 处，通知 2 人 |
| B 最少打扰 | 通知权重 50 | 与 A 相同（只有一种可行改法） |
| C 最稳妥 | 保留室外风险惩罚 60 | 改 3 处，取消自由活动，通知 4 人 |

求解上限 2 秒；装不了 OR-Tools 时退回贪心：先定备选、再按拓扑序前推，锁定节点仍不动。

### 3. 通知与动作（`yingbian/notify.py`）

把“取消游船 + 启用桌游”合并成一条人能读的变更；按 `persons` 生成打断/知会，再按节点类型生成动作清单（改预约要打电话、改集合点要通知谁）。系统只准备话术，不替人执行。

## 目录

```
yingbian-core/
├─ data/guzhen_day.json      # 12 节点剧本 + 通行时间矩阵
├─ yingbian/
│  ├─ models.py              # schema、校验、拓扑排序
│  ├─ propagate.py           # 三态传播、影响比重、关键路径
│  ├─ repair.py              # CP-SAT 最小修复、三方案、贪心回退
│  ├─ notify.py              # 通知预览、动作清单
│  └─ cli.py                 # 命令行入口
├─ tests/                    # 18 个 unittest
└─ .github/workflows/ci.yml
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

覆盖：基线全绿、降雨三态、影响比重、锁定节点不动、备选切换、三方案差异、贪心回退、锁定节点被事件命中时必须交给人。

## 推到 GitHub

本地仓库已经初始化并提交。先在 GitHub 上新建一个**空仓库**（不要勾选 README / .gitignore），然后：

```powershell
cd "C:\Users\胡诗语\Documents\ChatGPT\DJ\yingbian-core"
git remote add origin https://github.com/<你的用户名>/yingbian-core.git
git branch -M main
git push -u origin main
```

第一次推送会弹出 GitHub 登录窗口。也可以用 SSH：

```powershell
git remote add origin git@github.com:<你的用户名>/yingbian-core.git
git push -u origin main
```

如果建仓库时勾了 README，先执行 `git pull --rebase origin main` 再推。

## 下一步

| 周 | 事情 |
|---|---|
| W3 | Android/Compose 计划图：直接读 `--json` 输出；节点颜色绑 `state`，锁图标绑 `locked` |
| W4 | 接和风天气：把 `Event` 换成真实降雨预报；检查点按 `start - 60min` 触发 |
| W5 | 彩排 90 秒；三个方案里 C 的“多改一处换安全”正好是答辩记忆点 |

W1/W2 到此已经可以验收：**锁定不动、只改必要节点、三方案、<2 秒、通知集正确**，全部有测试和命令行证据。
