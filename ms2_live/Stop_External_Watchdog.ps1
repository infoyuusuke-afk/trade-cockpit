$ErrorActionPreference="Stop"
$runtime=Join-Path $PSScriptRoot "runtime"
$pidFile=Join-Path $runtime "external_watchdog.pid"
$marker="scripts.external_watchdog_runner"
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host "[WATCHDOG] no PID file"; exit 0 }
$raw=(Get-Content -LiteralPath $pidFile -Raw).Trim()
$watchdogPid=0
if (-not [int]::TryParse($raw,[ref]$watchdogPid)) { throw "[WATCHDOG] BLOCK: invalid PID file" }
$p=Get-CimInstance Win32_Process -Filter "ProcessId=$watchdogPid" -ErrorAction SilentlyContinue
if (-not $p) {
  Remove-Item -LiteralPath $pidFile -Force
  Write-Host "[WATCHDOG] stale PID cleaned PID=$watchdogPid"
  exit 0
}
if (($p.CommandLine -as [string]) -notmatch [regex]::Escape("scripts.external_watchdog_runner")) {
  throw "[WATCHDOG] BLOCK: PID $watchdogPid identity mismatch; refusing to stop"
}
Stop-Process -Id $watchdogPid -Force
$deadline=(Get-Date).AddSeconds(5)
while ((Get-Date) -lt $deadline -and (Get-Process -Id $watchdogPid -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 100 }
if (Get-Process -Id $watchdogPid -ErrorAction SilentlyContinue) { throw "[WATCHDOG] stop verification failed PID=$watchdogPid" }
Remove-Item -LiteralPath $pidFile -Force
Write-Host "[WATCHDOG] stopped verified PID=$watchdogPid"
