<#
P0-25. Non-destructive process/port/BRAIN ownership assessment.
Deliberately does NOT grant authority to stop or switch. No PID numbers,
command lines, paths, environment details, workbook names, or account data
are printed. Not a substitute for a real-safe-stop preflight.
#>
param([string]$Root="C:\AI_Cockpit_OneClick_Starter")
$ErrorActionPreference="Stop"
$stage="INPUT"
function Refuse([string]$Reason){throw $Reason}
try{
 $rootPath=[IO.Path]::GetFullPath($Root)
 $folder=Get-Item -LiteralPath $rootPath -ErrorAction Stop
 if(-not $folder.PSIsContainer -or
    (($folder.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)){
  Refuse "UNTRUSTED_ROOT"
 }
 $stateFile=Join-Path $rootPath "V10_CONTROLLER_STATE.json"
 if(-not (Test-Path -LiteralPath $stateFile -PathType Leaf)){
  Refuse "STATE_ABSENT"
 }
 $f=Get-Item -LiteralPath $stateFile -ErrorAction Stop
 if(($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    $f.Length -lt 2 -or $f.Length -gt 65536){Refuse "UNTRUSTED_STATE"}
 $stage="STATE"
 $state=[IO.File]::ReadAllText($stateFile,[Text.Encoding]::UTF8) |
   ConvertFrom-Json -ErrorAction Stop
 if($null -eq $state -or $state -isnot [pscustomobject]){Refuse "STATE_JSON_INVALID"}
 $map=[ordered]@{
  controller_pid="AI_COCKPIT_CONTROLLER_V10.ps1"
  watcher_pid="Kioxia_RSS_Live_Watcher.ps1"
  heartbeat_pid="Kioxia_Safety_Heartbeat.ps1"
  collector_pid="MS2_RSS_100_Collector.ps1"
  gateway_pid="AI_COCKPIT_GATEWAY_V10.ps1"
  brain_gateway_pid="AI_COCKPIT_GATEWAY_V10.ps1"
  voice_bridge_pid="AI_COCKPIT_VOICE_BRIDGE_V10.ps1"
  sbv2_pid="server_fastapi.py"
  shadow_supervisor_pid="ai_shadow_supervisor.py"
  brain_observer_pid="ai_brain_observer.py"
  excel_pid="EXCEL.EXE"
 }
 $brainPresent=($state.PSObject.Properties.Match("brain_observer_pid").Count -eq 1)
 $brainRecorded=0
 $brainValid=$false
 if($brainPresent){
  $brainValid=[int]::TryParse([string]$state.brain_observer_pid,[ref]$brainRecorded)
  if(-not $brainValid -or $brainRecorded -lt 0){Refuse "BRAIN_PID_INVALID"}
 }
 $repoPath=[string]$state.repo_root
 $runtimePath=[string]$state.runtime_dir
 if([string]::IsNullOrWhiteSpace($repoPath) -or
    [string]::IsNullOrWhiteSpace($runtimePath)){Refuse "STATE_ROOT_FIELDS_EMPTY"}
 $expectedObserver=Join-Path $repoPath "scripts\ai_brain_observer.py"
 $expectedLive=Join-Path $runtimePath "live_ms2.json"
 $expectedStatus=Join-Path $runtimePath "ai_brain_observer_status_v1.json"
 $stage="PROCESS_INVENTORY"
 $procs=@(Get-CimInstance Win32_Process -ErrorAction Stop)
 $byPid=@{}
 foreach($p in $procs){$byPid[[int]$p.ProcessId]=$p}
 $liveTracked=0
 $matchedTracked=0
 $unverifiedTracked=0
 $trackedPids=New-Object 'System.Collections.Generic.HashSet[int]'
 foreach($name in $map.Keys){
  $member=$state.PSObject.Properties[$name]
  if($null -eq $member){continue}
  $pidNumber=0
  if(-not [int]::TryParse([string]$member.Value,[ref]$pidNumber) -or $pidNumber -lt 0){
   Refuse "TRACKED_PID_INVALID"
  }
  if($pidNumber -le 0){continue}
  [void]$trackedPids.Add($pidNumber)
  if(-not $byPid.ContainsKey($pidNumber)){continue}
  $liveTracked++
  $p=$byPid[$pidNumber]
  $cmd=[string]$p.CommandLine
  $basename=[string]$p.Name
  $owned=$false
  if($name -ceq "excel_pid"){
   # A running Excel.exe is not proof of ownership by this cockpit.
   $owned=$false
  }elseif($name -ceq "controller_pid"){
   $owned=($cmd.IndexOf("RUN_AI_COCKPIT_V10.ps1",
            [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
           $cmd.IndexOf("AI_COCKPIT_CONTROLLER_V10.ps1",
            [StringComparison]::OrdinalIgnoreCase) -ge 0)
  }else{
   $owned=($cmd.IndexOf([string]$map[$name],
          [StringComparison]::OrdinalIgnoreCase) -ge 0)
  }
  if($owned){$matchedTracked++}else{$unverifiedTracked++}
 }
 $brainCandidates=0
 $brainOther=0
 $brainCandidateTracked=0
 $opaqueHosts=0
 foreach($p in $procs){
  $executable=[string]$p.Name
  if($executable -notmatch '^(python|pythonw|py|powershell|pwsh|cmd)\.exe$'){
   continue
  }
  $cmd=[string]$p.CommandLine
  if([string]::IsNullOrWhiteSpace($cmd)){
   $opaqueHosts++
   continue
  }
  if($cmd.IndexOf("ai_brain_observer.py",
        [StringComparison]::OrdinalIgnoreCase) -lt 0){continue}
  $exact=($executable -match '^(python|pythonw|py)\.exe$' -and
          $cmd.IndexOf($expectedObserver,
           [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
          $cmd.IndexOf($expectedLive,
           [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
          $cmd.IndexOf($expectedStatus,
           [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
          $cmd.Contains("--live") -and $cmd.Contains("--status"))
  if($exact){
   $brainCandidates++
   if($brainPresent -and [int]$p.ProcessId -eq $brainRecorded){
    $brainCandidateTracked++
   }
  }else{
   $brainOther++
  }
 }
 $stage="PORT_INVENTORY"
 $listening=@(Get-NetTCPConnection -State Listen -ErrorAction Stop |
  Where-Object {@(28580,28581,28582,28583,28584) -contains [int]$_.LocalPort})
 $trackedPorts=0
 $possibleBridgePorts=0
 $unknownPorts=0
 foreach($port in $listening){
  $owner=[int]$port.OwningProcess
  $candidate=$byPid[$owner]
  if($trackedPids.Contains($owner)){
   $trackedPorts++
  }elseif($null -ne $candidate -and
           $trackedPids.Contains([int]$candidate.ParentProcessId) -and
           [string]$candidate.Name -match '^(powershell|pwsh)\.exe$'){
   $possibleBridgePorts++
  }else{
   $unknownPorts++
  }
 }
 Write-Output ("AUDIT_TRACKED_LIVE_COUNT="+$liveTracked)
 Write-Output ("AUDIT_TRACKED_SCRIPT_MATCH_COUNT="+$matchedTracked)
 Write-Output ("AUDIT_TRACKED_OWNERSHIP_UNVERIFIED_COUNT="+$unverifiedTracked)
 Write-Output ("AUDIT_BRAIN_FIELD="+$(if($brainPresent){"PRESENT"}else{"LEGACY_MISSING"}))
 Write-Output ("AUDIT_BRAIN_EXACT_CANDIDATE_COUNT="+$brainCandidates)
 Write-Output ("AUDIT_BRAIN_OTHER_SCRIPT_COUNT="+$brainOther)
 Write-Output ("AUDIT_BRAIN_RECORDED_EXACT_COUNT="+$brainCandidateTracked)
 Write-Output ("AUDIT_OPAQUE_SCRIPT_HOSTS="+$opaqueHosts)
 Write-Output ("AUDIT_LISTEN_PORTS="+$listening.Count)
 Write-Output ("AUDIT_PORT_TRACKED_PID="+$trackedPorts)
 Write-Output ("AUDIT_PORT_POSSIBLE_CHILD="+$possibleBridgePorts)
 Write-Output ("AUDIT_PORT_UNVERIFIED="+$unknownPorts)
 Write-Output "AUDIT_RESULT=READ_ONLY_HOLD"
 Write-Output "STATE_FILE_MODIFIED=false"
 Write-Output "STOP_ALLOWED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 0
}catch{
 $message=[string]$_.Exception.Message
 $reason="UNCLASSIFIED"
 $allow=@("UNTRUSTED_ROOT","STATE_ABSENT","UNTRUSTED_STATE",
  "STATE_JSON_INVALID","BRAIN_PID_INVALID","STATE_ROOT_FIELDS_EMPTY",
  "TRACKED_PID_INVALID")
 if($allow -ccontains $message){$reason=$message}
 Write-Output ("AUDIT_BLOCK_STAGE="+$stage)
 Write-Output ("AUDIT_BLOCK_REASON="+$reason)
 Write-Output "AUDIT_RESULT=BLOCKED"
 Write-Output "STATE_FILE_MODIFIED=false"
 Write-Output "STOP_ALLOWED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 2
}
