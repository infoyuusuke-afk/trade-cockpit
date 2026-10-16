<#
P0-24: stage an immutable isolated Git release and switch ONLY launch shortcuts.
NEVER runs V10, stops a process, touches Excel, MS2, trade, or legacy checkout.
A successful switch means "routes installed, APP NOT STARTED", not acceptance.
#>
param(
 [ValidateSet("Switch","Rollback")][string]$Mode="Switch",
 [string]$PinnedSha="",
 [string]$SwitchId="",
 [string]$StateRoot="C:\AI_Cockpit_OneClick_Starter",
 [string]$FixtureRepo="",
 [string]$FixtureDesktopRoot=""
)
$ErrorActionPreference="Stop"
$phase="INPUT"
$originalMoved=$false
$originalLink=""
$newStopLink=""
$backupDir=""
function Deny([string]$Reason){throw $Reason}
function SafeItem([string]$Path){
 $o=Get-Item -LiteralPath $Path -ErrorAction Stop
 if (($o.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){Deny "REPARSE_REFUSED"}
 return $o
}
function CheckQuiescent([string]$Root){
 if(Test-Path -LiteralPath (Join-Path $Root "V10_CONTROLLER_STATE.json")){Deny "ACTIVE_V10_STATE"}
 foreach($port in @(28580,28581,28582,28583,28584)){
  if(@(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue).Count -gt 0){
   Deny "PORT_BUSY"
  }
 }
 $procs=@(Get-CimInstance Win32_Process -ErrorAction Stop |
  Where-Object { [string]$_.Name -match '^(powershell|pwsh|cmd|python|pythonw)\.exe$' })
 foreach($proc in $procs){
  if([string]$proc.CommandLine -match '(?i)AI_COCKPIT_START_DEBUG\.cmd|START_AI_COCKPIT\.ps1|RUN_AI_COCKPIT_V10\.ps1|AI_COCKPIT_CONTROLLER_V10\.ps1|ai_brain_observer\.py'){
   Deny "OLD_COCKPIT_PROCESS_PRESENT"
  }
 }
}
function FindOldShortcut(){
 $paths=@([Environment]::GetFolderPath("Desktop"),
  (Join-Path $env:USERPROFILE "Desktop"),
  (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
  [Environment]::GetFolderPath("CommonDesktopDirectory"))
 if($FixtureDesktopRoot){
  if($env:GITHUB_ACTIONS -cne "true" -or $env:RUNNER_OS -cne "Windows"){
   Deny "FIXTURE_RESTRICTED"
  }
  $paths=@($FixtureDesktopRoot)
 }
 $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
 $results=New-Object 'System.Collections.Generic.List[string]'
 $script:UnverifiedDesktopCount=0
 foreach($v in $paths){
  if(-not $v){continue}
  $d=[IO.Path]::GetFullPath($v)
  if(-not $seen.Add($d.TrimEnd([char]92))){continue}
  if(-not (Test-Path -LiteralPath $d -PathType Container)){continue}
  try {
   [void](SafeItem $d)
   foreach($f in @(Get-ChildItem -LiteralPath $d -Filter "AI Cockpit START.lnk" -File -ErrorAction Stop)){
    [void](SafeItem $f.FullName)
    [void]$results.Add($f.FullName)
   }
  }catch{
   # Optional extra Desktop may belong to a discarded account/redirect.
   # We switch only the exact existing shortcut found in an accessible root.
   $script:UnverifiedDesktopCount++
  }
 }
 return $results.ToArray()
}
function WriteWrapper([string]$File,[string]$Target,[string]$Params){
 if($File.Contains('"') -or $Target.Contains('"')){Deny "UNSAFE_PATH"}
 $text="@echo off"+[Environment]::NewLine+"setlocal"+[Environment]::NewLine+
   'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+
   $Target+'" '+$Params+[Environment]::NewLine+"exit /b %ERRORLEVEL%"+[Environment]::NewLine
 [IO.File]::WriteAllText($File,$text,(New-Object Text.ASCIIEncoding))
}
function Quoted([string]$Value){
 if($Value.Contains('"')){Deny "UNSAFE_PATH"}
 return '"'+$Value+'"'
}
$state=[IO.Path]::GetFullPath($StateRoot)
try{
 [void](SafeItem $state)
 if($Mode -eq "Rollback"){
  $phase="ROLLBACK"
  if($SwitchId -cnotmatch '^[0-9a-f]{32}$'){Deny "BAD_SWITCH_ID"}
  $backupDir=Join-Path $state ("V10_route_cutover_"+$SwitchId)
  [void](SafeItem $backupDir)
  $enc=[IO.File]::ReadAllBytes((Join-Path $backupDir "receipt.dpapi"))
  Add-Type -AssemblyName System.Security -ErrorAction Stop
  $entropy=[Text.Encoding]::UTF8.GetBytes("100B_V10_ROUTE_V1")
  $clear=[Security.Cryptography.ProtectedData]::Unprotect($enc,$entropy,
    [Security.Cryptography.DataProtectionScope]::CurrentUser)
  $record=([Text.Encoding]::UTF8.GetString($clear) | ConvertFrom-Json -ErrorAction Stop)
  if($record.id -cne $SwitchId -or $record.real_submit_allowed -cne $false){Deny "BAD_RECEIPT"}
  CheckQuiescent $state
  $old=[string]$record.link
  $stop=[string]$record.stop
  $bak=Join-Path $backupDir "original-start.lnk"
  if((Get-FileHash $old -Algorithm SHA256).Hash -ine [string]$record.new_hash -or
     (Get-FileHash $bak -Algorithm SHA256).Hash -ine [string]$record.old_hash -or
     (Get-FileHash $stop -Algorithm SHA256).Hash -ine [string]$record.stop_hash){Deny "LINK_CHANGED"}
  Remove-Item -LiteralPath $old -Force -ErrorAction Stop
  Copy-Item -LiteralPath $bak -Destination $old -ErrorAction Stop
  Remove-Item -LiteralPath $stop -Force -ErrorAction Stop
  if((Get-FileHash $old -Algorithm SHA256).Hash -ine [string]$record.old_hash){Deny "ROLLBACK_HASH"}
  Write-Output "V10_ROUTE_ROLLBACK=PASS"
  Write-Output "REAL_SUBMIT_ALLOWED=false"
  exit 0
 }
 $phase="GUARDS"
 if($PinnedSha -cnotmatch '^[0-9a-f]{40}$'){Deny "BAD_PIN"}
 if($FixtureRepo -and ($env:GITHUB_ACTIONS -cne "true" -or $env:RUNNER_OS -cne "Windows")){Deny "FIXTURE_RESTRICTED"}
 CheckQuiescent $state
 $found=@(FindOldShortcut)
 if($found.Count -ne 1){Deny "START_SHORTCUT_NOT_UNIQUE"}
 $originalLink=[string]$found[0]
 $desktop=Split-Path -Parent $originalLink
 $newStopLink=Join-Path $desktop "AI Cockpit V10 SAFE STOP.lnk"
 if(Test-Path -LiteralPath $newStopLink){Deny "STOP_LINK_EXISTS"}
 $phase="PINNED_RELEASE"
 $clone=Join-Path $state ("V10_release_"+$PinnedSha.Substring(0,12))
 if(Test-Path -LiteralPath $clone){Deny "RELEASE_ALREADY_PRESENT"}
 $source="https://github.com/infoyuusuke-afk/trade-cockpit.git"
 if($FixtureRepo){$source=$FixtureRepo}
 $cloneArgs=@("clone","--quiet","--no-checkout","--branch",
   "fix/p0-v10-brain-safe-stop-preflight-20261017",$source,$clone)
 if(-not $FixtureRepo){$cloneArgs=@("clone","--quiet","--depth","1","--no-checkout",
  "--branch","fix/p0-v10-brain-safe-stop-preflight-20261017",$source,$clone)}
 & git @cloneArgs 2>$null
 if($LASTEXITCODE -ne 0){Deny "CLONE_FAILED"}
 & git -C $clone checkout --quiet --detach $PinnedSha
 if($LASTEXITCODE -ne 0){Deny "COMMIT_NOT_PRESENT"}
 $releaseBranch="v10-owner-"+$PinnedSha.Substring(0,12)
 & git -C $clone switch --quiet -c $releaseBranch
 if($LASTEXITCODE -ne 0){Deny "PIN_BRANCH_FAILED"}
 if((& git -C $clone rev-parse HEAD).Trim() -cne $PinnedSha -or
    (& git -C $clone branch --show-current).Trim() -cne $releaseBranch -or
    @(& git -C $clone status --porcelain --untracked-files=no).Count -ne 0){Deny "PIN_MISMATCH"}
 foreach($f in @("RUN_AI_COCKPIT_V10.ps1","STOP_AI_COCKPIT_V10.ps1","AI_COCKPIT_CONTROLLER_V10.ps1")){
  [void](SafeItem (Join-Path $clone ("downloads\"+$f)))
 }
 $stopText=[IO.File]::ReadAllText((Join-Path $clone "downloads\STOP_AI_COCKPIT_V10.ps1"))
 $ctlText=[IO.File]::ReadAllText((Join-Path $clone "downloads\AI_COCKPIT_CONTROLLER_V10.ps1"))
 if(-not $stopText.Contains("Test-ExactBrainHandle") -or
    -not $stopText.Contains("brain_observer_pid") -or
    -not $ctlText.Contains("Start-BrainObserver")){Deny "STOP_BRAIN_CONTRACT_MISSING"}
 $phase="BUILD_AND_BACKUP"
 $id=[guid]::NewGuid().ToString("N")
 $backupDir=Join-Path $state ("V10_route_cutover_"+$id)
 [void](New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop)
 $startCmd=Join-Path $backupDir "START_PINNED_V10.cmd"
 $stopCmd=Join-Path $backupDir "STOP_PINNED_V10.cmd"
 WriteWrapper $startCmd (Join-Path $clone "downloads\RUN_AI_COCKPIT_V10.ps1") (
  "-RepoRoot "+(Quoted $clone)+" -Branch "+(Quoted $releaseBranch)+
  " -ExpectedSha "+$PinnedSha+" -Root "+(Quoted $state))
 WriteWrapper $stopCmd (Join-Path $clone "downloads\STOP_AI_COCKPIT_V10.ps1") (
  "-Root "+(Quoted $state))
 $bak=Join-Path $backupDir "original-start.lnk"
 Copy-Item -LiteralPath $originalLink -Destination $bak -ErrorAction Stop
 $oldHash=(Get-FileHash $originalLink -Algorithm SHA256).Hash
 if((Get-FileHash $bak -Algorithm SHA256).Hash -ine $oldHash){Deny "BACKUP_MISMATCH"}
 $shell=New-Object -ComObject WScript.Shell
 $draftStart=Join-Path $desktop ("AI_COCKPIT_V10_"+$id+".lnk")
 $draftStop=Join-Path $desktop ("AI_COCKPIT_STOP_"+$id+".lnk")
 $l=$shell.CreateShortcut($draftStart);$l.TargetPath=$startCmd;$l.WorkingDirectory=$backupDir;$l.Save()
 $l=$shell.CreateShortcut($draftStop);$l.TargetPath=$stopCmd;$l.WorkingDirectory=$backupDir;$l.Save()
 [void](SafeItem $draftStart);[void](SafeItem $draftStop)
 CheckQuiescent $state
 $phase="SWITCH"
 Move-Item -LiteralPath $originalLink -Destination (Join-Path $backupDir "original-moved.lnk") -ErrorAction Stop
 $originalMoved=$true
 Move-Item -LiteralPath $draftStart -Destination $originalLink -ErrorAction Stop
 Move-Item -LiteralPath $draftStop -Destination $newStopLink -ErrorAction Stop
 $record=[ordered]@{
  id=$id;link=$originalLink;stop=$newStopLink
  old_hash=$oldHash
  new_hash=(Get-FileHash $originalLink -Algorithm SHA256).Hash
  stop_hash=(Get-FileHash $newStopLink -Algorithm SHA256).Hash
  real_submit_allowed=$false
 }
 Add-Type -AssemblyName System.Security -ErrorAction Stop
 $data=[Text.Encoding]::UTF8.GetBytes(($record|ConvertTo-Json -Compress))
 $salt=[Text.Encoding]::UTF8.GetBytes("100B_V10_ROUTE_V1")
 $encrypted=[Security.Cryptography.ProtectedData]::Protect($data,$salt,
   [Security.Cryptography.DataProtectionScope]::CurrentUser)
 [IO.File]::WriteAllBytes((Join-Path $backupDir "receipt.dpapi"),$encrypted)
 Write-Output "V10_ROUTE_SWITCH=PASS_NOT_STARTED"
 Write-Output ("V10_SWITCH_ID="+$id)
 Write-Output "OLD_LINK_BACKUP_VERIFIED=true"
 Write-Output "PINNED_START_AND_STOP_INSTALLED=true"
 Write-Output "NO_APP_STARTED=true"
 Write-Output ("UNVERIFIED_DESKTOP_COUNT="+[int]$script:UnverifiedDesktopCount)
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 0
}catch{
 if($originalMoved){
  try{
   if(Test-Path -LiteralPath $originalLink){Remove-Item -LiteralPath $originalLink -Force -ErrorAction Stop}
   Copy-Item -LiteralPath (Join-Path $backupDir "original-start.lnk") -Destination $originalLink -ErrorAction Stop
   if($newStopLink -and (Test-Path -LiteralPath $newStopLink)){
    Remove-Item -LiteralPath $newStopLink -Force -ErrorAction Stop
   }
  }catch{}
 }
 $reason="GENERIC_FAILURE"
 $known=@("REPARSE_REFUSED","ACTIVE_V10_STATE","PORT_BUSY","OLD_COCKPIT_PROCESS_PRESENT",
  "DESKTOP_UNVERIFIED","START_SHORTCUT_NOT_UNIQUE","STOP_LINK_EXISTS","BAD_PIN",
  "FIXTURE_RESTRICTED","RELEASE_ALREADY_PRESENT","CLONE_FAILED","COMMIT_NOT_PRESENT",
  "PIN_BRANCH_FAILED","PIN_MISMATCH","STOP_BRAIN_CONTRACT_MISSING",
  "BACKUP_MISMATCH","BAD_SWITCH_ID","BAD_RECEIPT","LINK_CHANGED","ROLLBACK_HASH")
 if($known -ccontains [string]$_.Exception.Message){$reason=[string]$_.Exception.Message}
 Write-Output ("V10_ROUTE_BLOCK_STAGE="+$phase)
 Write-Output ("V10_ROUTE_BLOCK_REASON="+$reason)
 Write-Output "V10_ROUTE_SWITCH=BLOCKED"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 2
}
