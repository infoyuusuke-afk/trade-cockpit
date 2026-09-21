param([string]$Python="python",[int]$ReadyTimeoutSeconds=10)
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $PSScriptRoot
$runtime=Join-Path $root "ms2_live\runtime"
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$input=Join-Path $runtime "heartbeat_source_health.json"
$output=Join-Path $runtime "external_watchdog_health.json"
$pidFile=Join-Path $runtime "external_watchdog.pid"
$pidTmp=$pidFile+".tmp"
$log=Join-Path $runtime "external_watchdog.log"
$marker="scripts.external_watchdog_runner"

function Get-WatchdogProcess([int]$Id) {
  $p=Get-CimInstance Win32_Process -Filter "ProcessId=$Id" -ErrorAction SilentlyContinue
  if (-not $p) { return $null }
  if (($p.CommandLine -as [string]) -notmatch [regex]::Escape($marker)) { return @{ Match=$false; Process=$p } }
  return @{ Match=$true; Process=$p }
}

$pythonCmd=Get-Command $Python -ErrorAction Stop
& $pythonCmd.Source -m scripts.external_watchdog_runner --help *> $null
if ($LASTEXITCODE -ne 0) { throw "[WATCHDOG] Python runner preflight failed" }

if (Test-Path -LiteralPath $pidFile) {
  $existingId=0
  if ([int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(),[ref]$existingId)) {
    $existing=Get-WatchdogProcess $existingId
    if ($existing -and $existing.Match) { Write-Host "[WATCHDOG] ALREADY_RUNNING PID=$existingId"; exit 0 }
    if ($existing -and -not $existing.Match) { throw "[WATCHDOG] BLOCK: PID $existingId belongs to another process" }
  }
  Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$beforeOutput=if (Test-Path -LiteralPath $output) {(Get-Item -LiteralPath $output).LastWriteTimeUtc} else {[datetime]::MinValue}
$proc=Start-Process -FilePath $pythonCmd.Source -ArgumentList @("-m","scripts.external_watchdog_runner","--input",$input,"--output",$output) -WorkingDirectory $root -RedirectStandardOutput $log -RedirectStandardError ($log+".err") -PassThru -WindowStyle Hidden
try {
  [IO.File]::WriteAllText($pidTmp,[string]$proc.Id,[Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $pidTmp -Destination $pidFile -Force
  $deadline=(Get-Date).AddSeconds($ReadyTimeoutSeconds)
  $ready=$false
  while ((Get-Date) -lt $deadline) {
    $proc.Refresh()
    if ($proc.HasExited) { throw "[WATCHDOG] process exited before readiness" }
    if (Test-Path -LiteralPath $output) {
      if ((Get-Item -LiteralPath $output).LastWriteTimeUtc -gt $beforeOutput) { $ready=$true; break }
    }
    Start-Sleep -Milliseconds 250
  }
  if (-not $ready) { throw "[WATCHDOG] readiness timeout" }
  Write-Host "[WATCHDOG] READY PID=$($proc.Id)"
} catch {
  if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  Remove-Item -LiteralPath $pidFile,$pidTmp -Force -ErrorAction SilentlyContinue
  throw
}
