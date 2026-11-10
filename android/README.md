# 应变 Android 客户端（W2 S1–S5）

Compose 单 Activity，默认读取 `app/src/main/assets/fixtures/` 里的假数据，
不连后端也能把“降雨 → 影响 → 三方案 → 通知 → 待办 → 撤销”整条流程走完。

## 用 Android Studio 打开

`File → Open`，选择本目录（`yingbian-core/android`），不要选仓库根目录。

建议设置：

- Gradle JDK：Android Studio 自带的 JBR 25
- `Settings → Build, Execution, Deployment → Build Tools → Gradle → Gradle user home`
  设为本目录下的 `.gradle-home`，依赖已经缓存过，换机器时再让它重新下载

## 运行

- 模拟器或真机直接点 Run
- 命令行：`gradlew.bat :app:assembleDebug`
- APK：`app/build/outputs/apk/debug/app-debug.apk`

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
3. 右上角齿轮 → “餐厅取消：生成可拨号的待办”→ 选 B → 待办里点“拨号”
4. 右上角齿轮 → “阻断演示：锁定日落点 + 降雨”→ 弹“要解锁吗？”
5. 右上角齿轮 → “恢复：重新载入”，把计划恢复到 12 个节点 / 版本 1
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
