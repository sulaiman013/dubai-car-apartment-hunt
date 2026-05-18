@echo off
REM Double-click this on the laptop to refresh Bayut apartments on the VPS.
REM Activates the venv, runs the sync script, pauses on exit so you can read output.

cd /d "%~dp0\.."
REM Prefer the project venv if it exists; fall back to system Python.
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python -X utf8 scripts\sync_bayut_to_vps.py
echo.
echo (press any key to close)
pause >nul
