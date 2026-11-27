# 一键出预览图：模拟器截图
#
# 用法：
#   .\tools\preview.ps1                 # 行程页
#   .\tools\preview.ps1 -Screen scheme  # 方案页
#   .\tools\preview.ps1 -Screen profile # 我的
#   .\tools\preview.ps1 -Screen new     # 新建页
#   .\tools\preview.ps1 -NoBuild        # 不重新编译，只截图
#
# 做的事：
#   1. 模拟器没开就开（无窗口）
#   2. adb reverse 8000 → 让模拟器用 127.0.0.1 访问电脑后端
#   3. 编译并安装（除非 -NoBuild）
#   4. 启动 App → 点对应 tab → 截图到 交付\预览-<screen>.png
#
# 为什么要这套：真机截不了图（HDB 驱动缺失），
# 但模拟器能跑同一个 APK，看到的就是真界面。

param(
    [ValidateSet('plan', 'scheme', 'profile', 'new')]
    [string]$Screen = 'plan',
    [switch]$NoBuild,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$android = Join-Path $repo 'android'
$sdk = "$env:LOCALAPPDATA\Android\Sdk"
$adb = Join-Path $sdk 'platform-tools\adb.exe'
$emu = Join-Path $sdk 'emulator\emulator.exe'
$avd = 'Medium_Phone_API_37.0'

$env:JAVA_HOME = 'C:\Program Files\JetBrains\IntelliJ IDEA Community Edition 2025.2.6.4\jbr'
$env:ANDROID_HOME = $sdk
$env:PATH = "$env:JAVA_HOME\bin;$sdk\platform-tools;$env:PATH"

# 1) 模拟器
$devices = (& $adb devices) | Select-Object -Skip 1 | Where-Object { $_ -match 'emulator.*device$' }
if (-not $devices) {
    Write-Host '[1/5] 启动模拟器（无窗口，约 60~90 秒）…' -ForegroundColor Cyan
    Start-Process -FilePath $emu -ArgumentList @(
        '-avd', $avd, '-no-window', '-no-audio', '-no-boot-anim',
        '-gpu', 'swiftshader_indirect', '-no-snapshot-save'
    ) -WindowStyle Hidden
    for ($i = 1; $i -le 40; $i++) {
        Start-Sleep -Seconds 3
        $devices = (& $adb devices) | Select-Object -Skip 1 | Where-Object { $_ -match 'emulator.*device$' }
        if ($devices) { break }
    }
}
if (-not $devices) { throw '模拟器没起来' }
$serial = (($devices | Select-Object -First 1) -split '\s+')[0]
for ($i = 1; $i -le 40; $i++) {
    $boot = (& $adb -s $serial shell getprop sys.boot_completed 2>&1) -join ''
    if ($boot.Trim() -eq '1') { break }
    Start-Sleep -Seconds 3
}
Write-Host "[1/5] 模拟器就绪：$serial" -ForegroundColor Green

# 2) 端口转发
& $adb -s $serial reverse "tcp:$Port" "tcp:$Port" | Out-Null
$rev = (& $adb -s $serial reverse --list) -join ' '
if ($rev -match "$Port") {
    Write-Host "[2/5] 端口转发已建立：127.0.0.1:$Port → 电脑:$Port" -ForegroundColor Green
} else {
    Write-Host '[2/5] 端口转发失败（App 将连不上后端）' -ForegroundColor Yellow
}

# 3) 编译安装
$apk = Join-Path $android 'app\build\outputs\apk\lan\debug\app-lan-debug.apk'
if (-not $NoBuild) {
    Write-Host '[3/5] 编译…' -ForegroundColor Cyan
    Push-Location $android
    try {
        & '.\gradlew.bat' assembleLanDebug "-PbaseUrl=http://127.0.0.1:$Port" --no-daemon --console=plain |
            Select-String -Pattern '^e: |BUILD SUCCESS|BUILD FAILED' | Select-Object -First 6
    } finally { Pop-Location }
}
if (-not (Test-Path $apk)) { throw "找不到 APK：$apk" }
& $adb -s $serial install -r $apk 2>&1 | Select-String 'Success|Failure' | ForEach-Object { '  ' + $_.Line }
Write-Host '[3/5] 已安装' -ForegroundColor Green

# 4) 启动 + 切页
& $adb -s $serial shell am force-stop com.example.yingbian | Out-Null
& $adb -s $serial shell am start -n com.example.yingbian/.MainActivity | Out-Null
Start-Sleep -Seconds 8

# 1080x2400 下底部 tab 的中心坐标
$tabs = @{ plan = @(176, 2278); scheme = @(538, 2278); profile = @(902, 2278) }
if ($tabs.ContainsKey($Screen)) {
    $xy = $tabs[$Screen]
    & $adb -s $serial shell input tap $xy[0] $xy[1] | Out-Null
    Start-Sleep -Seconds 3
} elseif ($Screen -eq 'new') {
    & $adb -s $serial shell input tap 878 148 | Out-Null   # 右上角 +
    Start-Sleep -Seconds 4
}
Write-Host "[4/5] 已切到：$Screen" -ForegroundColor Green

# 5) 截图
$dir = Join-Path (Split-Path -Parent $PSScriptRoot) '..\软创\交付'
if (-not (Test-Path $dir)) { $dir = Join-Path $env:USERPROFILE 'Desktop' }
$out = Join-Path $dir "预览-$Screen.png"
cmd /c "`"$adb`" -s $serial exec-out screencap -p > `"$out`""
$head = [IO.File]::ReadAllBytes($out)[0..3]
$ok = ($head[0] -eq 137 -and $head[1] -eq 80)
Write-Host ("[5/5] 截图：" + $out + "  " + [math]::Round((Get-Item $out).Length / 1KB, 0) + " KB") -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
