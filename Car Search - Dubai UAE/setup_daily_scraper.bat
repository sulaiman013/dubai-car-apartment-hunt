@echo off
echo ============================================
echo  Dubai Car Hunt - Daily Scraper Scheduler
echo  Schedules the scraper at 18:00 BD time
echo ============================================
echo.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_daily_scraper.ps1"
