<#
P0-26 legacy STOP admission gate.
Pure read-only. No kill, Excel COM, state moves, Git, broker, network,
working directory change, script execution or sensitive data disclosure.
Never itself authorizes a stop or release cutover.

-AdmissionOut (used only by STOP_V10_LEGACY_SESSION_V1.ps1): additionally
writes one new JSON admission record (PIDs, creation times, roles) to that
path. In this mode a live Excel is recorded as left untouched instead of
vetoed, and a BRAIN observer is admitted only when it is the recorded
Controller's own child with the exact observer identity (plus at most one
venv interpreter child with identical arguments). Without the switch a live
Excel or any BRAIN host still blocks.

Identity is checked on the parsed argument vector (CommandLineToArgvW), never
on a command-line substring: a PowerShell host must run the expected script
as its -File argument, a Python host must run it as its first positional
argument, and a JSON bridge must be a Start-Job child (-s -NoLogo -NoProfile)
of the recorded Collector/Watcher using the same executable.
#>
param([string]$Root="C:\AI_Cockpit_OneClick_Starter",[string]$AdmissionOut="")
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
if(-not ("V10Argv" -as [type])){
 Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class V10Argv {
 [DllImport("shell32.dll", SetLastError=true)]
 static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string cmd, out int n);
 [DllImport("kernel32.dll")]
 static extern IntPtr LocalFree(IntPtr p);
 public static string[] Split(string cmd) {
  int n; IntPtr a = CommandLineToArgvW(cmd, out n);
  if (a == IntPtr.Zero) return new string[0];
  try {
   string[] r = new string[n];
   for (int i = 0; i < n; i++) r[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(a, i * IntPtr.Size));
   return r;
  } finally { LocalFree(a); }
 }
}
"@
}
function Get-Argv($proc){
 $cli=[string]$proc.CommandLine
 if([string]::IsNullOrWhiteSpace($cli)){return @()}
 return @([V10Argv]::Split($cli))
}
function Same-Path([string]$A,[string]$B){
 if([string]::IsNullOrWhiteSpace($A) -or [string]::IsNullOrWhiteSpace($B)){return $false}
 try{return [string]::Equals([IO.Path]::GetFullPath($A),[IO.Path]::GetFullPath($B),
  [StringComparison]::OrdinalIgnoreCase)}catch{return $false}
}
# The script a host actually runs: -File operand for PowerShell, first
# positional argument for Python. Text elsewhere on the line never counts.
function Get-ScriptOperand([string[]]$Argv,[string]$Kind){
 if($Kind -eq "ps1"){
  for($i=1;$i -lt $Argv.Count-1;$i++){ if($Argv[$i] -ieq "-File"){return $Argv[$i+1]} }
  return $null
 }
 for($i=1;$i -lt $Argv.Count;$i++){ if(-not $Argv[$i].StartsWith("-")){return $Argv[$i]} }
 return $null
}
function Verify-Process($proc,[string]$ExpectedLeaf,[string[]]$ExpectedFull,[datetime]$MinUtc){
 if($null -eq $proc){return $false}
 try{
  $pidNum=[int]$proc.ProcessId
  $object=Get-Process -Id $pidNum -ErrorAction Stop
  $handle=$object.Handle
  if($handle -eq [IntPtr]::Zero -or $object.HasExited){return $false}
  $info=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$pidNum) -ErrorAction Stop
  if($null -eq $info -or [int]$info.ProcessId -ne $pidNum){return $false}
  $kind=if($ExpectedLeaf -match '\.ps1$'){"ps1"}else{"py"}
  $operand=Get-ScriptOperand (Get-Argv $info) $kind
  if([string]::IsNullOrWhiteSpace($operand)){return $false}
  $full=@($ExpectedFull | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
  if($full.Count -gt 0){
   if(@($full | Where-Object { Same-Path $operand $_ }).Count -eq 0){return $false}
  }elseif(-not ([IO.Path]::GetFileName($operand) -ieq $ExpectedLeaf)){
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
  if($kind -eq "ps1"){
   if($exe -notmatch '^(powershell|pwsh)\.exe$'){return $false}
  }else{
   if($exe -notmatch '^(python|pythonw|py)\.exe$'){return $false}
  }
  return $true
 }catch {return $false}
}
# A venv python.exe redirector re-launches the base interpreter with the
# same arguments; that one child belongs to the same managed host.
# Collector Start-Job -InitializationScript adds -EncodedCommand (UTF16-LE).
# An arbitrary EncodedCommand is never sufficient for admission: reconstruct
# the exact initialization text from the four parsed Collector functions.
# No source function or decoded command is executed or displayed.
function Test-CollectorEncodedInitJob($Child,[string]$CollectorPath) {
 try {
  if([string]::IsNullOrWhiteSpace($CollectorPath)){return $false}
  $file=Get-Item -LiteralPath $CollectorPath -ErrorAction Stop
  if($file.PSIsContainer -or (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) -or
     $file.Length -lt 100 -or $file.Length -gt 400000){return $false}
  $a=@(Get-Argv $Child)
  if($a.Count -eq 8 -and $a[1] -ieq "-Version" -and
     $a[2] -match '^\d+(\.\d+){0,3}$'){
   $a=@($a[0]) + @($a | Select-Object -Skip 3)
  }
  if($a.Count -ne 6 -or $a[1] -ine "-s" -or $a[2] -ine "-NoLogo" -or
     $a[3] -ine "-NoProfile" -or $a[4] -ine "-EncodedCommand" -or
     [string]::IsNullOrWhiteSpace($a[5]) -or $a[5].Length -gt 150000 -or
     $a[5] -cnotmatch '^[A-Za-z0-9+/]+={0,2}$'){return $false}
  $bytes=[Convert]::FromBase64String($a[5])
  if($bytes.Length -lt 64 -or $bytes.Length -gt 100000 -or ($bytes.Length % 2) -ne 0){return $false}
  $decoded=[Text.Encoding]::Unicode.GetString($bytes)
  if($decoded.IndexOf([char]0) -ge 0){return $false}
  $t=$null;$errors=$null
  $ast=[Management.Automation.Language.Parser]::ParseFile($CollectorPath,[ref]$t,[ref]$errors)
  if($null -eq $ast -or $errors.Count -ne 0){return $false}
  $names=@("Get-NormalizedLocalWorkbookPath","Get-CollectorFileIdentityType",
           "Test-SameCanonicalWorkbookFile","Get-PublishedWorkbookGate")
  $expected=""
  foreach($name in $names){
   $found=@($ast.FindAll({
     param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
       [string]::Equals($n.Name,$name,[StringComparison]::Ordinal)
   },$true))
   if($found.Count -ne 1){return $false}
   $inner=$found[0].Body.GetScriptBlock().ToString()
   $expected+="function "+$name+" {`r`n"+$inner+"`r`n}`r`n"
  }
  return [string]::Equals($decoded,$expected,[StringComparison]::Ordinal)
 } catch {return $false}
}
function Get-VenvChild($Parent,$All){
 $pa=@(Get-Argv $Parent)
 $kids=@($All | Where-Object { [int]$_.ParentProcessId -eq [int]$Parent.ProcessId -and
  [string]$_.Name -match '^(python|pythonw)\.exe$' })
 if($kids.Count -eq 0){return $null}
 if($kids.Count -gt 1){Refuse "TRACKED_PROCESS_IDENTITY_NOT_PROVEN"}
 $ka=@(Get-Argv $kids[0])
 if($ka.Count -ne $pa.Count -or $pa.Count -lt 2){Refuse "TRACKED_PROCESS_IDENTITY_NOT_PROVEN"}
 for($i=1;$i -lt $pa.Count;$i++){ if($ka[$i] -cne $pa[$i]){Refuse "TRACKED_PROCESS_IDENTITY_NOT_PROVEN"} }
 if(([datetime]$kids[0].CreationDate) -lt ([datetime]$Parent.CreationDate)){Refuse "TRACKED_PROCESS_IDENTITY_NOT_PROVEN"}
 return $kids[0]
}
function New-Entry([string]$Role,$Proc){
 return [ordered]@{role=$Role;pid=[int]$Proc.ProcessId;
  created_utc_ticks=([datetime]$Proc.CreationDate).ToUniversalTime().Ticks;exe=[string]$Proc.Name}
}
try{
 $admit=-not [string]::IsNullOrWhiteSpace($AdmissionOut)
 if($admit){
  $admitPath=[IO.Path]::GetFullPath($AdmissionOut)
  if((Test-Path -LiteralPath $admitPath) -or
     -not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($admitPath)) -PathType Container)){
   Refuse "ADMISSION_OUT_INVALID"
  }
 }
 $stateRootPath=[IO.Path]::GetFullPath($Root)
 $rootObj=Get-Item -LiteralPath $stateRootPath -ErrorAction Stop
 if(-not $rootObj.PSIsContainer -or
    (($rootObj.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)){
  Refuse "UNTRUSTED_ROOT"
 }
 $path=Join-Path $stateRootPath "V10_CONTROLLER_STATE.json"
 if(-not (Test-Path -LiteralPath $path -PathType Leaf)){Refuse "STATE_MISSING"}
 $body=Read-UniquePlainFile $path
 $sha=[Security.Cryptography.SHA256]::Create()
 try{$stateHash=([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($path)))).Replace("-","")}finally{$sha.Dispose()}
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
 $brainRecord=$null
 $brainChild=$null
 if($candidate.Count -gt 0){
  # Admission mode only: exactly one observer that is the recorded
  # Controller's own child with the exact launch identity, optionally plus
  # its venv interpreter child. Anything else is an unproven BRAIN.
  $ctlPid=0
  if(-not $admit -or $candidate.Count -gt 2 -or
     -not [int]::TryParse([string]$s.controller_pid,[ref]$ctlPid) -or $ctlPid -le 0){
   Refuse "UNTRACKED_BRAIN_CANDIDATE"
  }
  $rootBrain=@($candidate | Where-Object { [int]$_.ParentProcessId -eq $ctlPid })
  if($rootBrain.Count -ne 1){Refuse "UNTRACKED_BRAIN_CANDIDATE"}
  $ba=@(Get-Argv $rootBrain[0])
  $liveArg=$null
  for($i=1;$i -lt $ba.Count-1;$i++){ if($ba[$i] -ceq "--live"){$liveArg=$ba[$i+1]} }
  if(-not (Same-Path $liveArg (Join-Path $runtime "live_ms2.json")) -or
     -not (Verify-Process $rootBrain[0] "ai_brain_observer.py" @((Join-Path $repo "scripts\ai_brain_observer.py")) $since)){
   Refuse "UNTRACKED_BRAIN_CANDIDATE"
  }
  $brainRecord=New-Entry "brain_observer" $rootBrain[0]
  if($candidate.Count -eq 2){
   try{$brainChild=Get-VenvChild $rootBrain[0] $candidate}catch{Refuse "UNTRACKED_BRAIN_CANDIDATE"}
   if($null -eq $brainChild){Refuse "UNTRACKED_BRAIN_CANDIDATE"}
  }
 }
 $currentSession=(Get-Process -Id $PID -ErrorAction Stop).SessionId
 $members=New-Object System.Collections.ArrayList
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
  $match=Verify-Process $byPid[$tracked] $leaf @($pathPart) $since
  if($key -eq "controller_pid"){
   if(-not $match){
    # Controller runs inside the RUN_AI_COCKPIT_V10 host started by the
    # V10 starter; only that exact script as -File operand is accepted.
    # That host predates the Controller's recorded start by its setup time.
    $match=Verify-Process $byPid[$tracked] "RUN_AI_COCKPIT_V10.ps1" @(
     (Join-Path $repo "downloads\RUN_AI_COCKPIT_V10.ps1"),
     (Join-Path $stateRootPath "RUN_AI_COCKPIT_V10.ps1")) $since.AddMinutes(-15)
   }
  }
  if(-not $match){Refuse "TRACKED_PROCESS_IDENTITY_NOT_PROVEN"}
  [void]$members.Add((New-Entry $key $byPid[$tracked]))
  if($leaf -match '\.py$'){
   $venv=Get-VenvChild $byPid[$tracked] $processes
   if($null -ne $venv){
    if(-not $expectedCohort.Add([int]$venv.ProcessId)){Refuse "DUPLICATED_TRACKED_PID"}
    [void]$members.Add((New-Entry "venv_child" $venv))
   }
  }
  $admitted++
 }
 if($null -ne $brainChild){
  if($expectedCohort.Contains([int]$brainChild.ProcessId)){Refuse "DUPLICATED_TRACKED_PID"}
  [void]$members.Add((New-Entry "brain_venv_child" $brainChild))
 }
 $excelPid=0
 if(-not [int]::TryParse([string]$s.excel_pid,[ref]$excelPid) -or $excelPid -lt 0){
  Refuse "EXCEL_PID_INVALID"
 }
 $excelLive=($excelPid -gt 0 -and $byPid.ContainsKey($excelPid))
 # Don't touch any Excel process, including the managed workbook: a
 # separate Excel COM/HWND admission gate is required before destructive stop.
 # Admission mode records it as left untouched; STOP never closes Excel.
 if($excelLive -and -not $admit){Refuse "EXCEL_PROCESS_STILL_ALIVE"}
 if($excelPid -gt 0 -and ($expectedCohort.Contains($excelPid) -or
    ($null -ne $brainRecord -and [int]$brainRecord.pid -eq $excelPid))){
  Refuse "EXCEL_PID_COLLIDES_WITH_WORKER"
 }
 if($null -ne $brainRecord -and $expectedCohort.Contains([int]$brainRecord.pid)){
  Refuse "DUPLICATED_TRACKED_PID"
 }
 $stage="PORTS"
 $listeners=@(Get-NetTCPConnection -State Listen -ErrorAction Stop |
  Where-Object { @(28580,28581,28582,28583,28584) -contains [int]$_.LocalPort })
 $ownedPorts=0
 $childPorts=0
 $bridges=New-Object System.Collections.ArrayList
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
  # Only a Start-Job JSON bridge: same PowerShell executable as its parent
  # and exactly the job-host arguments, nothing else on its command line
  # (PS5.1 writes "-Version 5.1 -s -NoLogo -NoProfile").
  $jobArgv=@(Get-Argv $child | Select-Object -Skip 1 | ForEach-Object { $_.ToLowerInvariant() })
  if($jobArgv.Count -eq 5 -and $jobArgv[0] -ceq "-version" -and $jobArgv[1] -cmatch '^\d+(\.\d+){0,3}$'){
   $jobArgv=@($jobArgv | Select-Object -Skip 2)
  }
  $jobArgs=@($jobArgv | Sort-Object)
  $jobExact=(($jobArgs -join " ") -ceq "-nologo -noprofile -s")
  $collectorInitExact=$false
  if(-not $jobExact -and $parentId -eq [int]$s.collector_pid){
   $collectorInitExact=Test-CollectorEncodedInitJob $child (Join-Path $runtime "MS2_RSS_100_Collector.ps1")
  }
  if(-not (Same-Path ([string]$child.ExecutablePath) ([string]$parent.ExecutablePath)) -or
     -not ($jobExact -or $collectorInitExact)){
   Refuse "PORT_CHILD_IDENTITY_NOT_PROVEN"
  }
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
  $entry=New-Entry "bridge_child" $child
  $entry.port=[int]$port.LocalPort
  $entry.parent_pid=$parentId
  [void]$bridges.Add($entry)
  $childPorts++
 }
 if($admit){
  $stage="ADMISSION"
  $record=[ordered]@{schema="V10_LEGACY_STOP_ADMISSION_V1";state_sha256=$stateHash;
   members=@($members);bridges=@($bridges);brain=$brainRecord;
   brain_status=$(if($null -eq $brainRecord){"ABSENT_VERIFIED"}else{"OWNED_CHILD_ADMITTED"});
   excel_pid=$excelPid;excel_live=[bool]$excelLive;excel_action="NONE"}
  $json=ConvertTo-Json -Depth 6 -Compress $record
  $tmp=$admitPath+".tmp"
  [IO.File]::WriteAllText($tmp,$json,(New-Object Text.UTF8Encoding($false)))
  [IO.File]::Move($tmp,$admitPath)
 }
 Write-Output "LEGACY_STATE_SCHEMA=COMPATIBLE"
 Write-Output ("TRACKED_LIVE_EXACT="+$admitted)
 Write-Output ("LISTENER_DIRECT="+$ownedPorts)
 Write-Output ("LISTENER_CHILD_VERIFIED="+$childPorts)
 Write-Output "UNTRACKED_BRAIN_CANDIDATES=0"
 if($admit){
  Write-Output ("BRAIN_STATUS="+$(if($null -eq $brainRecord){"ABSENT_VERIFIED"}else{"OWNED_CHILD_ADMITTED"}))
  Write-Output ("MANAGED_EXCEL_LIVE="+([string][bool]$excelLive).ToLowerInvariant())
  Write-Output "EXCEL_ACTION=NONE"
  Write-Output "ADMISSION_RECORD=WRITTEN"
 }else{
  Write-Output "MANAGED_EXCEL_LIVE=false"
 }
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
  "PORT_CHILD_IDENTITY_NOT_PROVEN","PORT_PARENT_NOT_FOUND",
  "ADMISSION_OUT_INVALID","EXCEL_PID_COLLIDES_WITH_WORKER")
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
