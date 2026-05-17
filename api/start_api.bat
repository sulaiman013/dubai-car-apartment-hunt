@echo off
title Dubai Hunt - API (FastAPI)
cd /d "%~dp0\.."
python -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8090
echo.
echo API exited. Press any key to close.
pause >nul
