@echo off
REM Double-click to share the landing page + both dashboards to your phone.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0share_via_tunnel.ps1"
echo.
pause
