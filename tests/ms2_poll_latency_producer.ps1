param([string]$MapName,[string]$Mode='accepted',[int]$N=100)
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'PS51_REQUIRED'}
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\ms2_ps_python_bridge_producer.ps1')
$session=Open-Ms2PsBridge -MapName $MapName -Size 20480
if(-not $session.Ok){throw ('ATTACH_REFUSED_'+$session.Reason)}
$map=[IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting($MapName)
$view=$map.CreateViewAccessor(0,20480)
$samples=New-Object System.Collections.Generic.List[object]
$warm=[Diagnostics.Stopwatch]::StartNew()
$stamp=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
$base=@{symbol='285A.T';market='TSE';source='synthetic-370';poll_seq=[int]1;observation_id='latency-warm';
 watcher_observed_at=$stamp;read_started_at=$stamp;read_finished_at=$stamp;sequence_basis='POLL';snapshot_atomic=$false;
 levels=@(@{Level=[int]1;AskPrice=[double]101;BidPrice=[double]100;AskQty=[int]0;BidQty=$null;read_at=$stamp})}
$packed=ConvertTo-Ms2PsBridgeRecord $base
if(-not $packed.Ok){throw 'WARMUP_PACK_REFUSED'}
$warmSubmit=Submit-Ms2PsBridgeRecord $session $packed.Record
if($warmSubmit.Status -ne 'ACCEPTED'){throw 'WARMUP_SUBMIT_REFUSED'}
# First warmup includes pack and initial IPC/JIT; kept separate from steady.
$warmMs=$warm.Elapsed.TotalMilliseconds
$view.Write([long]120,[long]1)
$deadline=[DateTime]::UtcNow.AddSeconds(20)
while($view.ReadInt64(120) -ne 2){if([DateTime]::UtcNow -gt $deadline){throw 'READY_DEADLINE'};Start-Sleep -Milliseconds 1}
# Standalone IPC fixture has NO writer watchdog. A held gate therefore measures
# PRODUCER_BUSY alone rather than a preexisting KILL_SWITCH after 150ms.
if($Mode -eq 'gate_busy'){$view.Write([long]192,[int]1)}
if($Mode -eq 'drop'){$view.Write([long]0,[long]8)}
try{
 for($poll=1;$poll -le $N;$poll++){
  $full=[Diagnostics.Stopwatch]::StartNew()
  $mock=[Diagnostics.Stopwatch]::StartNew()
  $price=[Diagnostics.Stopwatch]::StartNew();$priceMock=$poll;$priceMs=$price.Elapsed.TotalMilliseconds
  $audio=[Diagnostics.Stopwatch]::StartNew();$audioMock=$poll;$audioMs=$audio.Elapsed.TotalMilliseconds
  $signal=[Diagnostics.Stopwatch]::StartNew();$signalMock=$poll;$signalMs=$signal.Elapsed.TotalMilliseconds
  $mockMs=$mock.Elapsed.TotalMilliseconds
  $captureTimer=[Diagnostics.Stopwatch]::StartNew()
  $stamp=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
  $base.poll_seq=[int]$poll;$base.observation_id=('latency-'+$poll);$base.watcher_observed_at=$stamp
  $base.read_started_at=$stamp;$base.read_finished_at=$stamp;$base.levels[0].read_at=$stamp
  $captureMs=$captureTimer.Elapsed.TotalMilliseconds
  $packing=[Diagnostics.Stopwatch]::StartNew();$packed=ConvertTo-Ms2PsBridgeRecord $base;$packingMs=$packing.Elapsed.TotalMilliseconds
  if(-not $packed.Ok){throw 'PACK_REFUSED'}
  $submit=[Diagnostics.Stopwatch]::StartNew();$result=Submit-Ms2PsBridgeRecord $session $packed.Record;$submitMs=$submit.Elapsed.TotalMilliseconds
  $fullMs=$full.Elapsed.TotalMilliseconds
  $observed=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
  # Synthetic record retained only in memory AFTER the measured boundary.
  $samples.Add(@{poll_seq=$poll;state=$result.Status;reason=$result.Reason;observed_at=$observed;
   record=[Convert]::ToBase64String($packed.Record);mock_ms=$mockMs;price_mock_ms=$priceMs;audio_mock_ms=$audioMs;signal_mock_ms=$signalMs;capture_ms=$captureMs;
   packing_ms=$packingMs;submit_ms=$submitMs;full_ms=$fullMs})
  if($Mode -eq 'accepted'){Start-Sleep -Milliseconds 5}
 }
 @{ps=$PSVersionTable.PSVersion.ToString();first_warmup_ms=$warmMs;samples=@($samples.ToArray());mock_counts=@($priceMock,$audioMock,$signalMock)}|ConvertTo-Json -Depth 6 -Compress
}finally{$view.Write([long]192,[int]0);$view.Dispose();$map.Dispose();Close-Ms2PsBridge $session}
