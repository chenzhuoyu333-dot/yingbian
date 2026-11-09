# 应变 · Python 版

零依赖，**只需要 Python 3.10+，不需要 pip install 任何东西**（全用标准库）。

---

## 三分钟跑起来

### 1. 确认 Python

cmd 里执行：

```
python --version
```

看到 `Python 3.10.x` 或更高就行。没有就去 https://www.python.org 装，**安装时务必勾选 Add Python to PATH**。

### 2. 打开这个文件夹

```
C:\Users\Olivia\Desktop\yingbian
```

VS Code → 文件 → 打开文件夹 → 选它。**注意是 `yingbian` 这一层**，不是 `src`。

### 3. 跑三条命令

```
python -m src.dump     看数据（12 节点 / 11 边 / 5 锁定）
python -m src.check    跑 4 个用例，全绿就对了
python -m src.api      启动接口服务
```

---

## 当前状态：W1 + W2 都跑通了 ✅

```
全部通过：28 项断言
```

| 用例 | 场景 | 结果 |
|---|---|---|
| **T1** | 15:00 下雨 | 2 个节点有风险，改 2 处，保留率 100%（换美术馆 + 放弃拍照） |
| **T2** | 成员晚到 1 小时 | 12/12 受影响 → 全体变更 → **停下来问用户**（5 个锁定节点被顶） |
| **T3** | 餐厅取消预订 | 1 个节点失效，改 1 处，自动换「江畔小厨」 |
| **T4** | 下雨 + 用户锁定了日落点 | **BLOCKED**，不擅自改，弹"要解锁吗" |

---

## 接口（W2）

启动后浏览器打开 <http://localhost:3000>，有一页自测按钮。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/plan/p_sat_guzhen` | 取计划 |
| POST | `/api/plan/p_sat_guzhen/event` | 发事件，算三态 |
| POST | `/api/plan/p_sat_guzhen/repair` | 求三个方案 |
| POST | `/api/plan/p_sat_guzhen/apply` | 应用方案，生成新版本 |
| POST | `/api/plan/p_sat_guzhen/undo` | 撤销 |
| GET | `/api/weather?lat=30.27&lng=120.15` | 天气 |

**给 B 用**：启动时会打印一个 `http://192.168.x.x:3000` 的局域网地址，小程序里用那个地址，不要用 localhost。

**小程序要勾**：开发者工具 → 详情 → 本地设置 → 「不校验合法域名」。

### 天气：真实优先，拿不到就明确标注

- 不配 Key：返回 `source: "演示数据（未配置 QWEATHER_KEY）"`、`isDemo: true`
- 配了 Key：真实调用和风天气

配置方法（cmd，临时生效）：

```
set QWEATHER_KEY=你的key
python -m src.api
```

**绝不让演示数据伪装成真实数据** —— 这是"数据诚实"的实现。

---

## 目录

```
yingbian/
├── data/plan-saturday.json   12 个节点的行程数据（唯一数据源）
├── src/
│   ├── models.py             数据结构 + 时间/区间小工具
│   ├── rules.py              所有阈值和权重（要调就调这里）
│   ├── cases.py              4 个用例的"标准答案"
│   ├── propagate.py          算法一：影响传播
│   ├── repair.py             算法二：最小修复
│   ├── check.py              自动对答案
│   ├── dump.py               看数据、算缓冲
│   ├── api.py                W2 接口服务
│   └── gen_mocks.py          生成给 B 的 mock JSON
├── mock/                     5 份 mock（从真实算法跑出来的）
├── start.bat                 双击启动接口服务
└── README.md
```

---

## 两个已修正的设计细节（答辩会用）

**① 天气只判"有风险"，不判"失效"**
预报是概率性的，不是既定事实。判 `invalid` 的只有事实性事件：取消、关门、超出最晚时间。
→ 所以 T1 里日落点是**黄色（at_risk）**，不是红色。

**② 取消类事件允许替换"已锁定"节点的备选**
因为原节点已经不存在了（餐厅取消了），换等价备选正好保住了用户的安排。
而"下雨"不同 —— 节点还在，只是体验会差，所以锁定的节点必须停下来问用户（T4）。

**③ 三条边要无条件校验**
一个节点自己没问题，但它和下一站的时间可能已经错位（比如被后移到 17:20 结束、下一站 17:10 开始）。
所以约束校验**不能依赖上游状态**，否则会漏掉这种错位。

---

## 建议现在就做

```
git init
git add .
git commit -m "feat: W1+W2 完成，四个用例全绿，接口可跑"
```

全国赛「软件工程过程」占 10 分，看的就是提交历史。
