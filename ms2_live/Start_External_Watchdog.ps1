param([string]$Python="python")
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $PSScriptRoot
$runtime=Join-Path $root "ms2_live\runtime"
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$input=Join-Path $runtime "heartbeat_source_health.json"
$output=Join-Path $runtime "external_watchdog_health.json"
$pidFile=Join-Path $runtime "external_watchdog.pid"
$log=Join-Path $runtime "external_watchdog.log"
$proc=Start-Process -FilePath $Python -ArgumentList @("-m","scripts.external_watchdog_runner","--input",$input,"--output",$output) -WorkingDirectory $root -RedirectStandardOutput $log -RedirectStandardError ($log+".err") -PassThru -WindowStyle Hidden
[IO.File]::WriteAllText($pidFile,[string]$proc.Id,[Text.UTF8Encoding]::new($false))
Write-Host "[WATCHDOG] started PID=$($proc.Id)"
