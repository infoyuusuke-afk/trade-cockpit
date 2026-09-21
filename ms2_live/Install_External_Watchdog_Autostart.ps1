param(
  [switch]$Activate,
  [string]$Python="python",
  [string]$TaskName="AI-Cockpit-External-Watchdog-v1"
)
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $PSScriptRoot
$start=Join-Path $root "ms2_live\Start_External_Watchdog.ps1"
if (-not (Test-Path -LiteralPath $start)) { throw "Hardened watchdog start script not found" }
$pythonCmd=Get-Command $Python -ErrorAction Stop
$ps=(Get-Command powershell.exe -ErrorAction Stop).Source
$quotedStart='"'+$start.Replace('"','""')+'"'
$quotedPython='"'+$pythonCmd.Source.Replace('"','""')+'"'
$arguments="-NoProfile -ExecutionPolicy Bypass -File $quotedStart -Python $quotedPython"
$plan=[ordered]@{
  task_name=$TaskName
  trigger="AtLogOn"
  executable=$ps
  arguments=$arguments
  working_directory=$root
  multiple_instances="IgnoreNew"
  restart_count=3
  restart_interval_minutes=1
  activation_requested=[bool]$Activate
}
$plan | ConvertTo-Json -Depth 4
if (-not $Activate) {
  Write-Host "[WATCHDOG-AUTOSTART] DRY_RUN only; Task Scheduler unchanged"
  exit 0
}
$action=New-ScheduledTaskAction -Execute $ps -Argument $arguments -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -AtLogOn
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "AI Cockpit External Watchdog only; no broker/order submit" -Force | Out-Null
Write-Host "[WATCHDOG-AUTOSTART] REGISTERED $TaskName"
