@echo off
REM Refresh frontend data from the latest scraper output and open the dashboard.
cd /d "%~dp0"
echo Refreshing data from latest scrape...
python -X utf8 "%~dp0prep_data.py"
echo.
echo Opening dashboard in your default browser...
start "" "%~dp0index.html"
