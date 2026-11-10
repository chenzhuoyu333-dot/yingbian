param(
    [string]$BaseUrl = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not $BaseUrl) {
    $ip = python -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',80));print(s.getsockname()[0])"
    $BaseUrl = "http://$($ip.Trim()):8000"
}

$env:JAVA_HOME = "$env:ProgramFiles\Android\Android Studio\jbr"
$env:GRADLE_USER_HOME = "$root\.gradle-home"
$env:ANDROID_USER_HOME = "$root\.android-home"
$env:GRADLE_OPTS = "-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=7897 -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=7897"

# Prefer an already installed Gradle 9.6.0; fall back to the wrapper.
$gradle = Get-ChildItem "$env:USERPROFILE\.gradle\wrapper\dists\gradle-9.6.0-bin\*\gradle-9.6.0\bin\gradle.bat" `
    -ErrorAction SilentlyContinue | Select-Object -First 1
$runner = if ($gradle) { $gradle.FullName } else { "$root\gradlew.bat" }

& $runner :app:assembleEmulatorDebug :app:assembleLanDebug `
    "-PbaseUrl=$BaseUrl" --no-daemon --console=plain

New-Item -ItemType Directory -Force "$root\dist" | Out-Null
Copy-Item "$root\app\build\outputs\apk\emulator\debug\app-emulator-debug.apk" `
    "$root\dist\yingbian-emulator.apk" -Force
Copy-Item "$root\app\build\outputs\apk\lan\debug\app-lan-debug.apk" `
    "$root\dist\yingbian-lan.apk" -Force

Write-Host ""
Write-Host "emulator 包：dist\yingbian-emulator.apk（离线演示，10.0.2.2:8000）"
Write-Host "LAN 包：     dist\yingbian-lan.apk（默认连 $BaseUrl，可在 App 设置页改）"
