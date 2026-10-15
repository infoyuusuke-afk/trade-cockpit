# Diagnostic only: splits the first PS5.1 bridge submit into its cost parts on
# synthetic data. It asserts nothing and does not change any threshold.
param([ValidateSet("submit", "submit_notrace", "primitives")][string]$Mode = "submit", [int]$Count = 6)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
. (Join-Path $repo "scripts\ms2_ps_python_bridge_producer.ps1")

function Get-Ms([System.Diagnostics.Stopwatch]$Clock) { [math]::Round($Clock.Elapsed.TotalMilliseconds, 3) }
function Measure-Twice([string]$Name, [scriptblock]$Body) {
    $out = @()
    foreach ($i in 1, 2, 3) {
        $clock = [System.Diagnostics.Stopwatch]::StartNew()
        & $Body
        $out += (Get-Ms $clock)
    }
    return [ordered]@{ name = $Name; first = $out[0]; second = $out[1]; third = $out[2] }
}

if ($Mode -eq "primitives") {
    $map = [System.IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew(("ms2probe-" + [guid]::NewGuid().ToString("N")), 20480)
    $acc = $map.CreateViewAccessor(0, 20480)
    $mutex = New-Object System.Threading.Mutex($false)
    $inbuf = New-Object byte[] 2072
    $payload = New-Object byte[] 2048
    $rows = @()
    $rows += Measure-Twice "ps_empty_function" { function Invoke-Ms2Nothing { 1 }; [void](Invoke-Ms2Nothing) }
    $rows += Measure-Twice "mutex_waitone_release" { [void]$mutex.WaitOne(0); $mutex.ReleaseMutex() }
    $rows += Measure-Twice "accessor_read_int64" { [void]$acc.ReadInt64(0) }
    $rows += Measure-Twice "accessor_write_int32" { $acc.Write([long]192, [int]0) }
    $rows += Measure-Twice "reflection_write_int64" { Write-Ms2PsBridgeInt64 $acc 0 0 }
    $rows += Measure-Twice "reflection_write_array" { Write-Ms2PsBridgeBytes $acc 4096 $payload }
    $rows += Measure-Twice "sha256_create_compute" { $s = [Security.Cryptography.SHA256]::Create(); try { [void]$s.ComputeHash($inbuf) } finally { $s.Dispose() } }
    $rows += Measure-Twice "bitconverter_array_copy" { $p = New-Object byte[] 24; [Array]::Copy([BitConverter]::GetBytes([long]5), 0, $p, 0, 8) }
    $rows += Measure-Twice "hashtable_return" { $h = @{ Status = "ACCEPTED"; ElapsedMs = 1.0; Retry = $false } }
    $acc.Dispose(); $map.Dispose(); $mutex.Dispose()
    Write-Host ("PS_PRIMITIVES=" + (ConvertTo-Json -Compress -Depth 4 @($rows)))
    exit 0
}

$capture = @{
    symbol = "285A.T"; market = "TSE"; poll_seq = [int]3; source = "offline-harness"; data_freshness = "STALE"
    watcher_observed_at = "2026-10-14T01:00:00.000+09:00"
    levels = @(@{ Level = [int]1; BidPrice = [double]100.0; AskPrice = [double]101.0; BidQty = $null; AskQty = [int]0; read_at = "2026-10-14T01:00:00.010+09:00" })
    gap = @{ window_size = [int]300; overlap_with_prev = [int]0; prev_poll_nonempty = $true; new_appended = [int]20; suspected_gap = $true }
}
$packed = ConvertTo-Ms2PsBridgeRecord $capture
if (-not $packed.Ok) { throw "PACK_FAILED" }

$name = "b" + ([guid]::NewGuid().ToString("N").Substring(0, 11))
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = "python"
$start.Arguments = "-m scripts.ms2_ps_python_bridge hold --name $name --preset empty --timeout 20"
$start.WorkingDirectory = $repo
$start.RedirectStandardOutput = $true
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $start
[void]$proc.Start()
try {
    $task = $proc.StandardOutput.ReadLineAsync()
    if (-not $task.Wait(15000)) { throw "STDOUT_TIMEOUT" }
    if ($task.Result -ne ("READY " + $name + " 20480")) { throw "NOT_READY" }
    $openClock = [System.Diagnostics.Stopwatch]::StartNew()
    if ($Mode -eq "submit") { $session = Open-Ms2PsBridge -MapName $name -Size 20480 -TraceTiming }
    else { $session = Open-Ms2PsBridge -MapName $name -Size 20480 }
    $openMs = Get-Ms $openClock
    if (-not $session.Ok) { throw ("OPEN_" + $session.Reason) }
    $rows = @()
    for ($i = 1; $i -le $Count; $i++) {
        $outer = [System.Diagnostics.Stopwatch]::StartNew()
        $r = Submit-Ms2PsBridgeRecord -Session $session -Record $packed.Record
        $outerMs = Get-Ms $outer
        $stages = [ordered]@{}
        if ($session.TraceTiming -and $session.LastStages) {
            foreach ($k in "HEADER", "PREFIX", "CHECKSUM", "ENVELOPE", "PAYLOAD", "COMMIT", "UNLOCK") {
                if ($session.LastStages.ContainsKey($k)) { $stages[$k] = [math]::Round($session.LastStages[$k], 3) }
            }
        }
        $elapsed = [math]::Round($r.ElapsedMs, 3)
        $mutexMs = [math]::Round([double]$session.LastMutexMs, 3)
        $publishMs = [math]::Round([double]$session.LastPublishMs, 3)
        $rows += [ordered]@{
            n = $i; status = $r.Status; elapsed_ms = $elapsed; outer_ms = $outerMs
            call_overhead_ms = [math]::Round($outerMs - $elapsed, 3)
            mutex_ms = $mutexMs; publish_ms = $publishMs
            pre_gate_ms = [math]::Round($elapsed - $publishMs - $mutexMs, 3)
            stages = $stages
        }
    }
    Close-Ms2PsBridge $session
    Write-Host ("PS_FIRST_SUBMIT=" + (ConvertTo-Json -Compress -Depth 4 ([ordered]@{ mode = $Mode; open_ms = $openMs; submits = @($rows) })))
} finally {
    if (-not $proc.WaitForExit(5000)) { try { $proc.Kill() } catch {} }
}
