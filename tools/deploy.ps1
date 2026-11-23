# 一条命令：编译 → 装到设备 → 端口转发 → 启动
#
# 用法：
#   .\tools\deploy.ps1                 # 联网版，走 127.0.0.1（adb reverse）
#   .\tools\deploy.ps1 -Mock           # 离线演示版
#   .\tools\deploy.ps1 -BaseUrl http://10.195.159.236:8000
#   .\tools\deploy.ps1 -Fresh          # 签名冲突/装不上时用（先卸载再装）
#   .\tools\deploy.ps1 -Log            # 装完自动看日志
#
# 为什么默认走 127.0.0.1：
#   adb reverse 把设备的 127.0.0.1:8000 转发到电脑，地址永远不变，
#   也不受校园网 AP 隔离、DHCP 换 IP 的影响。

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$Mock,
    [switch]$Fresh,
    [switch]$Log,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$android = Join-Path $repo "android"
$apkLan = Join-Path $android "app\build\outputs\apk\lan\debug\app-lan-debug.apk"
$apkMock = Join-Path $android "app\build\outputs\apk\emulator\debug\app-emulator-debug.apk"
$appId = "com.example.yingbian"

# ── 环境 ────────────────────────────────────────────────
$env:JAVA_HOME = "C:\Program Files\JetBrains\IntelliJ IDEA Community Edition 2025.2.6.4\jbr"
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:PATH = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:PATH"

$adb = Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
if (-not (Test-Path $adb)) { throw "找不到 adb：$adb" }

# ── 设备检查 ────────────────────────────────────────────
& $adb start-server 2>&1 | Out-Null
$devices = (& $adb devices) | Select-Object -Skip 1 | Where-Object { $_ -match "\sdevice$" }
if (-not $devices) {
    Write-Host "没检测到设备。检查三件事：" -ForegroundColor Yellow
    Write-Host "  1) 平板：设置 → 关于 → 连点『版本号』7 次 → 开发者选项"
    Write-Host "  2) 开发者选项里打开『USB 调试』（小米/OPPO 还要开『USB 安装』）"
    Write-Host "  3) 插上线后平板上会弹『允许 USB 调试吗』，勾选始终允许并确定"
    exit 1
}
Write-Host ("设备: " + ($devices -join ", ")) -ForegroundColor Green

# ── 编译 ────────────────────────────────────────────────
if (-not $NoBuild) {
    Push-Location $android
    try {
        if ($Mock) {
            Write-Host "编译离线演示版…" -ForegroundColor Cyan
            & ".\gradlew.bat" assembleEmulatorDebug --no-daemon --console=plain
        } else {
            Write-Host "编译联网版（默认地址 $BaseUrl）…" -ForegroundColor Cyan
            & ".\gradlew.bat" assembleLanDebug "-PbaseUrl=$BaseUrl" --no-daemon --console=plain
        }
        if ($LASTEXITCODE -ne 0) { throw "编译失败" }
    } finally {
        Pop-Location
    }
}

$apk = if ($Mock) { $apkMock } else { $apkLan }
if (-not (Test-Path $apk)) { throw "找不到安装包：$apk" }

# ── 安装 ────────────────────────────────────────────────
if ($Fresh) {
    Write-Host "先卸载旧版（签名不同时必需）…" -ForegroundColor Yellow
    & $adb uninstall $appId 2>&1 | Out-Null
}

Write-Host "安装中…" -ForegroundColor Cyan
$install = & $adb install -r $apk 2>&1
Write-Host ($install -join "`n")
if ($install -match "INSTALL_FAILED_UPDATE_INCOMPATIBLE|signatures do not match") {
    Write-Host "签名冲突：加 -Fresh 重新跑（会清掉 App 数据）" -ForegroundColor Yellow
    exit 1
}
if ($install -notmatch "Success") { throw "安装失败" }

# ── 端口转发：让设备用 127.0.0.1 访问电脑 ────────────────
& $adb reverse tcp:8000 tcp:8000 2>&1 | Out-Null
$reverse = (& $adb reverse --list) -join " "
if ($reverse -match "8000") {
    Write-Host "已建立端口转发 127.0.0.1:8000 → 电脑:8000" -ForegroundColor Green
} else {
    Write-Host "端口转发没成功（设备可能不支持，退回用局域网 IP）" -ForegroundColor Yellow
}

# ── 启动 ────────────────────────────────────────────────
& $adb shell am start -n "$appId/.MainActivity" 2>&1 | Out-Null
Write-Host "已启动 App" -ForegroundColor Green
Write-Host ""
Write-Host "有用的命令：" -ForegroundColor Cyan
Write-Host "  截图   : & `"$adb`" exec-out screencap -p > shot.png"
Write-Host "  日志   : & `"$adb`" logcat -s YingBian AndroidRuntime"
Write-Host "  清数据 : & `"$adb`" shell pm clear $appId"

if ($Log) {
    Write-Host "`n日志（Ctrl+C 退出）…" -ForegroundColor Cyan
    & $adb logcat -s AndroidRuntime:System.err
}
