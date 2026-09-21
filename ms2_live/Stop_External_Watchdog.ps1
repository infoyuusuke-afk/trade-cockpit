$runtime=Join-Path $PSScriptRoot "runtime"
$pidFile=Join-Path $runtime "external_watchdog.pid"
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host "[WATCHDOG] no PID file"; exit 0 }
$watchdogPid=[int](Get-Content -LiteralPath $pidFile -Raw)
$p=Get-Process -Id $watchdogPid -ErrorAction SilentlyContinue
if ($p) { Stop-Process -Id $watchdogPid -Force; Write-Host "[WATCHDOG] stopped PID=$watchdogPid" }
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
