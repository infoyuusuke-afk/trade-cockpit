param([string]$MapName, [ValidateSet("timing", "crash")][string]$Mode)
$ErrorActionPreference = "Stop"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\ms2_ps_python_bridge_producer.ps1")
$capture = @{ symbol="285A.T"; market="TSE"; poll_seq=[int]3; source="offline-harness"; data_freshness="STALE";
    watcher_observed_at="2026-10-14T01:00:00.000+09:00";
    levels=@(@{Level=[int]1; BidPrice=[double]100; AskPrice=[double]101; BidQty=$null; AskQty=[int]0}) }
$packed = ConvertTo-Ms2PsBridgeRecord $capture
$session = Open-Ms2PsBridge -MapName $MapName -Size 20480
if (-not $session.Ok -or -not $packed.Ok) { throw "ATTACH_OR_PACK" }
try {
    if ($Mode -eq "crash") {
        if (-not (Enter-Ms2PsBridgeGate $session)) { throw "BUSY" }
        Write-Ms2PsBridgeInt64 $session.Accessor 512 0
        $session.Accessor.Write([long]4096, [byte]78)
        Write-Output "HELD"
        [Threading.Thread]::Sleep(30000)
        throw "EXPECTED_KILL"
    }
    $samples=@();$accepted=0;$dropped=0
    for ($i=0; $i -lt 200; $i++) {
        $watch=[Diagnostics.Stopwatch]::StartNew()
        $r=Submit-Ms2PsBridgeRecord $session $packed.Record
        $samples += $watch.Elapsed.TotalMilliseconds
        if ($r.Status -eq "ACCEPTED") {$accepted++}
        elseif ($r.Status -eq "DROPPED" -and $r.Reason -eq "DROP_NEWEST") {$dropped++}
        else {throw ("UNEXPECTED_"+$r.Status+"_"+$r.Reason)}
    }
    $sorted=@($samples | Sort-Object)
    @{ samples=200; accepted=$accepted; dropped=$dropped; p50_ms=$sorted[99]; p95_ms=$sorted[189];
       p99_ms=$sorted[197]; max_ms=$sorted[199]; context="Windows synthetic PS5.1 submit incl call overhead";
       hard_realtime_guaranteed=$false } | ConvertTo-Json -Compress
} finally { Close-Ms2PsBridge $session }
