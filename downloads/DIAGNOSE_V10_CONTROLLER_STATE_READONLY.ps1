<#
P0-24C: independent read-only, privacy-filtered Controller state diagnosis.
No file modifications, process stops, browser, Excel/MS2 interaction or orders.
Reports ONLY enum field names and aggregate counts, never PIDs/paths/content.
#>
param([string]$Root="C:\AI_Cockpit_OneClick_Starter")
$ErrorActionPreference="Stop"
$stage="INIT"
function Block([string]$Why){throw $Why}
function Safe([string]$P){
 $i=Get-Item -LiteralPath $P -ErrorAction Stop
 if(($i.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){
  Block "REPARSE_POINT"
 }
 return $i
}
try{
 $stateRoot=[IO.Path]::GetFullPath($Root)
 [void](Safe $stateRoot)
 $file=Join-Path $stateRoot "V10_CONTROLLER_STATE.json"
 $stage="STATE"
 if(-not (Test-Path -LiteralPath $file -PathType Leaf)){
  Write-Output "STATE_PRESENT=false"
  Write-Output "STATE_SCHEMA=ABSENT"
  Write-Output "DIAG_RESULT=READ_ONLY"
  Write-Output "CUTOVER_ELIGIBLE=false"
  Write-Output "REAL_SUBMIT_ALLOWED=false"
  exit 0
 }
 Write-Output "STATE_PRESENT=true"
 $item=Safe $file
 if($item.PSIsContainer -or $item.Length -lt 2 -or $item.Length -gt 65536){
  Block "STATE_FILE_SIZE_INVALID"
 }
 try{
  $obj=([IO.File]::ReadAllText($file,[Text.Encoding]::UTF8) |
        ConvertFrom-Json -ErrorAction Stop)
 }catch{Block "STATE_JSON_INVALID"}
 if($null -eq $obj -or $obj -isnot [pscustomobject]){
  Block "STATE_JSON_INVALID"
 }
 $required=@("controller_pid","session_id","started_at","repo_root",
  "runtime_dir","brain_observer_pid","excel_pid","collector_pid",
  "watcher_pid","heartbeat_pid","gateway_pid","brain_gateway_pid",
  "voice_bridge_pid","shadow_supervisor_pid","sbv2_pid")
 $pids=@("controller_pid","brain_observer_pid","excel_pid",
  "collector_pid","watcher_pid","heartbeat_pid","gateway_pid",
  "brain_gateway_pid","voice_bridge_pid","shadow_supervisor_pid","sbv2_pid")
 $missing=New-Object 'System.Collections.Generic.List[string]'
 $invalid=New-Object 'System.Collections.Generic.List[string]'
 $tracked=New-Object 'System.Collections.Generic.List[int]'
 foreach($key in $required){
  if($obj.PSObject.Properties.Match($key).Count -ne 1){
   [void]$missing.Add($key)
   continue
  }
  $val=$obj.$key
  if($pids -ccontains $key){
   $pidValue=0
   if(-not [int]::TryParse([string]$val,[ref]$pidValue) -or
      $pidValue -lt 0 -or ($key -ceq "controller_pid" -and $pidValue -eq 0)){
    [void]$invalid.Add($key)
   }elseif($pidValue -gt 0){[void]$tracked.Add($pidValue)}
  }elseif($key -in @("repo_root","runtime_dir","started_at")){
   if([string]::IsNullOrWhiteSpace([string]$val)){
    [void]$invalid.Add($key)
   }elseif($key -ceq "started_at"){
    $dt=[datetime]::MinValue
    if(-not [datetime]::TryParse([string]$val,[ref]$dt)){
     [void]$invalid.Add($key)
    }
   }
  }elseif($key -ceq "session_id"){
   $sid=0
   if(-not [int]::TryParse([string]$val,[ref]$sid) -or $sid -lt 0){
    [void]$invalid.Add($key)
   }
  }
 }
 Write-Output ("MISSING_REQUIRED_COUNT="+$missing.Count)
 foreach($key in $missing){Write-Output ("MISSING_FIELD="+$key)}
 Write-Output ("INVALID_REQUIRED_COUNT="+$invalid.Count)
 foreach($key in $invalid){Write-Output ("INVALID_FIELD="+$key)}
 $schema=if($missing.Count -eq 0 -and $invalid.Count -eq 0){"COMPLETE"}else{"INCOMPLETE"}
 Write-Output ("STATE_SCHEMA="+$schema)
 $stage="PORTS"
 $conn=@(Get-NetTCPConnection -State Listen -ErrorAction Stop)
 $ports=@($conn | Where-Object {
  @(28580,28581,28582,28583,28584) -contains [int]$_.LocalPort
 })
 Write-Output ("COCKPIT_LISTENERS="+$ports.Count)
 $stage="PROCESSES"
 $all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
 $live=0
 foreach($n in $tracked){
  if(@($all | Where-Object {[int]$_.ProcessId -eq $n}).Count -gt 0){
   $live++
  }
 }
 $known=@($all | Where-Object{
  ([string]$_.Name -match '^(powershell|pwsh|cmd|python|pythonw|py)\.exe$') -and
  ([string]$_.CommandLine -match '(?i)AI_COCKPIT_START_DEBUG\.cmd|START_AI_COCKPIT\.ps1|RUN_AI_COCKPIT_V10\.ps1|AI_COCKPIT_CONTROLLER_V10\.ps1|ai_brain_observer\.py|MS2_RSS_100_Collector\.ps1|Kioxia_RSS_Live_Watcher\.ps1|ai_shadow_supervisor\.py|AI_COCKPIT_GATEWAY_V10\.ps1|AI_COCKPIT_VOICE_BRIDGE_V10\.ps1')
 })
 $opaque=@($all | Where-Object{
  ([string]$_.Name -match '^(powershell|pwsh|cmd|python|pythonw|py)\.exe$') -and
  [string]::IsNullOrWhiteSpace([string]$_.CommandLine)
 })
 Write-Output ("RECORDED_PID_ALIVE_COUNT="+$live)
 Write-Output ("KNOWN_COCKPIT_PROCESS_COUNT="+$known.Count)
 Write-Output ("UNINSPECTABLE_SCRIPT_HOST_COUNT="+$opaque.Count)
 Write-Output "STATE_FILE_MODIFIED=false"
 Write-Output "DIAG_RESULT=READ_ONLY"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 0
}catch{
 $reason="UNCLASSIFIED"
 if(@("REPARSE_POINT","STATE_FILE_SIZE_INVALID","STATE_JSON_INVALID") -ccontains
    [string]$_.Exception.Message){$reason=[string]$_.Exception.Message}
 Write-Output ("DIAG_BLOCK_STAGE="+$stage)
 Write-Output ("DIAG_BLOCK_REASON="+$reason)
 Write-Output "DIAG_RESULT=BLOCKED"
 Write-Output "STATE_FILE_MODIFIED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 2
}
