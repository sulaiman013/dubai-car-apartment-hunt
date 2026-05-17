@echo off
REM Double-click to share the dashboard to your phone via Cloudflare Quick Tunnel.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0share_via_tunnel.ps1"
echo.
pause
