<#
P0-27: one non-stopping OWNER entry for the legacy V10 session.

It never stops, starts, switches or kills anything. It runs the reviewed
P0-26C components only after fetching them for one full 40-hex commit and
matching their exact Git blob hashes; local copies are never trusted.

Checks, all read-only on the session:
  - legacy admission (PREFLIGHT -AdmissionOut): PowerShell -File operands for
    Controller/RUN, Start-Job bridges, venv children, BRAIN absence or
    ownership, managed Excel PID, owners of LISTEN 28580-28584;
  - STOP -RecoveryCheck (writes nothing);
  - with -IncludeStopDryRun, STOP without -Execute (handle pinning only).
State file, root result/evidence, Excel process set, V10 listeners, admitted
processes and launch files (root CMD/BAT/LNK/PS1/VBS, Desktop and Startup
LNK/CMD/BAT) are fingerprinted before and after and must be identical. Only
those listed folders are compared (LAUNCH_SCOPE=LISTED_FOLDERS_ONLY); other
desktops, profiles or shortcuts elsewhere are not inspected.

The entry itself is not self-verifying: it must be fetched by full commit
SHA and matched to its published Git blob and SHA256 before it runs
(docs/V10_P0_27_OWNER_READONLY_DELIVERY.md).

Temporary files, the only writes:
  - one folder %TEMP%\v10-owner-readonly-<guid> holding the two fetched
    scripts and the admission record; removed before the result is printed;
  - with -IncludeStopDryRun, STOP's own %TEMP%\v10-legacy-stop-dryrun-<UTC>
    folder (state copy and admission record), which STOP removes; the set of
    such folders must be unchanged afterwards.
Strict READONLY_VERIFIED is the default mode (only the first folder);
DRY_RUN_READY additionally ran the STOP dry run.

Output is codes and counts only: no paths, PIDs, command lines, workbook
names, state JSON or account data. A pass never means STOP, cutover or that
a new V10 can start while business Excel is open.
#>
param(
 [Parameter(Mandatory=$true)][string]$PinnedCommit,
 [string]$Root="C:\AI_Cockpit_OneClick_Starter",
 [switch]$IncludeStopDryRun,
 # GitHub Actions Windows only: take the two scripts from a local folder
 # instead of raw.githubusercontent.com (blob hashes are still enforced).
 [string]$FixtureRoot=""
)
$ErrorActionPreference="Stop"
$ReviewedCommit="4e4b59e4f054cd91d0122f717f0f6d60c28d70d5"
$Spec=@(
 @{Name="PREFLIGHT_V10_LEGACY_SHUTDOWN_V1.ps1";Blob="94cbce7f4352bac9b1fdb0749a15f8a15400ba7b"},
 @{Name="STOP_V10_LEGACY_SESSION_V1.ps1";Blob="bc883ea583c065b335361fc33498d5a8c4fc77ab"}
)
$V10Ports=@(28580,28581,28582,28583,28584)
$stage="INPUT"
$tempRoot=$null
$counts=[ordered]@{}
function Block([string]$Reason){ throw $Reason }
function BHash([byte[]]$Bytes){
 $prefix=[Text.Encoding]::ASCII.GetBytes("blob "+$Bytes.Length+[char]0)
 $all=New-Object byte[] ($prefix.Length+$Bytes.Length)
 [Array]::Copy($prefix,0,$all,0,$prefix.Length)
 [Array]::Copy($Bytes,0,$all,$prefix.Length,$Bytes.Length)
 $sha=[Security.Cryptography.SHA1]::Create()
 try{return ([BitConverter]::ToString($sha.ComputeHash($all))).Replace("-","").ToLowerInvariant()}
 finally{$sha.Dispose()}
}
function Sha256Bytes([byte[]]$Bytes){
 $sha=[Security.Cryptography.SHA256]::Create()
 try{return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace("-","")}
 finally{$sha.Dispose()}
}
function Sha256Text([string]$Text){ return Sha256Bytes ([Text.Encoding]::UTF8.GetBytes($Text)) }
function Read-Bytes([string]$Path,[string]$Reason){
 try{return [IO.File]::ReadAllBytes($Path)}catch{Block $Reason}
}
function Run-Component([string]$Script,[string[]]$Arguments){
 $ps=Join-Path $PSHOME "powershell.exe"
 $ErrorActionPreference="Continue"
 $lines=@(& $ps -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>$null)
 $code=$LASTEXITCODE
 $ErrorActionPreference="Stop"
 return [pscustomobject]@{Code=[int]$code;Lines=@($lines | ForEach-Object { [string]$_ })}
}
function Get-Value($Lines,[string]$Key){
 foreach($l in $Lines){ if($l.StartsWith($Key+"=")){ return $l.Substring($Key.Length+1) } }
 return ""
}
function Is-Code([string]$v){ return $v -cmatch '^[A-Z0-9_]{1,64}$' }
if(-not ("V10OwnerArgv" -as [type])){
 Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class V10OwnerArgv {
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
function Get-LaunchFiles([string]$RootFull){
 $dirs=@($RootFull,[Environment]::GetFolderPath("Desktop"),(Join-Path $env:USERPROFILE "Desktop"),
  (Join-Path $env:USERPROFILE "OneDrive\Desktop"),[Environment]::GetFolderPath("CommonDesktopDirectory"),
  [Environment]::GetFolderPath("Startup"),[Environment]::GetFolderPath("CommonStartup"))
 $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
 $rows=New-Object System.Collections.ArrayList
 $script:LaunchDirsChecked=0
 $script:LaunchDirsAbsent=0
 foreach($d in $dirs){
  if(-not $d){$script:LaunchDirsAbsent++;continue}
  $full=[IO.Path]::GetFullPath($d).TrimEnd([char]92)
  if(-not $seen.Add($full)){continue}
  if(-not (Test-Path -LiteralPath $full -PathType Container)){$script:LaunchDirsAbsent++;continue}
  $script:LaunchDirsChecked++
  $ext=if($full -ieq $RootFull.TrimEnd([char]92)){'^\.(cmd|bat|lnk|ps1|vbs)$'}else{'^\.(lnk|cmd|bat)$'}
  foreach($f in @(Get-ChildItem -LiteralPath $full -File -Force -ErrorAction Stop | Where-Object { $_.Extension -match $ext })){
   [void]$rows.Add($f.FullName.ToLowerInvariant()+"|"+$f.Length+"|"+$f.LastWriteTimeUtc.Ticks+"|"+(Sha256Bytes (Read-Bytes $f.FullName "LAUNCH_FILE_UNREADABLE")))
  }
 }
 return ,@($rows | Sort-Object)
}
function Get-Fingerprint([string]$RootFull){
 $fp=@{}
 $state=Join-Path $RootFull "V10_CONTROLLER_STATE.json"
 # Keep the exact legacy composite fingerprint for fail-closed admission.
 # Separate the internal factors only to classify a rejected read-only check.
 $fp.StateHash="ABSENT"
 $fp.StateTimestamp="ABSENT"
 if(Test-Path -LiteralPath $state -PathType Leaf){
  $b=Read-Bytes $state "STATE_UNREADABLE"
  $fp.StateHash=Sha256Bytes $b
  $fp.StateTimestamp=[string](Get-Item -LiteralPath $state).LastWriteTimeUtc.Ticks
 }
 $fp.State=$fp.StateHash+"|"+$fp.StateTimestamp
 $result=Join-Path $RootFull "V10_LEGACY_STOP_RESULT.json"
 $fp.Result=if(Test-Path -LiteralPath $result -PathType Leaf){Sha256Bytes (Read-Bytes $result "RESULT_UNREADABLE")}else{"ABSENT"}
 $ev=Join-Path $RootFull "V10_LEGACY_STOP_EVIDENCE"
 $fp.Evidence=if(Test-Path -LiteralPath $ev){
  Sha256Text ((@(Get-ChildItem -LiteralPath $ev -Recurse -Force -ErrorAction Stop | ForEach-Object { $_.FullName+"|"+$_.LastWriteTimeUtc.Ticks }) | Sort-Object) -join "`n")
 }else{"ABSENT"}
 $excel=@(Get-CimInstance Win32_Process -Filter "Name = 'EXCEL.EXE'" -ErrorAction Stop |
  ForEach-Object { ([string]$_.ProcessId)+":"+([datetime]$_.CreationDate).ToUniversalTime().Ticks } | Sort-Object)
 $fp.Excel=$excel -join ","
 $fp.ExcelCount=$excel.Count
 $listen=@(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $V10Ports -contains [int]$_.LocalPort })
 $fp.Listen=(@($listen | ForEach-Object { ([string]$_.LocalAddress)+":"+$_.LocalPort+":"+$_.OwningProcess } | Sort-Object)) -join ","
 $fp.ListenOwners=@($listen | ForEach-Object { [int]$_.OwningProcess })
 $fp.ListenCount=$listen.Count
 $launch=Get-LaunchFiles $RootFull
 $fp.Launch=$launch -join "`n"
 $fp.LaunchCount=$launch.Count
 $fp.DryRunDirs=(@(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Directory -Filter "v10-legacy-stop-dryrun-*" -Force -ErrorAction SilentlyContinue |
  ForEach-Object { $_.Name }) | Sort-Object) -join ","
 return $fp
}
function Test-EntryAlive($Entry){
 $p=Get-Process -Id ([int]$Entry.pid) -ErrorAction SilentlyContinue
 if($null -eq $p){return $false}
 try{
  if($p.HasExited){return $false}
  return ([Math]::Abs($p.StartTime.ToUniversalTime().Ticks-[long]$Entry.created_utc_ticks) -le [TimeSpan]::TicksPerSecond*2)
 }catch{return $true}
}
function Get-ControllerHost($Entry){
 if($null -eq $Entry){return "NOT_RUNNING"}
 $info=Get-CimInstance Win32_Process -Filter ("ProcessId = "+[int]$Entry.pid) -ErrorAction Stop
 if($null -eq $info){return "UNVERIFIED"}
 $argv=@([V10OwnerArgv]::Split([string]$info.CommandLine))
 for($i=1;$i -lt $argv.Count-1;$i++){
  if($argv[$i] -ieq "-File"){
   $leaf=[IO.Path]::GetFileName($argv[$i+1])
   if($leaf -ieq "AI_COCKPIT_CONTROLLER_V10.ps1"){return "CONTROLLER_SCRIPT"}
   if($leaf -ieq "RUN_AI_COCKPIT_V10.ps1"){return "RUN_HOST"}
   return "UNVERIFIED"
  }
 }
 return "UNVERIFIED"
}

$result="BLOCKED"
$reason=""
try{
 $stage="ENVIRONMENT"
 if($PSVersionTable.PSVersion.Major -ne 5 -or [string]$PSVersionTable.PSEdition -cne "Desktop" -or
    [Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT){
  Block "ENVIRONMENT_UNSUPPORTED"
 }
 $stage="PINNED_COMMIT"
 if($PinnedCommit -cnotmatch '^[0-9a-f]{40}$'){Block "PINNED_COMMIT_FORMAT"}
 if($PinnedCommit -cne $ReviewedCommit){Block "PINNED_COMMIT_MISMATCH"}
 $stage="TARGET_PATH"
 if(-not [IO.Path]::IsPathRooted($Root) -or $Root.StartsWith("\\")){Block "TARGET_PATH_INVALID"}
 $rootFull=[IO.Path]::GetFullPath($Root)
 if(-not (Test-Path -LiteralPath $rootFull -PathType Container)){Block "ROOT_NOT_FOUND"}
 if(((Get-Item -LiteralPath $rootFull -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){Block "TARGET_PATH_INVALID"}
 if(-not (Test-Path -LiteralPath (Join-Path $rootFull "V10_CONTROLLER_STATE.json") -PathType Leaf)){Block "STATE_MISSING"}

 $stage="FINGERPRINT_BEFORE"
 $before=Get-Fingerprint $rootFull

 $stage="PACKAGE_VERIFY"
 if($FixtureRoot -and ($env:GITHUB_ACTIONS -cne "true" -or $env:RUNNER_OS -cne "Windows")){Block "FIXTURE_RESTRICTED"}
 $tempRoot=Join-Path ([IO.Path]::GetTempPath()) ("v10-owner-readonly-"+[guid]::NewGuid().ToString("N"))
 [void](New-Item -ItemType Directory -Path $tempRoot -ErrorAction Stop)
 foreach($entry in $Spec){
  $dest=Join-Path $tempRoot $entry.Name
  if($FixtureRoot){
   $src=Join-Path $FixtureRoot $entry.Name
   if(-not (Test-Path -LiteralPath $src -PathType Leaf)){Block "SCRIPT_MISSING"}
   Copy-Item -LiteralPath $src -Destination $dest -ErrorAction Stop
  }else{
   [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
   $uri="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/"+$PinnedCommit+"/downloads/"+$entry.Name
   try{Invoke-WebRequest -Uri $uri -OutFile $dest -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop}catch{Block "SCRIPT_DOWNLOAD_FAILED"}
  }
  $bytes=[IO.File]::ReadAllBytes($dest)
  if($bytes.Length -lt 500 -or $bytes.Length -gt 200000 -or (BHash $bytes) -cne $entry.Blob){Block "SCRIPT_BLOB_MISMATCH"}
 }
 $counts.PINNED_COMMIT_VERIFIED="true"
 $counts.SCRIPT_BLOBS_VERIFIED=$Spec.Count
 $preflight=Join-Path $tempRoot $Spec[0].Name
 $stop=Join-Path $tempRoot $Spec[1].Name

 $stage="ADMISSION"
 $admission=Join-Path $tempRoot "admission.json"
 $a=Run-Component $preflight @("-Root",$rootFull,"-AdmissionOut",$admission)
 if($a.Code -ne 0 -or $a.Lines -cnotcontains "PREFLIGHT_RESULT=EVIDENCE_ONLY_PASS" -or
    -not (Test-Path -LiteralPath $admission -PathType Leaf)){
  $why=Get-Value $a.Lines "PREFLIGHT_BLOCK_REASON"
  if(-not (Is-Code $why)){$why="UNVERIFIED"}
  if($why -ceq "PORT_CHILD_IDENTITY_NOT_PROVEN"){
   $d=Get-Value $a.Lines "PREFLIGHT_PORT_DIAGNOSTIC"
   $allowed=@("COLLECTOR_SOURCE_UNREADABLE","COLLECTOR_SOURCE_UNTRUSTED",
     "COLLECTOR_ARGV_LAYOUT_MISMATCH","COLLECTOR_ENCODED_PAYLOAD_INVALID",
     "COLLECTOR_SOURCE_PARSE_ERROR","COLLECTOR_SOURCE_FUNCTION_MISMATCH",
     "COLLECTOR_INIT_TEXT_MISMATCH","COLLECTOR_INIT_INSPECTION_UNAVAILABLE",
     "HOST_EXE_PATH_MISMATCH","LIFETIME_OR_SESSION_UNVERIFIED",
     "PORT_CHILD_UNVERIFIED","COLLECTOR_INIT_UNVERIFIED")
   $counts.P0_27_BLOCK_DETAIL=if($allowed -ccontains $d){$d}else{"UNVERIFIED"}
   $port=Get-Value $a.Lines "PREFLIGHT_PORT_NUM"
   $counts.P0_27_BLOCK_PORT=if(@("28580","28581","28582","28583","28584") -ccontains $port){$port}else{"UNKNOWN"}
  }
  Block ("PREFLIGHT_"+$why)
 }
 $rec=[IO.File]::ReadAllText($admission,[Text.Encoding]::UTF8) | ConvertFrom-Json
 if([string]$rec.schema -cne "V10_LEGACY_STOP_ADMISSION_V1"){Block "ADMISSION_SCHEMA"}
 $members=@($rec.members | Where-Object { $null -ne $_ })
 $bridges=@($rec.bridges | Where-Object { $null -ne $_ })
 $entries=@($members+$bridges)
 if($null -ne $rec.brain){$entries+=$rec.brain}
 $admittedPids=New-Object 'System.Collections.Generic.HashSet[int]'
 foreach($e in $entries){[void]$admittedPids.Add([int]$e.pid)}
 $counts.ADMITTED_PROCESSES=$entries.Count
 $counts.CONTROLLER_HOST=Get-ControllerHost (@($members | Where-Object { [string]$_.role -ceq "controller_pid" }) | Select-Object -First 1)
 $counts.WORKERS_LIVE=@($members | Where-Object { [string]$_.role -like "*_pid" -and [string]$_.role -cne "controller_pid" }).Count
 $counts.VENV_CHILDREN=@($members | Where-Object { [string]$_.role -like "*venv_child" }).Count
 $counts.BRIDGE_CHILDREN=$bridges.Count
 $counts.BRAIN_STATUS=[string]$rec.brain_status
 $counts.MANAGED_EXCEL_LIVE=([string][bool]$rec.excel_live).ToLowerInvariant()
 $counts.EXCEL_PROCESSES=$before.ExcelCount
 $counts.V10_LISTEN_PORTS=$before.ListenCount
 $counts.LISTEN_ATTRIBUTED=@($before.ListenOwners | Where-Object { $admittedPids.Contains([int]$_) }).Count
 if($counts.LISTEN_ATTRIBUTED -ne $counts.V10_LISTEN_PORTS){Block "LISTENER_NOT_ATTRIBUTED"}

 $stage="RECOVERY_CHECK"
 $r=Run-Component $stop @("-Root",$rootFull,"-RecoveryCheck")
 $action=Get-Value $r.Lines "RECOVERY_ACTION"
 if($r.Lines -cnotcontains "RECOVERY_CHECK=COMPLETE" -or $r.Lines -cnotcontains "PROCESSES_STOPPED=0" -or -not (Is-Code $action)){
  Block "RECOVERY_CHECK_UNVERIFIED"
 }
 $counts.LEGACY_RECOVERY_ACTION=$action

 if($IncludeStopDryRun){
  $stage="STOP_DRY_RUN"
  $d=Run-Component $stop @("-Root",$rootFull)
  if($d.Code -ne 0 -or $d.Lines -cnotcontains "LEGACY_STOP_RESULT=DRY_RUN_READY"){
   $why=Get-Value $d.Lines "LEGACY_STOP_REASON"
   if(-not (Is-Code $why)){$why="UNVERIFIED"}
   Block ("STOP_DRY_RUN_"+$why)
  }
  $n=Get-Value $d.Lines "ADMITTED_PROCESSES"
  if($n -cne [string]$entries.Count){Block "STOP_DRY_RUN_ADMISSION_DIFFERS"}
 }

 $stage="FINGERPRINT_AFTER"
 $after=Get-Fingerprint $rootFull
 # Diagnostic details, not an exception: ANY change still BLOCKS this check.
 $counts.STATE_CONTENT_UNCHANGED=([string]($after.StateHash -ceq $before.StateHash)).ToLowerInvariant()
 $counts.STATE_TIMESTAMP_UNCHANGED=([string]($after.StateTimestamp -ceq $before.StateTimestamp)).ToLowerInvariant()
 $counts.STATE_CHANGE_CLASS=if($counts.STATE_CONTENT_UNCHANGED -cne "true"){"CONTENT_CHANGED"}elseif($counts.STATE_TIMESTAMP_UNCHANGED -cne "true"){"METADATA_ONLY"}else{"NO_CHANGE"}
 $counts.STATE_UNCHANGED=([string]($after.State -ceq $before.State)).ToLowerInvariant()
 $counts.ROOT_RESULT_AND_EVIDENCE_UNCHANGED=([string]($after.Result -ceq $before.Result -and $after.Evidence -ceq $before.Evidence)).ToLowerInvariant()
 $counts.EXCEL_SET_UNCHANGED=([string]($after.Excel -ceq $before.Excel)).ToLowerInvariant()
 $counts.LISTENERS_UNCHANGED=([string]($after.Listen -ceq $before.Listen)).ToLowerInvariant()
 $counts.MANAGED_PROCESSES_UNCHANGED=([string](@($entries | Where-Object { -not (Test-EntryAlive $_) }).Count -eq 0)).ToLowerInvariant()
 $counts.LAUNCH_FILES_CHECKED=$after.LaunchCount
 # Only the listed folders are compared; other desktops or profiles are not inspected.
 $counts.LAUNCH_SCOPE="LISTED_FOLDERS_ONLY"
 $counts.LAUNCH_DIRS_CHECKED=$script:LaunchDirsChecked
 $counts.LAUNCH_DIRS_ABSENT=$script:LaunchDirsAbsent
 $counts.LAUNCH_FILES_UNCHANGED=([string]($after.Launch -ceq $before.Launch)).ToLowerInvariant()
 $counts.STOP_DRY_RUN_TEMP_LEFT=([string]($after.DryRunDirs -cne $before.DryRunDirs)).ToLowerInvariant()
 foreach($k in @("STATE_UNCHANGED","ROOT_RESULT_AND_EVIDENCE_UNCHANGED","EXCEL_SET_UNCHANGED","LISTENERS_UNCHANGED",
   "MANAGED_PROCESSES_UNCHANGED","LAUNCH_FILES_UNCHANGED")){
  if($counts[$k] -cne "true"){Block ("CHANGED_DURING_CHECK_"+$k)}
 }
 if($counts.STOP_DRY_RUN_TEMP_LEFT -cne "false"){Block "STOP_DRY_RUN_TEMP_LEFT"}
 $result=if($IncludeStopDryRun){"DRY_RUN_READY"}else{"READONLY_VERIFIED"}
}catch{
 $msg=[string]$_.Exception.Message
 $reason=if((Is-Code $msg) -and $msg -cmatch '^(ENVIRONMENT_|PINNED_|TARGET_|ROOT_|STATE_|RESULT_|LAUNCH_|FIXTURE_|SCRIPT_|PREFLIGHT_|ADMISSION_|LISTENER_|RECOVERY_|STOP_DRY_RUN_|CHANGED_DURING_CHECK_)'){$msg}
  elseif($_.Exception -is [UnauthorizedAccessException] -or $msg -match 'denied'){"ACCESS_DENIED"}
  else{"UNVERIFIED"}
 $result="BLOCKED"
}
# Remove the own temporary folder before reporting; nothing else is removed.
$tempRemoved="true"
if($tempRoot -and (Test-Path -LiteralPath $tempRoot)){
 try{Remove-Item -LiteralPath $tempRoot -Recurse -Force}catch{}
 if(Test-Path -LiteralPath $tempRoot){$tempRemoved="false"}
}
if($result -cne "BLOCKED" -and $tempRemoved -cne "true"){$result="BLOCKED";$reason="TEMP_NOT_REMOVED"}
Write-Output ("P0_27_RESULT="+$result)
if($result -ceq "BLOCKED"){
 Write-Output ("P0_27_BLOCK_STAGE="+$stage)
 Write-Output ("P0_27_BLOCK_REASON="+$reason)
}
foreach($k in $counts.Keys){Write-Output ($k+"="+$counts[$k])}
Write-Output ("READ_SCOPE="+$(if($IncludeStopDryRun){"STOP_DRY_RUN_TEMP_ALLOWED"}else{"STRICT_OWN_TEMP_ONLY"}))
Write-Output ("TEMP_REMOVED="+$tempRemoved)
Write-Output "PROCESSES_STOPPED=0"
Write-Output "EXCEL_ACTION=NONE"
Write-Output "EXCEL_WORKBOOK_COEXISTENCE=NOT_EVALUATED"
Write-Output "STOP_ALLOWED=false"
Write-Output "CUTOVER_ELIGIBLE=false"
Write-Output "REAL_SUBMIT_ALLOWED=false"
exit $(if($result -ceq "BLOCKED"){2}else{0})
