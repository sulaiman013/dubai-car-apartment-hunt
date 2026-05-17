# Dubai Daily Scraper Scheduler — PowerShell (no admin needed)
# Runs at 18:00 Bangladesh local time daily (= 16:00 Dubai time)

$ErrorActionPreference = "Stop"
$scriptDir  = $PSScriptRoot
$scriptPath = Join-Path $scriptDir "scrape_dubai_cars.py"
$taskName   = "DubaiCarHunt_Daily"
$runAt      = "18:00"   # 6 PM Bangladesh time

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Dubai Car Hunt - Daily Scraper Setup"        -ForegroundColor Cyan
Write-Host " Schedule: $runAt local (Bangladesh GMT+6)"   -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Locate Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) { $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $pythonCmd) {
    Write-Host "ERROR: Python not found on PATH" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
$pythonExe = $pythonCmd.Source
Write-Host "Python: $pythonExe" -ForegroundColor Green

# Install/refresh required packages
Write-Host "`nInstalling required packages..." -ForegroundColor Yellow
& $pythonExe -m pip install --quiet --upgrade playwright beautifulsoup4 pandas
& $pythonExe -m playwright install chromium

# Remove any existing task with the same name
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Build the new task
$action   = New-ScheduledTaskAction `
              -Execute $pythonExe `
              -Argument "-X utf8 `"$scriptPath`"" `
              -WorkingDirectory $scriptDir

$trigger  = New-ScheduledTaskTrigger -Daily -At $runAt

$settings = New-ScheduledTaskSettingsSet `
              -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries `
              -StartWhenAvailable `
              -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Daily Dubai car hunt - Dubizzle+DubiCars+YallaMotor scraper" | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
$info = $task | Get-ScheduledTaskInfo

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " SUCCESS - daily scraper scheduled"          -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host " Task name : $taskName"
Write-Host " Schedule  : Daily at $runAt local time"
Write-Host " Next run  : $($info.NextRunTime)" -ForegroundColor Cyan
Write-Host ""
Write-Host " Run now   : Start-ScheduledTask -TaskName $taskName"
Write-Host " Test now  : python -X utf8 `"$scriptPath`""
Write-Host " View      : Get-ScheduledTask -TaskName $taskName"
Write-Host " Delete    : Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
Write-Host ""
Read-Host "Press Enter to exit"
