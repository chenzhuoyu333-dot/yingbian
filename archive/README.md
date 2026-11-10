# 归档：`w2-reference/`

这是组员独立写的一版 W1 + W2 实现，**不参与构建、测试和演示**，只作参考与交叉验证。

为什么归档：

- 它的算法结论和主实现一致（T1 2/12、T2 12/12 阻断、T3 1/12、T4 阻断），
  可以作为"两套独立实现互相印证"的证据。
- 但它自带一份**不同的行程数据**（节点 id 是 `n_walk` / `n_cafe` / `n_dinner` 等），
  和主数据 `data/plan-saturday.json` 不能混用，混用会导致接口和界面结果对不上。
- 它的服务端口、错误码、字段命名也和主接口有细微差别，客户端只需对接主接口。

主实现始终以仓库根目录为准：

- 数据：`data/plan-saturday.json`
- 算法：`yingbian/`
- 接口：`server/app.py`
- 客户端：`android/`

其中已经吸收的部分：

- 真实和风天气（`yingbian/weather.py`，`QWEATHER_KEY` + `isDemo` 诚实标注）
- 网页自测台与 `POST /api/reset`（`server/app.py`）
- 服务启动时打印局域网地址（手机真机联调用）
- 阈值与方案权重集中到 `yingbian/rules.py`
- 修复候选"试跑否决"（会制造新冲突的动作直接淘汰，`yingbian/repair.py`）
- drop 动作在图上的语义说明
