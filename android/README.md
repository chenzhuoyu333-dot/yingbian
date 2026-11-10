# 应变 Android 客户端（W2 S1–S5）

Compose 单 Activity。内置两个构建变体：

- `emulator`：离线演示，读 `assets/fixtures/` 的假数据，不依赖后端
- `lan`：默认连电脑局域网上的后端，用于真机联调和录屏

两个包的地址都可在 App 内「连接设置」里改，改完重启仍生效。

## 用 Android Studio 打开

`File → Open`，选择本目录（`yingbian-core/android`），不要选仓库根目录。

建议设置：

- Gradle JDK：Android Studio 自带的 JBR 25
- `Settings → Build, Execution, Deployment → Build Tools → Gradle → Gradle user home`
  设为本目录下的 `.gradle-home`，依赖已经缓存过，换机器时再让它重新下载

## 运行

- 模拟器：`gradlew.bat :app:assembleEmulatorDebug`
- 真机：`gradlew.bat :app:assembleLanDebug -PbaseUrl=http://电脑IP:8000`
- 一次出两个包：`powershell -File make-apks.ps1`，产物在 `dist/`

`make-apks.ps1` 会自动读取本机局域网 IP 作为 LAN 包的默认地址，
输出 `dist/yingbian-emulator.apk` 和 `dist/yingbian-lan.apk`。

## 连接设置（真机必看）

右上角齿轮 → 连接设置：

1. 「离线演示」开关：打开用内置数据，关闭则连后端
2. 服务器地址：模拟器填 `http://10.0.2.2:8000`；真机填 `http://电脑IP:8000`
3. 点「测试连接」：显示「通 · 周六古镇一日游（12 个节点）」即成功
4. 点「保存并重载」生效，App 会立刻重新拉一次计划

USB 调试时也可以不填 IP：

```powershell
adb reverse tcp:8000 tcp:8000
```

然后把地址填成 `http://127.0.0.1:8000`。

真机走局域网时，Windows 防火墙需要放行 Python 的 8000 端口，
否则现象就是「模拟器能连、真机连不上」。

项目路径含中文，`gradle.properties` 已按 AGP 提示打开 `android.overridePathCheck=true`。

## 五个页面

| 屏 | 文件 | 内容 |
|---|---|---|
| S1 计划图 | `ui/Screens.kt` 的 `PlanScreen` | 12 个节点、11 条连线、锁定标记、天气卡 |
| S2 三方案 | `SchemeScreen` | A/B/C 改动数、保留率、牺牲项 |
| S3 影响面板 | `ImpactSheet` | 受影响节点 + 原因 + 路径判断 |
| S4 通知预览 | `NotifyScreen` | 勾选通知对象 |
| S5 待办清单 | `TodoScreen` | 勾选、拨号、复制话术 |

其余界面状态（空 / 加载 / 失败 / 阻断）分别在 `EmptyScreen`、`LoadingScreen`、
`ErrorScreen`、`BlockedDialog`。

## 演示路径

1. 行程页点“模拟下雨（15:00–17:00）”→ 2 个节点变黄 → 影响面板 → 看方案
2. 选方案 B“保体验”→ 采用 → 通知预览 → 确认并生成待办
3. 右上角齿轮 → 演示调试选项 → “餐厅取消：生成可拨号的待办”→ 选 B → 待办里点“拨号”
4. 右上角齿轮 → 演示调试选项 → “阻断演示：锁定日落点 + 降雨”→ 弹“要解锁吗？”
5. 右上角齿轮 → 演示调试选项 → “恢复：重新载入”，把计划恢复到 12 个节点 / 版本 1
6. 顶部“撤销”回到上一版

“第一版通知对象由用户勾选”是 W2 §6 的明确降级，不是遗漏。

## 接真后端

改 `data/PlanRepository.kt` 顶部的 `AppConfig`：

```kotlin
const val USE_MOCK = false
const val BASE_URL = "http://10.0.2.2:8000"   // 模拟器
```

真机 USB 调试时改成 `http://127.0.0.1:8000`，先在电脑执行：

```powershell
adb reverse tcp:8000 tcp:8000
python -m server.app
```

## 已知边界

- 后端天气已接和风（`QWEATHER_KEY`），客户端目前仍读 mock；W3 剩余工作是把天气请求切到 `/api/weather`，界面上保留 `source` 和 `fetchedAt`
- `vote` / `global` 目前只显示路径标签，没有多人投票流程
- 离线兜底使用 SharedPreferences 缓存上一次计划；假数据模式不会触发
