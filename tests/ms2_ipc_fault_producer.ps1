param([string]$MapName, [ValidateSet("timing", "crash")][string]$Mode)
$startup=[Diagnostics.Stopwatch]::StartNew()
$ErrorActionPreference = "Stop"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\ms2_ps_python_bridge_producer.ps1")
$capture = @{ symbol="285A.T"; market="TSE"; poll_seq=[int]3; source="offline-harness"; data_freshness="STALE";
    watcher_observed_at="2026-10-14T01:00:00.000+09:00";
    levels=@(@{Level=[int]1; BidPrice=[double]100; AskPrice=[double]101; BidQty=$null; AskQty=[int]0}) }
$packing=[Diagnostics.Stopwatch]::StartNew()
$packed = ConvertTo-Ms2PsBridgeRecord $capture
$firstPackingMs=$packing.Elapsed.TotalMilliseconds
$attaching=[Diagnostics.Stopwatch]::StartNew()
$session = Open-Ms2PsBridge -MapName $MapName -Size 20480 -TraceTiming
$attachMs=$attaching.Elapsed.TotalMilliseconds
$startupMs=$startup.Elapsed.TotalMilliseconds
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
    function Stats($Values) {
        $v=@($Values | Sort-Object);$n=$v.Count
        return @{samples=$n;p50_ms=$v[[Math]::Ceiling($n*.50)-1];p95_ms=$v[[Math]::Ceiling($n*.95)-1];p99_ms=$v[[Math]::Ceiling($n*.99)-1];max_ms=$v[$n-1]}
    }
    $packSamples=@();$attachSamples=@()
    for ($i=0; $i -lt 50; $i++) {
        $t=[Diagnostics.Stopwatch]::StartNew();$p=ConvertTo-Ms2PsBridgeRecord $capture
        $packSamples += $t.Elapsed.TotalMilliseconds
        if (-not $p.Ok) {throw "PACK"}
        $t=[Diagnostics.Stopwatch]::StartNew();$a=Open-Ms2PsBridge $MapName 20480
        $attachSamples += $t.Elapsed.TotalMilliseconds
        if (-not $a.Ok) {throw "ATTACH"};Close-Ms2PsBridge $a
    }
    $completeSamples=@();$completePack=@();$gcSamples=@();$cpuSamples=@();$stageSamples=@{};$worst=@{}
    $samples=@();$mutexSamples=@();$publishSamples=@();$acceptedSamples=@();$fullSamples=@();$accepted=0;$dropped=0
    for ($i=0; $i -lt 200; $i++) {
        $gcBefore=@([GC]::CollectionCount(0),[GC]::CollectionCount(1),[GC]::CollectionCount(2))
        $cpuBefore=[Diagnostics.Process]::GetCurrentProcess().TotalProcessorTime.TotalMilliseconds
        $complete=[Diagnostics.Stopwatch]::StartNew()
        $packed=ConvertTo-Ms2PsBridgeRecord $capture
        $packMs=$complete.Elapsed.TotalMilliseconds
        if (-not $packed.Ok) {throw "PACK"}
        $watch=[Diagnostics.Stopwatch]::StartNew()
        $r=Submit-Ms2PsBridgeRecord $session $packed.Record
        $elapsed=$watch.Elapsed.TotalMilliseconds
        $total=$complete.Elapsed.TotalMilliseconds
        $completeSamples += $total;$completePack += $packMs
        $gcDelta=@(([GC]::CollectionCount(0)-$gcBefore[0]),([GC]::CollectionCount(1)-$gcBefore[1]),([GC]::CollectionCount(2)-$gcBefore[2]))
        $cpuDelta=[Diagnostics.Process]::GetCurrentProcess().TotalProcessorTime.TotalMilliseconds-$cpuBefore
        $cpuSamples += $cpuDelta
        foreach ($key in $session.LastStages.Keys) {
            if (-not $stageSamples.ContainsKey($key)) {$stageSamples[$key]=@()}
            $stageSamples[$key] += $session.LastStages[$key]
        }
        if ($worst.Count -eq 0 -or $total -gt $worst.total_ms) {
            $worst=@{index=$i;total_ms=$total;packing_ms=$packMs;submit_ms=$elapsed;status=$r.Status;
                mutex_ms=$session.LastMutexMs;publish_ms=$session.LastPublishMs;stages=$session.LastStages.Clone();gc_delta=$gcDelta;process_cpu_ms=$cpuDelta}
        }
        $samples += $elapsed
        $mutexSamples += $session.LastMutexMs
        $publishSamples += $session.LastPublishMs
        if ($r.Status -eq "ACCEPTED") {$accepted++;$acceptedSamples += $elapsed}
        elseif ($r.Status -eq "DROPPED" -and $r.Reason -eq "DROP_NEWEST") {$dropped++;$fullSamples += $elapsed}
        else {throw ("UNEXPECTED_"+$r.Status+"_"+$r.Reason)}
    }
    $stageStats=@{};foreach($key in $stageSamples.Keys){$stageStats[$key]=Stats $stageSamples[$key]}
    $sorted=@($samples | Sort-Object)
    @{ samples=200; accepted=$accepted; dropped=$dropped; p50_ms=$sorted[99]; p95_ms=$sorted[189];
       p99_ms=$sorted[197]; max_ms=$sorted[199]; context="Windows synthetic PS5.1 submit incl call overhead";
       phases=@{packing=(Stats $packSamples);attach=(Stats $attachSamples);mutex=(Stats $mutexSamples);publish=(Stats $publishSamples);accepted=(Stats $acceptedSamples);full=(Stats $fullSamples)};
       complete_steady=(Stats $completeSamples);complete_packing=(Stats $completePack);stage_stats=$stageStats;worst=$worst;
       seed=364;input="fixed one-level offline fixture poll3; missing bid qty and explicit zero ask qty";
       instrumentation="Stopwatch wall time; GC counts; process CPU includes harness overhead; no causal proof";
       cold=@{packing_ms=$firstPackingMs;attach_ms=$attachMs;startup_ms=$startupMs};
       hard_realtime_guaranteed=$false } | ConvertTo-Json -Depth 5 -Compress
} finally { Close-Ms2PsBridge $session }
