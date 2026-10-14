param([string]$MapName,[string]$WarmMap,[long]$Generation,[int]$N=100,[string]$Mode='normal')
$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1){throw 'PS51_REQUIRED'}
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\ms2_ps_python_bridge_producer.ps1')
$session=Open-Ms2PsBridge -MapName $MapName -Size 20480
if(-not $session.Ok){throw 'ATTACH_REFUSED'}
$warm=[Diagnostics.Stopwatch]::StartNew()
$stamp=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
$c=@{symbol='285A.T';market='TSE';source='synthetic-372';poll_seq=[int]1;observation_id=('s'+$Generation+'-1');watcher_observed_at=$stamp;read_started_at=$stamp;read_finished_at=$stamp;sequence_basis='POLL';snapshot_atomic=$false;levels=@(@{Level=[int]1;AskPrice=[double]101;BidPrice=[double]100;AskQty=[int]0;BidQty=$null;read_at=$stamp})}
$p=ConvertTo-Ms2PsBridgeRecord $c
if(-not $p.Ok){throw 'PACK_REFUSED'}
if($Mode -ne 'cold'){
 $warmSession=Open-Ms2PsBridge -MapName $WarmMap -Size 20480
 if(-not $warmSession.Ok){throw 'WARM_ATTACH_REFUSED'}
 try {
  $warmResult=Submit-Ms2PsBridgeRecord $warmSession $p.Record
  if($warmResult.Status -ne 'ACCEPTED'){throw 'WARM_SUBMIT_REFUSED'}
 } finally {Close-Ms2PsBridge $warmSession}
}
# Warmup publishes only to a disposable IPC fixture with no Writer. Control uses stdin, outside all measured boundaries.
@{kind='ready';ps=$PSVersionTable.PSVersion.ToString();warmup_ms=$warm.Elapsed.TotalMilliseconds}|ConvertTo-Json -Compress
if([Console]::ReadLine() -ne 'GO'){throw 'GO_REQUIRED'}
try {
 for($i=1;$i -le $N;$i++){
  $full=[Diagnostics.Stopwatch]::StartNew();$t=[Diagnostics.Stopwatch]::StartNew()
  $poll=if($Mode -eq 'duplicate'){1}else{$i}
  if($Mode -ne 'duplicate'){
   $stamp=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz');$c.poll_seq=[int]$poll;$c.observation_id=('s'+$Generation+'-'+$poll)
   $c.watcher_observed_at=$stamp;$c.read_started_at=$stamp;$c.read_finished_at=$stamp;$c.levels[0].read_at=$stamp
  }
  $capture=$t.Elapsed.TotalMilliseconds;$t.Restart();$p=ConvertTo-Ms2PsBridgeRecord $c;$packing=$t.Elapsed.TotalMilliseconds
  if(-not $p.Ok){throw 'PACK_REFUSED'}
  $t.Restart();$r=Submit-Ms2PsBridgeRecord $session $p.Record;$submit=$t.Elapsed.TotalMilliseconds;$elapsed=$full.Elapsed.TotalMilliseconds
  # Per-poll independent receipt stream; transport/backpressure is OUTSIDE timing.
  @{kind='receipt';session_id=('native-'+$Generation);generation=$Generation;poll_seq=$poll;attempt=$i;state=$r.Status;reason=$r.Reason;observed_at=[DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz');record=[Convert]::ToBase64String($p.Record);capture_ms=$capture;packing_ms=$packing;submit_ms=$submit;full_ms=$elapsed}|ConvertTo-Json -Compress
  if([Console]::ReadLine() -ne 'NEXT'){throw 'NEXT_REQUIRED'}
  if($Mode -ne 'queue_full'){Start-Sleep -Milliseconds 5}
 }
 @{kind='done'}|ConvertTo-Json -Compress
} finally {Close-Ms2PsBridge $session}
