<#
P0-28: OWNER-PC read-only attribution diagnosis for blocked P0-27 ports.
No process stop/start, COM, broker request, state writes, or launch changes.
Only predefined status enums / port numbers / counts are printed.
This is NOT an admission or safe-stop authority. STOP_ALLOWED remains false.
#>
param([string]$Root="C:\AI_Cockpit_OneClick_Starter")
$ErrorActionPreference="Stop"
$ports=@(28580,28581,28582,28583,28584)
$phase="INPUT"
$result="BLOCKED"
$reason="UNVERIFIED"
$changed=$false
$details=@{}
$script:HostArgvTypeReady=$false

function Refuse([string]$Code) { throw $Code }
function Hash-Bytes([byte[]]$Bytes) {
 $sha=[Security.Cryptography.SHA256]::Create()
 try {return [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace("-","")}
 finally {$sha.Dispose()}
}
function Process-Snapshot($Pids,$Map) {
 $items=New-Object System.Collections.ArrayList
 foreach($n in @($Pids | Sort-Object -Unique)) {
  if(-not $Map.ContainsKey([int]$n)) {
   [void]$items.Add(([string]$n)+":MISSING")
  } else {
   $p=$Map[[int]$n]
   [void]$items.Add(([string]$n)+":"+([string]$p.CreationDate)+":"+([string]$p.ParentProcessId))
  }
 }
 return (($items | Sort-Object) -join ";")
}
function Listener-Snapshot {
 $list=@(Get-NetTCPConnection -State Listen -ErrorAction Stop |
  Where-Object { $ports -contains [int]$_.LocalPort })
 return ,$list
}
function Listener-Identity($Listeners) {
 return ((@($Listeners | ForEach-Object {
  ([string]$_.LocalAddress)+":"+([string]$_.LocalPort)+":"+([string]$_.OwningProcess)
 } | Sort-Object)) -join ";")
}
function Same-Path([string]$A,[string]$B) {
 if([string]::IsNullOrWhiteSpace($A) -or [string]::IsNullOrWhiteSpace($B)){return $false}
 try {
  return [string]::Equals([IO.Path]::GetFullPath($A),[IO.Path]::GetFullPath($B),
      [StringComparison]::OrdinalIgnoreCase)
 } catch {return $false}
}
function Args($Proc) {
 if(-not $script:HostArgvTypeReady) {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class P028Argv {
 [DllImport("shell32.dll", SetLastError=true)]
 static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string cmd, out int n);
 [DllImport("kernel32.dll")]
 static extern IntPtr LocalFree(IntPtr p);
 public static string[] Split(string cmd) {
  int n;
  IntPtr a=CommandLineToArgvW(cmd,out n);
  if(a==IntPtr.Zero)return new string[0];
  try {
   string[] r=new string[n];
   for(int i=0;i<n;i++)r[i]=Marshal.PtrToStringUni(Marshal.ReadIntPtr(a,i*IntPtr.Size));
   return r;
  } finally { LocalFree(a); }
 }
}
"@ -ErrorAction Stop
  $script:HostArgvTypeReady=$true
 }
 if([string]::IsNullOrWhiteSpace([string]$Proc.CommandLine)){return @()}
 return ,@([P028Argv]::Split([string]$Proc.CommandLine))
}
function Classify($Listener,$Tracked,$Map,$Session) {
 $pidNum=[int]$Listener.OwningProcess
 if(-not $Map.ContainsKey($pidNum)) {
  return @{Status="UNVERIFIED";Reason="PORT_PROCESS_NOT_FOUND"}
 }
 $child=$Map[$pidNum]
 if($Tracked.Contains($pidNum)) {
  # Recorded state membership only: still does not grant kill authority.
  return @{Status="TRACKED_RECORDED";Reason="NONE"}
 }
 $parentId=[int]$child.ParentProcessId
 if(-not ($Tracked.Contains($parentId)) -or
    -not (@([int]$script:CollectorPid,[int]$script:WatcherPid) -contains $parentId)) {
  return @{Status="UNVERIFIED";Reason="PARENT_NOT_COLLECTOR_OR_WATCHER"}
 }
 if(-not $Map.ContainsKey($parentId)) {
  return @{Status="UNVERIFIED";Reason="PORT_PARENT_NOT_FOUND"}
 }
 $parent=$Map[$parentId]
 if([string]$child.Name -notmatch '^(powershell|pwsh)\.exe$') {
  return @{Status="UNVERIFIED";Reason="HOST_EXE_NOT_POWERSHELL"}
 }
 if(-not (Same-Path ([string]$child.ExecutablePath) ([string]$parent.ExecutablePath))) {
  return @{Status="UNVERIFIED";Reason="EXECUTABLE_PATH_MISMATCH"}
 }
 try {
  $argv=@(Args $child)
  if($argv.Count -lt 2) {
   return @{Status="UNVERIFIED";Reason="START_JOB_ARGV_MISMATCH"}
  }
  $rest=@($argv | Select-Object -Skip 1 | ForEach-Object { $_.ToLowerInvariant() })
  if($rest.Count -eq 5 -and $rest[0] -ceq "-version" -and
     $rest[1] -cmatch '^\d+(\.\d+){0,3}$') {
   $rest=@($rest | Select-Object -Skip 2)
  }
  if((@($rest | Sort-Object) -join " ") -cne "-nologo -noprofile -s") {
   return @{Status="UNVERIFIED";Reason="START_JOB_ARGV_MISMATCH"}
  }
  $parentBirth=([datetime]$parent.CreationDate).ToUniversalTime()
  $childBirth=([datetime]$child.CreationDate).ToUniversalTime()
  if($childBirth -lt $parentBirth.AddSeconds(-2)) {
   return @{Status="UNVERIFIED";Reason="PROCESS_CREATION_TIME_MISMATCH"}
  }
  $parentProc=Get-Process -Id $parentId -ErrorAction Stop
  $childProc=Get-Process -Id $pidNum -ErrorAction Stop
  if($parentProc.HasExited -or $childProc.HasExited) {
   return @{Status="UNVERIFIED";Reason="PROCESS_DISAPPEARED"}
  }
  if($parentProc.SessionId -ne $Session -or $childProc.SessionId -ne $Session) {
   return @{Status="UNVERIFIED";Reason="SESSION_MISMATCH"}
  }
  if([Math]::Abs(($parentProc.StartTime.ToUniversalTime()-$parentBirth).TotalSeconds) -gt 2 -or
     [Math]::Abs(($childProc.StartTime.ToUniversalTime()-$childBirth).TotalSeconds) -gt 2) {
   return @{Status="UNVERIFIED";Reason="PROCESS_CREATION_TIME_MISMATCH"}
  }
  return @{Status="JOB_BRIDGE_VERIFIED";Reason="NONE"}
 } catch {
  return @{Status="UNVERIFIED";Reason="PROCESS_INSPECTION_UNAVAILABLE"}
 }
}

try {
 $phase="ENVIRONMENT"
 if([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    $PSVersionTable.PSVersion.Major -ne 5 -or
    [string]$PSVersionTable.PSEdition -cne "Desktop") { Refuse "UNSUPPORTED_ENVIRONMENT" }
 $phase="STATE"
 if(-not [IO.Path]::IsPathRooted($Root) -or $Root.StartsWith("\\")) { Refuse "UNTRUSTED_ROOT" }
 $rootFull=[IO.Path]::GetFullPath($Root)
 $ri=Get-Item -LiteralPath $rootFull -ErrorAction Stop
 if(-not $ri.PSIsContainer -or ($ri.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
  Refuse "UNTRUSTED_ROOT"
 }
 $statePath=Join-Path $rootFull "V10_CONTROLLER_STATE.json"
 $si=Get-Item -LiteralPath $statePath -ErrorAction Stop
 if($si.PSIsContainer -or ($si.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    $si.Length -lt 2 -or $si.Length -gt 65536) { Refuse "UNTRUSTED_STATE" }
 $raw=[IO.File]::ReadAllBytes($statePath)
 $hash=Hash-Bytes $raw
 $state=([Text.Encoding]::UTF8.GetString($raw) | ConvertFrom-Json -ErrorAction Stop)
 if($null -eq $state -or $state -isnot [pscustomobject]) { Refuse "INVALID_STATE" }
 $script:CollectorPid=0; $script:WatcherPid=0
 if(-not [int]::TryParse([string]$state.collector_pid,[ref]$script:CollectorPid) -or
    -not [int]::TryParse([string]$state.watcher_pid,[ref]$script:WatcherPid) -or
    $script:CollectorPid -le 0 -or $script:WatcherPid -le 0) { Refuse "INVALID_TRACKED_PIDS" }
 $tracked=New-Object 'System.Collections.Generic.HashSet[int]'
 foreach($key in @("controller_pid","collector_pid","watcher_pid","heartbeat_pid",
                   "gateway_pid","brain_gateway_pid","voice_bridge_pid","sbv2_pid",
                   "shadow_supervisor_pid","brain_observer_pid")) {
  if($state.PSObject.Properties.Match($key).Count -eq 0){continue}
  $value=0
  if(-not [int]::TryParse([string]$state.$key,[ref]$value) -or $value -lt 0) {Refuse "INVALID_TRACKED_PIDS"}
  if($value -gt 0){[void]$tracked.Add($value)}
 }
 $phase="PORT_SNAPSHOT"
 $before=@(Listener-Snapshot)
 $initial=Listener-Identity $before
 $phase="PROCESS_SNAPSHOT"
 $all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
 $map=@{}
 foreach($p in $all){$map[[int]$p.ProcessId]=$p}
 $relevant=New-Object 'System.Collections.Generic.HashSet[int]'
 foreach($n in $tracked){[void]$relevant.Add([int]$n)}
 foreach($port in $before){
  $n=[int]$port.OwningProcess
  [void]$relevant.Add($n)
  if($map.ContainsKey($n)){[void]$relevant.Add([int]$map[$n].ParentProcessId)}
 }
 $processBefore=Process-Snapshot @($relevant) $map
 $session=(Get-Process -Id $PID -ErrorAction Stop).SessionId
 $phase="CLASSIFY"
 $failCount=0
 foreach($p in $ports){
  $using=@($before | Where-Object { [int]$_.LocalPort -eq $p })
  $name="PORT_"+[string]$p
  if($using.Count -eq 0) {
   $details[$name]=@{Status="NOT_LISTENING";Reason="NONE"}
  } elseif($using.Count -ne 1) {
   $details[$name]=@{Status="UNVERIFIED";Reason="MULTIPLE_LISTENERS"}
   $failCount++
  } else {
   $det=Classify $using[0] $tracked $map $session
   $details[$name]=$det
   if($det.Status -eq "UNVERIFIED"){$failCount++}
  }
 }
 $phase="RECHECK"
 $after=@(Listener-Snapshot)
 $afterMap=@{}
 foreach($p in @(Get-CimInstance Win32_Process -ErrorAction Stop)){$afterMap[[int]$p.ProcessId]=$p}
 $processAfter=Process-Snapshot @($relevant) $afterMap
 $afterHash=Hash-Bytes ([IO.File]::ReadAllBytes($statePath))
 if($initial -cne (Listener-Identity $after) -or $hash -cne $afterHash -or
    $processBefore -cne $processAfter) {
  $changed=$true
  $result="INCONCLUSIVE"
  $reason="SESSION_CHANGED_DURING_AUDIT"
 } elseif($failCount -gt 0) {
  $result="ATTRIBUTION_UNVERIFIED"
  $reason="UNVERIFIED_PORT_OWNER"
 } else {
  $result="CLASSIFIED"
  $reason="NONE"
 }
} catch {
 $result="BLOCKED"
 $reason=if($phase -eq "STATE"){"STATE_UNVERIFIED"}elseif($phase -eq "ENVIRONMENT"){"ENVIRONMENT_UNVERIFIED"}else{"INSPECTION_UNAVAILABLE"}
}
Write-Output ("P0_28_RESULT="+$result)
Write-Output ("P0_28_REASON="+$reason)
if(-not $changed -and $result -ne "BLOCKED") {
 foreach($p in $ports) {
  $key="PORT_"+[string]$p
  $d=$details[$key]
  Write-Output ($key+"="+$d.Status)
  Write-Output ($key+"_REASON="+$d.Reason)
 }
}
Write-Output "STATE_MODIFIED=false"
Write-Output "PROCESSES_STOPPED=0"
Write-Output "EXCEL_ACTION=NONE"
Write-Output "STOP_ALLOWED=false"
Write-Output "CUTOVER_ELIGIBLE=false"
Write-Output "REAL_SUBMIT_ALLOWED=false"
exit $(if($result -eq "CLASSIFIED"){0}else{2})
