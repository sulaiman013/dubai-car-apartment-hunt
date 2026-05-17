# Expose the Dubai Car Hunt dashboard via a Cloudflare Quick Tunnel.
# Serves the frontend folder on http://localhost:8765, then prints a public
# https://*.trycloudflare.com URL you can open from your phone.
#
# Run:    powershell -ExecutionPolicy Bypass -File share_via_tunnel.ps1
# Stop:   close the window, or Ctrl+C

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$port = 8765
$cf   = "$env:USERPROFILE\cloudflared\cloudflared.exe"

if (-not (Test-Path $cf)) {
    Write-Host "cloudflared.exe not found at $cf" -ForegroundColor Red
    Write-Host "Download it from: https://github.com/cloudflare/cloudflared/releases/latest"
    Read-Host "Press Enter to exit"; exit 1
}

# Kill any stale server / tunnel from a previous run.
Get-Process python, cloudflared -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match 'DCH-' -or $_.CommandLine -match 'http\.server|trycloudflare' } |
    Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host " Dubai Car Hunt - phone tunnel" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host " Serving:  $here"
Write-Host " Local:    http://localhost:$port"
Write-Host ""

# 1. Local static server (Python http.server)
$serverLog = Join-Path $env:TEMP "dch_server.log"
$server = Start-Process -PassThru -WindowStyle Hidden -FilePath "python" `
    -ArgumentList "-X","utf8","-m","http.server",$port,"--bind","127.0.0.1" `
    -WorkingDirectory $here -RedirectStandardOutput $serverLog -RedirectStandardError $serverLog
Write-Host " Started local server (PID $($server.Id))" -ForegroundColor Green
Start-Sleep -Seconds 1

# Probe the local server before opening a tunnel.
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/index.html" -UseBasicParsing -TimeoutSec 5
    if ($r.StatusCode -ne 200) { throw "status $($r.StatusCode)" }
    Write-Host " Local server is responding (HTTP 200)" -ForegroundColor Green
} catch {
    Write-Host " Local server did not respond: $_" -ForegroundColor Red
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Read-Host "Press Enter to exit"; exit 1
}

Write-Host ""
Write-Host " Starting Cloudflare Quick Tunnel..." -ForegroundColor Yellow
Write-Host " (Watch for a line like: https://something-random.trycloudflare.com)"
Write-Host " (Press Ctrl+C to stop both the tunnel and the local server)"
Write-Host ""

# Trap Ctrl+C: clean up the local server before exiting.
try {
    & $cf tunnel --no-autoupdate --url "http://localhost:$port"
} finally {
    Write-Host ""
    Write-Host "Shutting down local server (PID $($server.Id))..."
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Bye."
}
