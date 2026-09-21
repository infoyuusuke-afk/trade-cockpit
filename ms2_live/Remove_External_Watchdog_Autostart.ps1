param(
  [switch]$Apply,
  [string]$TaskName="AI-Cockpit-External-Watchdog-v1"
)
$ErrorActionPreference="Stop"
if (-not $Apply) {
  Write-Host "[WATCHDOG-AUTOSTART] DRY_RUN uninstall; would remove $TaskName"
  exit 0
}
$task=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) { Write-Host "[WATCHDOG-AUTOSTART] task not present"; exit 0 }
Disable-ScheduledTask -TaskName $TaskName | Out-Null
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[WATCHDOG-AUTOSTART] REMOVED $TaskName"
