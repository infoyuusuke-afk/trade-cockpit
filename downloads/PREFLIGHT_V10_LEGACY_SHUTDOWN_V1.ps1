<#
P0-26 legacy STOP admission gate.
Pure read-only. No kill, Excel COM, state moves, Git, broker, network,
working directory change, script execution or sensitive data disclosure.
Never itself authorizes a stop or release cutover.
#>
param([string]$Root="C:\AI_Cockpit_OneClick_Starter")
$ErrorActionPreference="Stop"
$stage="ROOT"
function Refuse([string]$Reason){ throw $Reason }
function Read-UniquePlainFile([string]$P){
 $obj=Get-Item -LiteralPath $P -ErrorAction Stop
 if($obj.PSIsContainer -or
    (($obj.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) -or
    $obj.Length -lt 3 -or $obj.Length -gt 65536){Refuse "UNTRUSTED_STATE_FILE"}
 return [IO.File]::ReadAllText($P,[Text.Encoding]::UTF8)
}
function Is-OpaqueHost($obj) {
 return ([string]$obj.Name -match '^(powershell|pwsh|cmd|python|pythonw|py)\.exe$' -and
    [string]::IsNullOrWhiteSpace([string]$obj.CommandLine))
}
function Verify-Process($proc,[string]$ExpectedLeaf,[string]$ExpectedFull,[datetime]$MinUtc){
 if($null -eq $proc){return $false}
 try{
  $pidNum=[int]$proc.ProcessId
  $object=Get-Process -Id $pidNum -ErrorAction Stop
  $handle=$object.Handle
  if($handle -eq [IntPtr]::Zero -or $object.HasExited){return $false}
  $info=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$pidNum) -ErrorAction Stop
  if($null -eq $info -or [int]$info.ProcessId -ne $pidNum){return $false}
  $cli=[string]$info.CommandLine
  if([string]::IsNullOrWhiteSpace($cli) -or
     $cli.IndexOf($ExpectedLeaf,[StringComparison]::OrdinalIgnoreCase) -lt 0){
   return $false
  }
  if(-not [string]::IsNullOrWhiteSpace($ExpectedFull) -and
     $cli.IndexOf($ExpectedFull,[StringComparison]::OrdinalIgnoreCase) -lt 0){
   return $false
  }
  $when=$object.StartTime.ToUniversalTime()
  $cimDate=([datetime]$info.CreationDate).ToUniversalTime()
  if([Math]::Abs(($when-$cimDate).TotalSeconds) -gt 2 -or
     $when -lt $MinUtc.AddSeconds(-30) -or
     $object.SessionId -ne (Get-Process -Id $PID -ErrorAction Stop).SessionId){
   return $false
  }
  $exe=[string]$info.Name
  if($ExpectedLeaf -match '\.ps1$'){
   if($exe -notmatch '^(powershell|pwsh)\.exe$'){return $false}
  }elseif($ExpectedLeaf -match '\.py$'){
   if($exe -notmatch '^(python|pythonw|py)\.exe$'){return $false}
  }
  return $true
 }catch {return $false}
}
try{
 $home=[IO.Path]::GetFullPath($Root)
 $rootObj=Get-Item -LiteralPath $home -ErrorAction Stop
 if(-not $rootObj.PSIsContainer -or
    (($rootObj.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)){
  Refuse "UNTRUSTED_ROOT"
 }
 $path=Join-Path $home "V10_CONTROLLER_STATE.json"
 if(-not (Test-Path -LiteralPath $path -PathType Leaf)){Refuse "STATE_MISSING"}
 $body=Read-UniquePlainFile $path
 $s=$body | ConvertFrom-Json -ErrorAction Stop
 if($null -eq $s -or $s -isnot [pscustomobject]){Refuse "STATE_JSON_INVALID"}
 $stage="STATE_SCHEMA"
 # This compatibility preflight is specifically for the OWNER's historical
 # state. A new state with BRAIN PID must use the new normal Stop path.
 if($s.PSObject.Properties.Match("brain_observer_pid").Count -ne 0){
  Refuse "NOT_A_LEGACY_STATE"
 }
 $required=@("controller_pid","session_id","started_at","repo_root","runtime_dir",
  "excel_pid","watcher_pid","heartbeat_pid","collector_pid","gateway_pid",
  "brain_gateway_pid","voice_bridge_pid","sbv2_pid","shadow_supervisor_pid")
 foreach($k in $required){
  if($s.PSObject.Properties.Match($k).Count -ne 1){Refuse "STATE_SCHEMA_INCOMPLETE"}
 }
 if([string]::IsNullOrWhiteSpace([string]$s.repo_root) -or
    [string]::IsNullOrWhiteSpace([string]$s.runtime_dir)){
  Refuse "STATE_ROOT_INVALID"
 }
 $repo=[IO.Path]::GetFullPath([string]$s.repo_root)
 $runtime=[IO.Path]::GetFullPath([string]$s.runtime_dir)
 $started=[datetime]::MinValue
 if(-not [datetime]::TryParse([string]$s.started_at,[ref]$started)){
  Refuse "STATE_TIME_INVALID"
 }
 $since=$started.ToUniversalTime()
 $scriptMap=[ordered]@{
  controller_pid=@("AI_COCKPIT_CONTROLLER_V10.ps1",(Join-Path $repo "downloads\AI_COCKPIT_CONTROLLER_V10.ps1"))
  watcher_pid=@("Kioxia_RSS_Live_Watcher.ps1",(Join-Path $runtime "Kioxia_RSS_Live_Watcher.ps1"))
  heartbeat_pid=@("Kioxia_Safety_Heartbeat.ps1",(Join-Path $runtime "Kioxia_Safety_Heartbeat.ps1"))
  collector_pid=@("MS2_RSS_100_Collector.ps1",(Join-Path $runtime "MS2_RSS_100_Collector.ps1"))
  gateway_pid=@("AI_COCKPIT_GATEWAY_V10.ps1",(Join-Path $repo "downloads\AI_COCKPIT_GATEWAY_V10.ps1"))
  brain_gateway_pid=@("AI_COCKPIT_GATEWAY_V10.ps1",(Join-Path $repo "downloads\AI_COCKPIT_GATEWAY_V10.ps1"))
  voice_bridge_pid=@("AI_COCKPIT_VOICE_BRIDGE_V10.ps1",(Join-Path $repo "downloads\AI_COCKPIT_VOICE_BRIDGE_V10.ps1"))
  sbv2_pid=@("server_fastapi.py","")
  shadow_supervisor_pid=@("ai_shadow_supervisor.py",(Join-Path $repo "scripts\ai_shadow_supervisor.py"))
 }
 $stage="INVENTORY"
 $processes=@(Get-CimInstance Win32_Process -ErrorAction Stop)
 $byPid=@{}
 foreach($proc in $processes){$byPid[[int]$proc.ProcessId]=$proc}
 $opaque=@($processes | Where-Object { Is-OpaqueHost $_ })
 # A hidden observer could be a Python launcher with no readable CLI.
 if($opaque.Count -gt 0){Refuse "OPAQUE_SCRIPT_HOST_PRESENT"}
 $candidate=@($processes | Where-Object{
  ([string]$_.Name -match '^(python|pythonw|py|powershell|pwsh|cmd)\.exe$') -and
  ([string]$_.CommandLine).IndexOf("ai_brain_observer.py",
     [StringComparison]::OrdinalIgnoreCase) -ge 0
 })
 if($candidate.Count -gt 0){Refuse "UNTRACKED_BRAIN_CANDIDATE"}
 $currentSession=(Get-Process -Id $PID -ErrorAction Stop).SessionId
 $expectedCohort=New-Object 'System.Collections.Generic.HashSet[int]'
 $admitted=0
 $live=0
 foreach($key in @("controller_pid","watcher_pid","heartbeat_pid","collector_pid",
  "gateway_pid","brain_gateway_pid","voice_bridge_pid","sbv2_pid",
  "shadow_supervisor_pid")){
  $tracked=0
  if(-not [int]::TryParse([string]$s.$key,[ref]$tracked) -or $tracked -lt 0){
   Refuse "TRACKED_PID_INVALID"
  }
  if($key -eq "controller_pid" -and $tracked -le 0){Refuse "CONTROLLER_PID_MISSING"}
  if($tracked -eq 0){continue}
  if(-not $expectedCohort.Add($tracked)){Refuse "DUPLICATED_TRACKED_PID"}
  if(-not $byPid.ContainsKey($tracked)){continue}
  $live++
  $leaf=[string]$scriptMap[$key][0]
  $pathPart=[string]$scriptMap[$key][1]
  $match=Verify-Process $byPid[$tracked] $leaf $pathPart $since
  if($key -eq "controller_pid" -and -not $match){
   # Controller is invoked inside RUN_AI_COCKPIT_V10 PowerShell host.
   $match=Verify-Process $byPid[$tracked] "RUN_AI_COCKPIT_V10.ps1" "" $since
  }
  if(-not $match){Refuse "TRACKED_PROCESS_IDENTITY_NOT_PROVEN"}
  $admitted++
 }
 $excelPid=0
 if(-not [int]::TryParse([string]$s.excel_pid,[ref]$excelPid) -or $excelPid -lt 0){
  Refuse "EXCEL_PID_INVALID"
 }
 $excelLive=($excelPid -gt 0 -and $byPid.ContainsKey($excelPid))
 # Don't touch any Excel process, including the managed workbook: a
 # separate Excel COM/HWND admission gate is required before destructive stop.
 if($excelLive){Refuse "EXCEL_PROCESS_STILL_ALIVE"}
 $stage="PORTS"
 $listeners=@(Get-NetTCPConnection -State Listen -ErrorAction Stop |
  Where-Object { @(28580,28581,28582,28583,28584) -contains [int]$_.LocalPort })
 $ownedPorts=0
 $childPorts=0
 foreach($port in $listeners){
  $n=[int]$port.OwningProcess
  if($expectedCohort.Contains($n)){
   $ownedPorts++
   continue
  }
  $child=$byPid[$n]
  if($null -eq $child){Refuse "PORT_PROCESS_NOT_FOUND"}
  $parentId=[int]$child.ParentProcessId
  if(-not $expectedCohort.Contains($parentId) -or
     ([int]$parentId -ne [int]$s.collector_pid -and
      [int]$parentId -ne [int]$s.watcher_pid) -or
     [string]$child.Name -notmatch '^(powershell|pwsh)\.exe$'){
   Refuse "PORT_CHILD_IDENTITY_NOT_PROVEN"
  }
  $parent=$byPid[$parentId]
  if($null -eq $parent){Refuse "PORT_PARENT_NOT_FOUND"}
  $parentBirth=([datetime]$parent.CreationDate).ToUniversalTime()
  $childBirth=([datetime]$child.CreationDate).ToUniversalTime()
  if($childBirth -lt $parentBirth.AddSeconds(-2) -or
     [string]::IsNullOrWhiteSpace([string]$child.CommandLine)){
   Refuse "PORT_CHILD_IDENTITY_NOT_PROVEN"
  }
  $parentProc=Get-Process -Id $parentId -ErrorAction Stop
  $childProc=Get-Process -Id $n -ErrorAction Stop
  if($parentProc.SessionId -ne $currentSession -or
     $childProc.SessionId -ne $currentSession -or
     [Math]::Abs(($parentProc.StartTime.ToUniversalTime()-$parentBirth).TotalSeconds) -gt 2 -or
     [Math]::Abs(($childProc.StartTime.ToUniversalTime()-$childBirth).TotalSeconds) -gt 2){
   Refuse "PORT_CHILD_IDENTITY_NOT_PROVEN"
  }
  $childPorts++
 }
 Write-Output "LEGACY_STATE_SCHEMA=COMPATIBLE"
 Write-Output ("TRACKED_LIVE_EXACT="+$admitted)
 Write-Output ("LISTENER_DIRECT="+$ownedPorts)
 Write-Output ("LISTENER_CHILD_VERIFIED="+$childPorts)
 Write-Output "UNTRACKED_BRAIN_CANDIDATES=0"
 Write-Output "MANAGED_EXCEL_LIVE=false"
 Write-Output "PREFLIGHT_RESULT=EVIDENCE_ONLY_PASS"
 Write-Output "STOP_ALLOWED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 0
}catch{
 $known=@("UNTRUSTED_STATE_FILE","UNTRUSTED_ROOT","STATE_MISSING",
  "STATE_JSON_INVALID","NOT_A_LEGACY_STATE","STATE_SCHEMA_INCOMPLETE",
  "STATE_ROOT_INVALID","STATE_TIME_INVALID","OPAQUE_SCRIPT_HOST_PRESENT",
  "UNTRACKED_BRAIN_CANDIDATE","TRACKED_PID_INVALID","CONTROLLER_PID_MISSING",
  "DUPLICATED_TRACKED_PID","TRACKED_PROCESS_IDENTITY_NOT_PROVEN",
  "EXCEL_PID_INVALID","EXCEL_PROCESS_STILL_ALIVE","PORT_PROCESS_NOT_FOUND",
  "PORT_CHILD_IDENTITY_NOT_PROVEN","PORT_PARENT_NOT_FOUND")
 $why=if($known -ccontains [string]$_.Exception.Message){
  [string]$_.Exception.Message
 }else{"UNVERIFIED"}
 Write-Output ("PREFLIGHT_BLOCK_STAGE="+$stage)
 Write-Output ("PREFLIGHT_BLOCK_REASON="+$why)
 Write-Output "PREFLIGHT_RESULT=BLOCKED"
 Write-Output "STOP_ALLOWED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 2
}
