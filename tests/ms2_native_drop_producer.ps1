param([string]$MapName, [string]$EvidenceName, [long]$Generation, [int]$N=100,
      [string]$Mode='normal', [string]$PauseAt='none')
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) { throw 'PS51_REQUIRED' }
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\ms2_ps_python_bridge_producer.ps1')
# Compile/attach before the loop. No durable write, process launch or pipe per poll.
Add-Type -TypeDefinition @'
using System;
using System.IO.MemoryMappedFiles;
using System.Threading;
public sealed class OfflineDropJournal : IDisposable {
  MemoryMappedFile map; MemoryMappedViewAccessor view; long version;
  public OfflineDropJournal(string name, long generation) {
    map=MemoryMappedFile.OpenExisting(name); view=map.CreateViewAccessor(0,1024);
    if(view.ReadInt64(8)!=generation) throw new Exception("GENERATION");
    version=view.ReadInt64(0);
    if(version!=0) throw new Exception("NO_REPLAY_OR_SECOND_PRODUCER");
  }
  public void Begin() { view.Write(0,++version); Thread.MemoryBarrier(); }
  public void End(int reason,long poll,long unixMs) {
    long offset=64+reason*40; long count=view.ReadInt64(offset);
    if(count==0) { view.Write(offset+8,poll); view.Write(offset+24,unixMs); }
    view.Write(offset,count+1); view.Write(offset+16,poll); view.Write(offset+32,unixMs);
    view.Write(16,view.ReadInt64(16)+1); view.Write(24,poll);
    Thread.MemoryBarrier(); view.Write(0,++version);
  }
  public void Complete() { Begin(); view.Write(32,(long)1); Thread.MemoryBarrier(); view.Write(0,++version); }
  public void Dispose() { view.Dispose(); map.Dispose(); }
}
'@
$timer=[Diagnostics.Stopwatch]::StartNew()
$session=Open-Ms2PsBridge -MapName $MapName -Size 20480
$attachMs=$timer.Elapsed.TotalMilliseconds
if (-not $session.Ok) { throw 'ATTACH_REFUSED' }
$journal=New-Object OfflineDropJournal($EvidenceName,$Generation)
$samples=New-Object System.Collections.Generic.List[object]
$loop=[Diagnostics.Stopwatch]::StartNew(); $lastTick=0.0; $jitter=New-Object System.Collections.Generic.List[double]
try {
  for($poll=1;$poll -le $N;$poll++) {
    # Price/audio/signal mock precedes observation boundary, no disk in either path.
    $tick=$loop.Elapsed.TotalMilliseconds; $jitter.Add($tick-$lastTick); $lastTick=$tick
    $priceMock=$poll; $audioMock=$poll; $signalMock=$poll
    $full=[Diagnostics.Stopwatch]::StartNew()
    $journal.Begin()
    if ($PauseAt -eq 'before_capture' -and $poll -eq 2) { Start-Sleep -Seconds 30 }
    $captureStart=$full.Elapsed.TotalMilliseconds
    $started=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
    $capture=@{symbol='285A.T';market='TSE';poll_seq=[int]$poll;source='synthetic-native-368';data_freshness='UNKNOWN';
      observation_id=('offline-'+$Generation+'-'+$poll); watcher_observed_at=$started;read_started_at=$started;
      sequence_basis='POLL';snapshot_atomic=$false;
      levels=@(@{Level=[int]1;AskPrice=[double]101;BidPrice=[double]100;AskQty=[int]0;BidQty=$null;
        read_at=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')})}
    $capture.read_finished_at=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
    $captureMs=$full.Elapsed.TotalMilliseconds-$captureStart
    $packingStart=$full.Elapsed.TotalMilliseconds
    if($Mode -eq 'invalid') { $capture.poll_seq=[int]0 }
    $packed=ConvertTo-Ms2PsBridgeRecord $capture
    $packingMs=$full.Elapsed.TotalMilliseconds-$packingStart
    $submitStart=$full.Elapsed.TotalMilliseconds
    $reason=0; $state='ACCEPTED'
    if (-not $packed.Ok) { $reason=5; $state='DROP' }
    elseif($Mode -eq 'stale') {$reason=4;$state='DROP'}
    elseif($Mode -eq 'not_ready') {$reason=3;$state='DROP'}
    elseif($Mode -eq 'stop') {$reason=6;$state='DROP'}
    elseif($Mode -eq 'writer_stopped') {$reason=8;$state='DROP'}
    else {
      $result=Submit-Ms2PsBridgeRecord $session $packed.Record
      if($result.Status -ne 'ACCEPTED') {
        $state='DROP'; $reason=9
        if($result.Reason -eq 'DROP_NEWEST') {$reason=1}
        elseif($result.Reason -eq 'PRODUCER_BUSY') {$reason=2}
        elseif($result.Reason -eq 'KILL_SWITCH') {$reason=7}
      }
    }
    $submitMs=$full.Elapsed.TotalMilliseconds-$submitStart
    if($PauseAt -eq 'after_accept' -and $poll -eq 2) { Start-Sleep -Seconds 30 }
    $journal.End($reason,$poll,[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
    $fullMs=$full.Elapsed.TotalMilliseconds
    $samples.Add(@{state=$state;reason=$reason;capture_ms=$captureMs;packing_ms=$packingMs;submit_ms=$submitMs;full_ms=$fullMs})
    # Benchmark pacing is outside measured producer boundary.
    if($Mode -eq 'normal' -or $Mode -eq 'cpu') { Start-Sleep -Milliseconds 5 }
  }
  $journal.Complete()
  @{ps=$PSVersionTable.PSVersion.ToString();attach_ms=$attachMs;samples=@($samples.ToArray());
    mock_counts=@($priceMock,$audioMock,$signalMock);loop_spacing_ms=@($jitter.ToArray());
    snapshot_atomic=$false;eligible_observed_n=0;producer_persisted=$false} | ConvertTo-Json -Depth 6 -Compress
} finally { $journal.Dispose(); Close-Ms2PsBridge $session }
