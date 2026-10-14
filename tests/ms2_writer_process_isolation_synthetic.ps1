<#
Issue #382 Windows PowerShell 5.1 synthetic, genuinely separate PROCESS Writer.
No MS2, Excel, Collector import, network, broker, real observations or orders.
The bounded preallocated in-memory bus is a *disposable fixture* NOT an adapter
for the Collector or existing canonical 2048-byte / IPC implementation.
No guarantee about OS scheduling or 5ms worst case; see metrics.
#>
[CmdletBinding()]
param(
    [switch]$Worker,
    [string]$MapName,
    [string]$MutexName,
    [ValidateSet('normal','writer_blocked','gate_held','writer_killed','queue_full')]
    [string]$Mode = 'normal',
    [int]$Iterations = 120
)
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'WINDOWS_POWERSHELL_5_1_REQUIRED'
}
Add-Type -TypeDefinition @'
using System;
using System.IO.MemoryMappedFiles;
using System.Threading;
public sealed class SyntheticMs2Bus : IDisposable {
    const int CAPACITY=4;
    const long WR=0, RD=8, READY=16, WORKER_STATE=24, DATA=64;
    MemoryMappedFile map;
    MemoryMappedViewAccessor view;
    Mutex mutex;
    public SyntheticMs2Bus(string mapName,string mutexName,bool create) {
        if(create) {
            map=MemoryMappedFile.CreateNew(mapName,4096);
            mutex=new Mutex(false,mutexName);
        } else {
            map=MemoryMappedFile.OpenExisting(mapName);
            mutex=Mutex.OpenExisting(mutexName);
        }
        view=map.CreateViewAccessor(0,4096,MemoryMappedFileAccess.ReadWrite);
        if(create) {
            view.Write(WR,(long)0);
            view.Write(RD,(long)0);
            view.Write(READY,(long)0);
            view.Write(WORKER_STATE,(long)0);
        }
    }
    public long Ready { get { return view.ReadInt64(READY); } }
    public long WorkerState { get { return view.ReadInt64(WORKER_STATE); } }
    public void SignalReady() { view.Write(READY,(long)1); }
    public int Offer(long id) {
        bool owned=false;
        try {
            try { owned=mutex.WaitOne(0); }
            catch(AbandonedMutexException) {
                // Owns an abandoned mutex; no recovery or re-enqueue is safe.
                try { mutex.ReleaseMutex(); } catch(Exception) {}
                return -3;
            }
            if(!owned) return -2; // GATE_BUSY, no wait
            long write=view.ReadInt64(WR), read=view.ReadInt64(RD);
            if(write<read || write-read>CAPACITY) return -4;
            if(write-read==CAPACITY) return -1; // QUEUE_FULL
            view.Write(DATA+(write%CAPACITY)*8,id);
            view.Write(WR,write+1);
            return 1; // QUEUED ONLY, NOT DURABLY PERSISTED
        } finally {
            if(owned) mutex.ReleaseMutex();
        }
    }
    public long Take() {
        bool owned=false;
        try {
            try { owned=mutex.WaitOne(0); }
            catch(AbandonedMutexException) {
                try { mutex.ReleaseMutex(); } catch(Exception) {}
                return -3;
            }
            if(!owned) return 0;
            long write=view.ReadInt64(WR), read=view.ReadInt64(RD);
            if(write<=read) return 0;
            if(write-read>CAPACITY) return -4;
            long id=view.ReadInt64(DATA+(read%CAPACITY)*8);
            view.Write(RD,read+1);
            return id;
        } finally { if(owned) mutex.ReleaseMutex(); }
    }
    public void StallWriterOutsideGate(int ms) {
        view.Write(WORKER_STATE,(long)2);
        Thread.Sleep(ms); // artificial blocking Writer I/O, not disk
    }
    public void StallWriterHoldingGate(int ms) {
        bool owned=mutex.WaitOne(0);
        try {
            view.Write(WORKER_STATE,(long)1);
            Thread.Sleep(ms);
        } finally { if(owned) mutex.ReleaseMutex(); }
    }
    public void Dispose() {
        if(view!=null)view.Dispose();
        if(mutex!=null)mutex.Dispose();
        if(map!=null)map.Dispose();
    }
}
'@ -ErrorAction Stop

function Require([bool]$predicate,[string]$name) {
    if(-not $predicate){throw ("SYNTHETIC_ASSERT_FAILED_"+$name)}
}
function Percentile([double[]]$numbers,[double]$quantile) {
    if($numbers.Count -eq 0){return $null}
    $sorted=@($numbers|Sort-Object)
    $ix=[Math]::Max(0,([Math]::Ceiling($quantile*$sorted.Count)-1))
    return [Math]::Round([double]$sorted[$ix],4)
}
if($Worker) {
    $bus=[SyntheticMs2Bus]::new($MapName,$MutexName,$false)
    try {
        $bus.SignalReady()
        if($Mode -eq 'writer_blocked' -or $Mode -eq 'queue_full'){
            $bus.StallWriterOutsideGate(4000)
        } elseif($Mode -eq 'gate_held') {
            $bus.StallWriterHoldingGate(4000)
        } else {
            # This is a worker PROCESS; no code in the producer calls Take.
            for($i=0;$i -lt 2000;$i++){
                [void]$bus.Take()
                [Threading.Thread]::Sleep(1)
            }
        }
    } finally {$bus.Dispose()}
    return
}
$results=@()
$scriptPath=$PSCommandPath
foreach($mode in @('normal','writer_blocked','queue_full','gate_held','writer_killed')){
    $nonce=[guid]::NewGuid().ToString('N')
    $mmf='Local\ms2_synth_'+$nonce
    $mtx='Local\ms2_synth_gate_'+$nonce
    $bus=[SyntheticMs2Bus]::new($mmf,$mtx,$true)
    $job=$null
    try {
        $job=Start-Job -ScriptBlock {
            param($source,$map,$gate,$case)
            & $source -Worker -MapName $map -MutexName $gate -Mode $case
        } -ArgumentList $scriptPath,$mmf,$mtx,$mode
        $deadline=[Diagnostics.Stopwatch]::StartNew()
        while($bus.Ready -ne 1 -and $deadline.ElapsedMilliseconds -lt 15000){
            if($job.State -eq 'Failed'){throw 'WORKER_PROCESS_FAILED_BEFORE_READY'}
            [Threading.Thread]::Sleep(10)
        }
        Require ($bus.Ready -eq 1) 'WORKER_READY'
        if($mode -eq 'writer_killed') {
            Stop-Job $job -ErrorAction Stop
            Require ($job.State -in @('Stopped','Completed','Failed')) 'WORKER_STOPPED'
        } elseif($mode -eq 'writer_blocked' -or $mode -eq 'gate_held' -or $mode -eq 'queue_full') {
            $start=[Diagnostics.Stopwatch]::StartNew()
            while($bus.WorkerState -ne $(if($mode -eq 'gate_held'){1}else{2}) -and $start.ElapsedMilliseconds -lt 4000) {
                [Threading.Thread]::Sleep(10)
            }
            Require ($bus.WorkerState -eq $(if($mode -eq 'gate_held'){1}else{2})) 'WRITER_FAULT_ACTIVE'
        }
        $samples=New-Object 'System.Collections.Generic.List[double]'
        $queued=0; $full=0; $busy=0; $abandoned=0; $corrupt=0
        $priceMock=0; $signalMock=0; $riskMock=0; $killMock=0
        # PRE-ATTACHED, PRE-COMPILED path. No disk, subprocess, JSON, SHA,
        # canonical pack, IPC open or worker join in the measured Offer().
        $producerLoop=[Diagnostics.Stopwatch]::StartNew()
        for($i=1;$i -le $Iterations;$i++){
            $watch=[Diagnostics.Stopwatch]::StartNew()
            $status=$bus.Offer([long]$i)
            $watch.Stop()
            $samples.Add($watch.Elapsed.TotalMilliseconds)
            switch($status) {
                1 {$queued++}
                -1 {$full++}
                -2 {$busy++}
                -3 {$abandoned++}
                default {$corrupt++}
            }
            $priceMock++;$signalMock++;$riskMock++;$killMock++
            if($mode -eq 'normal'){[Threading.Thread]::Sleep(2)}
        }
        $producerLoop.Stop()
        Require ($priceMock -eq $Iterations -and $signalMock -eq $Iterations -and
                 $riskMock -eq $Iterations -and $killMock -eq $Iterations) 'MOCK_MONITOR_CONTINUITY'
        Require (($queued+$full+$busy+$abandoned+$corrupt) -eq $Iterations) 'EVERY_OFFER_CLASSIFIED'
        Require ($corrupt -eq 0) 'NO_CORRUPT_RING_STATE'
        if($mode -eq 'writer_blocked' -or $mode -eq 'writer_killed' -or $mode -eq 'queue_full') {
            Require ($full -gt 0) 'WRITER_NOT_DRAINING_QUEUE_FULL'
        }
        if($mode -eq 'gate_held') {Require ($busy -gt 0) 'HELD_GATE_NO_WAIT_DROP'}
        $numbers=$samples.ToArray()
        $line=[ordered]@{
            scenario=$mode
            observations=$Iterations
            queued=$queued;drop_queue_full=$full;drop_gate_busy=$busy
            drop_abandoned=$abandoned;corrupt=$corrupt
            price_updates=$priceMock;signal_updates=$signalMock
            risk_checks=$riskMock;kill_checks=$killMock
            p50_ms=(Percentile $numbers .50);p95_ms=(Percentile $numbers .95)
            p99_ms=(Percentile $numbers .99);max_ms=(Percentile $numbers 1.0)
            loop_ms=[Math]::Round($producerLoop.Elapsed.TotalMilliseconds,4)
            worker_separate_process=$true
            persisted_verified=$false
            eligible_observed_n=0
            real_submit_allowed=$false
            promotion_eligible=$false
            statistical_edge_confirmed=$false
            no_os_wcet_proof=$true
        }
        $results+=New-Object psobject -Property $line
    } finally {
        if($null -ne $job) {
            if($job.State -eq 'Running') {Stop-Job $job -ErrorAction SilentlyContinue}
            Remove-Job $job -Force -ErrorAction SilentlyContinue
        }
        $bus.Dispose()
    }
}
[pscustomobject]@{
    schema_version='ms2-writer-process-isolation-synthetic-0.1'
    runtime='WindowsPowerShell5.1'
    sample_kind='OFFLINE_SYNTHETIC_NOT_REAL_MARKET'
    real_submit_allowed=$false
    completed_scenarios=$results.Count
    cases=$results
} | ConvertTo-Json -Depth 7 -Compress
