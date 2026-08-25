# Registers a daily 08:30 sync task for the Garmin CIRQA collector.
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_sync.ps1
# Remove later with:
#   Unregister-ScheduledTask -TaskName "GarminCirqaSync" -Confirm:$false

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Virtualenv python not found at $python - run the setup steps in AGENTS.md first."
    exit 1
}

$action    = New-ScheduledTaskAction -Execute $python -Argument "sync.py --quiet" -WorkingDirectory $repo
$trigger   = New-ScheduledTaskTrigger -Daily -At 08:30
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName "GarminCirqaSync" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Scheduled task 'GarminCirqaSync' registered: daily 08:30, runs sync.py --quiet"
