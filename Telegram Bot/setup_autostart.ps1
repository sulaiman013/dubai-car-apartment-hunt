# Register a Windows scheduled task that starts the Telegram bot at user logon.
$ErrorActionPreference = "Stop"
$here     = $PSScriptRoot
$batPath  = Join-Path $here "start_bot.bat"
$taskName = "DubaiHunt_TGbot"

if (-not (Test-Path $batPath)) { Write-Host "start_bot.bat not found at $batPath" -ForegroundColor Red; exit 1 }

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed previous task"
}

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Dubai Hunt Telegram bot - starts at user logon" | Out-Null

Write-Host ""
Write-Host "SUCCESS - bot will start at logon" -ForegroundColor Green
Write-Host " Task   : $taskName"
Write-Host " Start  : Start-ScheduledTask -TaskName $taskName"
Write-Host " Stop   : Stop-Process -Name node"
Write-Host " Remove : Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
