# 启动后端（Windows 一键版）
#
# 用法：
#   双击根目录的「启动后端.bat」
#   或：powershell -ExecutionPolicy Bypass -File tools\start-backend.ps1
#   只想检查环境、不启动：powershell -ExecutionPolicy Bypass -File tools\start-backend.ps1 -Check
#
# 它会做四件事：
#   1. 检查 Python 版本
#   2. 缺依赖就装（requirements.txt）
#   3. 没有 .env 就从 .env.example 复制一份，并提示填哪两个 key
#   4. 打印"手机该填的地址"，然后启动服务

param(
    [switch]$Check,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Line($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

Line "==============================================" "Cyan"
Line "  应变 · 后端启动器" "Cyan"
Line "==============================================" "Cyan"
Write-Host ""

# ── 1. Python ───────────────────────────────────────────
$python = $null
foreach ($candidate in @("python", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) { $python = $candidate; break }
        }
    } catch { }
}

if (-not $python) {
    Line "✗ 没找到 Python 3.10+" "Red"
    Line "  去 https://www.python.org/downloads/ 装一个，装的时候勾选 Add to PATH" "Yellow"
    if (-not $Check) { Read-Host "按回车退出" | Out-Null }
    exit 1
}
$pyVersion = & $python --version 2>&1
Line "✓ Python: $pyVersion" "Green"

# ── 2. 依赖 ─────────────────────────────────────────────
$needInstall = $false
try {
    & $python -c "import fastapi, uvicorn, httpx" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $needInstall = $true }
} catch { $needInstall = $true }

if ($needInstall) {
    Line "… 正在安装依赖（第一次会慢一点）" "Yellow"
    & $python -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Line "✗ 依赖安装失败，检查网络或换国内镜像：" "Red"
        Line "  $python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple" "Yellow"
        if (-not $Check) { Read-Host "按回车退出" | Out-Null }
        exit 1
    }
    Line "✓ 依赖装好了" "Green"
} else {
    Line "✓ 依赖已就绪" "Green"
}

# ── 3. .env ─────────────────────────────────────────────
$envPath = Join-Path $repo ".env"
$examplePath = Join-Path $repo ".env.example"

if (-not (Test-Path $envPath)) {
    if (Test-Path $examplePath) {
        Copy-Item $examplePath $envPath
        Line "" 
        Line "！已从 .env.example 生成 .env，但里面是空的。" "Yellow"
        Line "  打开 $envPath 填这两行（不填也能跑，但功能会降级）：" "Yellow"
        Line "    AMAP_KEY=你的高德Key           （不填：搜不到地点，生成行程会失败）" "Yellow"
        Line "    LLM_API_KEY=你的DeepSeekKey    （不填：退回规则解析，界面会标注）" "Yellow"
        Line "  填完再运行一次本脚本。" "Yellow"
        if (-not $Check) { Read-Host "按回车退出" | Out-Null }
        exit 0
    }
} 

# 读 .env，看关键项填了没
$envLines = @{}
foreach ($line in Get-Content $envPath -Encoding UTF8) {
    if ($line -match "^\s*([A-Z_]+)\s*=\s*(.*)$") { $envLines[$Matches[1]] = $Matches[2].Trim() }
}
$amapOk = $envLines.ContainsKey("AMAP_KEY") -and $envLines["AMAP_KEY"]
$llmOk = $envLines.ContainsKey("LLM_API_KEY") -and $envLines["LLM_API_KEY"]
Line ("✓ .env: AMAP_KEY " + $(if ($amapOk) { "已填" } else { "缺失（生成会失败）" })) $(if ($amapOk) { "Green" } else { "Yellow" })
Line ("✓ .env: LLM_API_KEY " + $(if ($llmOk) { "已填" } else { "缺失（退回规则解析）" })) $(if ($llmOk) { "Green" } else { "Yellow" })

# ── 4. 地址 ─────────────────────────────────────────────
Write-Host ""
Line "手机 / 平板该填的地址：" "Cyan"
$found = $false
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
    ForEach-Object {
        Line ("    http://" + $_.IPAddress + ":$Port") "White"
        $found = $true
    }
if (-not $found) { Line "    （没找到局域网 IP，检查 Wi-Fi 是否连着）" "Yellow" }

Line "" 
Line "提示：App 里点【自动寻找服务器】也能自己找到，不用手填。" "Gray"
Write-Host ""

if ($Check) {
    Line "（-Check 模式：只检查，不启动）" "Gray"
    exit 0
}

# ── 5. 启动 ─────────────────────────────────────────────
Line "正在启动服务… 保持这个窗口开着，关掉服务就停了" "Cyan"
Line "按 Ctrl+C 停止" "Gray"
Write-Host ""
& $python -m uvicorn server.app:app --host 0.0.0.0 --port $Port
