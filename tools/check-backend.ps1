# 检查本机后端是否在跑
#
# 用法：双击根目录的「检查后端.bat」，或
#       powershell -ExecutionPolicy Bypass -File tools\check-backend.ps1
#
# 判定顺序（前者成功就不必看后者）：
#   1. HTTP 能不能拿到 /api/plans  → 这是"真的能用"的唯一标准
#   2. TCP 端口能不能连上          → HTTP 不通但端口通 = 刚启动或别的程序占了
#   3. 谁在占用这个端口            → 排错用
#
# 注意：不要用 Get-NetTCPConnection -State Listen 判断 ——
#       某些机器上它返回的 State 是空的，会把运行中的后端误判成"没在听"。

param([int]$Port = 8000)

$ErrorActionPreference = "Continue"
function Ok($t)   { Write-Host ("  [OK] " + $t) -ForegroundColor Green }
function Bad($t)  { Write-Host ("  [X ] " + $t) -ForegroundColor Red }
function Info($t) { Write-Host ("       " + $t) -ForegroundColor Gray }

Write-Host ""
Write-Host "  检查后端  http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host ""

# (1) HTTP + 数据
$httpOk = $false
try {
    $resp = Invoke-WebRequest "http://127.0.0.1:$Port/api/plans" -TimeoutSec 4 -UseBasicParsing
    if ($resp.StatusCode -eq 200) {
        $httpOk = $true
        Ok "HTTP 正常（200）"
        try {
            $json = $resp.Content | ConvertFrom-Json
            $planCount = @($json.data.plans).Count
            Ok ("能取到数据：$planCount 份行程")
        } catch {
            Info "返回内容不是预期 JSON（可能别的服务占了这个端口）"
        }
    } else {
        Bad ("HTTP 状态码 " + $resp.StatusCode)
    }
} catch {
    Bad "HTTP 连不上（后端没启动，或端口被别的程序占了）"
}

# (2) TCP 端口（HTTP 失败时用来区分"没开"和"开了但没响应"）
$portOpen = $false
if (-not $httpOk) {
    try {
        $portOpen = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
    } catch {
        $portOpen = $false
    }
    if ($portOpen) {
        Info "端口 $Port 能连上，但 HTTP 没响应 —— 可能刚启动，等 5 秒再试"
    } else {
        Info "端口 $Port 也连不上"
    }
}

# (3) 谁占着这个端口
$holder = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($holder) {
    $proc = Get-Process -Id $holder.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
        $started = if ($proc.StartTime) { $proc.StartTime.ToString("HH:mm:ss") } else { "未知" }
        Info ("端口占用：" + $proc.ProcessName + "（PID " + $proc.Id + "，启动于 " + $started + "）")
    }
}

# (4) 手机该填什么
if ($httpOk) {
    Write-Host ""
    Write-Host "  手机 / 平板该填的地址：" -ForegroundColor Cyan
    $any = $false
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
        ForEach-Object {
            Write-Host ("       http://" + $_.IPAddress + ":" + $Port)
            $any = $true
        }
    if (-not $any) { Info "没找到局域网 IP，检查 Wi-Fi 是否连着" }
}

Write-Host ""
if ($httpOk) {
    Write-Host "  结论：后端在正常运行，App 可以直接用。" -ForegroundColor Green
    Write-Host "  浏览器打开 http://127.0.0.1:$Port 能看到状态页。" -ForegroundColor Gray
} elseif ($portOpen) {
    Write-Host "  结论：端口在听但 HTTP 不通，再等几秒重试。" -ForegroundColor Yellow
} else {
    Write-Host "  结论：后端没在跑。启动方法：" -ForegroundColor Yellow
    Write-Host "      双击根目录的「启动后端.bat」" -ForegroundColor White
    Write-Host "      或：python -m uvicorn server.app:app --host 0.0.0.0 --port $Port" -ForegroundColor White
}
Write-Host ""
