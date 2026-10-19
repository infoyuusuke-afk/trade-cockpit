#requires -Version 5.1
<#
OWNER opt-in read-only Windows acceptance snapshot. Never creates approval
pins, starts/stops V10, changes Git/Excel/MS2, or accesses broker/orders.
Only sanitized verdicts are printed; never PIDs, paths or market rows.
#>
[CmdletBinding()]
param(
 [string]$RepoRoot = "",
 [string]$StateRoot = "C:\AI_Cockpit_OneClick_Starter",
 [switch]$SelfTest
)
$ErrorActionPreference = "Stop"
$sourceProof = @(
 "V10_READONLY_SOURCE=PASS",
 "GIT_BRANCH_AND_FULL_SHA_MATCH=1",
 "GIT_WORKTREE_CLEAN=1",
 "RUNTIME_FILES_TOUCHED=0",
 "CONTROLLER_STARTED=0",
 "MS2_TOUCHED=0",
 "EXCEL_TOUCHED=0",
 "REAL_SUBMIT_ALLOWED=0",
 "OWNER_AUTHENTICATED=0"
)
function Test-ExactProof([int]$ExitCode,[object[]]$Lines,[string[]]$Expected) {
 if ($ExitCode -ne 0 -or $null -eq $Lines -or $Lines.Count -ne $Expected.Count) { return $false }
 foreach ($line in $Lines) {
  if ($line -isnot [string] -or $line.Length -gt 200 -or $Expected -cnotcontains $line) {
   return $false
  }
 }
 # Membership alone is insufficient: duplicate safe lines could replace
 # one required proof line. Require one occurrence of EACH exact marker.
 foreach ($required in $Expected) {
  if (@($Lines | Where-Object { $_ -ceq $required }).Count -ne 1) { return $false }
 }
 return $true
}
function Finish-Blocked([string]$Reason) {
 Write-Output "V10_WINDOWS_READONLY_ACCEPTANCE=BLOCKED"
 Write-Output ("BLOCKER="+$Reason)
 Write-Output "CONTROLLER_STARTED_BY_THIS_CHECK=0"
 Write-Output "REAL_SUBMIT_ALLOWED=0"
 exit 2
}
$brainProof = @(
 "V10_BRAIN_PREFLIGHT=OBSERVATION_ONLY",
 "VERIFIED_SHA=" + ("a" * 40),
 "EXCHANGE_TICK_DATE_VERIFIED=0",
 "EXPECTED_RETURN_VALIDATED=0",
 "SOURCE_AUTHENTICATED=0",
 "REAL_SUBMIT_ALLOWED=0"
)
if ($SelfTest) {
 if (-not (Test-ExactProof 0 $sourceProof $sourceProof)) { Write-Output "SELFTEST_FAILURE_CASE=1"; exit 3 }
 if (Test-ExactProof 1 $sourceProof $sourceProof) { Write-Output "SELFTEST_FAILURE_CASE=2"; exit 3 }
 if (Test-ExactProof 0 @($sourceProof + @("UNREVIEWED=1")) $sourceProof) { Write-Output "SELFTEST_FAILURE_CASE=3"; exit 3 }
 if (Test-ExactProof 0 @($sourceProof[0..7] + @("REAL_SUBMIT_ALLOWED=1")) $sourceProof) { Write-Output "SELFTEST_FAILURE_CASE=4"; exit 3 }
 if (Test-ExactProof 0 @($sourceProof[0..7] + @($sourceProof[0])) $sourceProof) { Write-Output "SELFTEST_FAILURE_CASE=5"; exit 3 }
 if (-not (Test-ExactProof 0 $brainProof $brainProof)) { Write-Output "SELFTEST_FAILURE_CASE=6"; exit 3 }
 if (Test-ExactProof 2 $brainProof $brainProof) { Write-Output "SELFTEST_FAILURE_CASE=7"; exit 3 }
 if (Test-ExactProof 0 @($brainProof[0..4] + @("REAL_SUBMIT_ALLOWED=1")) $brainProof) { Write-Output "SELFTEST_FAILURE_CASE=8"; exit 3 }
 if (Test-ExactProof 0 @($brainProof + @("TICKER=PRIVATE")) $brainProof) { Write-Output "SELFTEST_FAILURE_CASE=9"; exit 3 }
 Write-Output "V10_WINDOWS_READONLY_SELFTEST=PASS"
 Write-Output "CONTROLLER_STARTED_BY_THIS_CHECK=0"
 Write-Output "REAL_SUBMIT_ALLOWED=0"
 exit 0
}
if ($env:OS -cne "Windows_NT") { Finish-Blocked "WINDOWS_REQUIRED" }
$stage = "LOCAL_SOURCE_UNVERIFIED"
try {
 if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
  $RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
 }
 if (-not [IO.Path]::IsPathRooted($RepoRoot) -or
     -not [IO.Path]::IsPathRooted($StateRoot) -or
     $RepoRoot.StartsWith("\\") -or $StateRoot.StartsWith("\\")) {
  Finish-Blocked "LOCAL_PATH_REQUIRED"
 }
 $repo = [IO.Path]::GetFullPath($RepoRoot)
 $state = [IO.Path]::GetFullPath($StateRoot)
 foreach ($dir in @($repo,$state)) {
  if (-not (Test-Path -LiteralPath $dir -PathType Container)) { Finish-Blocked "LOCAL_PATH_MISSING" }
  $item=Get-Item -LiteralPath $dir -ErrorAction Stop
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
   Finish-Blocked "LOCAL_PATH_UNTRUSTED"
  }
 }
 $approval=Join-Path $repo "downloads\V10_APPROVED_SOURCE.json"
 $verify=Join-Path $repo "downloads\VERIFY_V10_SOURCE_PIN_READONLY.ps1"
 $preflight=Join-Path $repo "downloads\AI_COCKPIT_V10_BRAIN_PREFLIGHT.ps1"
 foreach ($file in @($approval,$verify,$preflight)) {
  if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
   Finish-Blocked "SOURCE_APPROVAL_OR_PREFLIGHT_MISSING"
  }
  $item=Get-Item -LiteralPath $file -ErrorAction Stop
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
      $item.Length -le 2 -or $item.Length -gt 65536) {
   Finish-Blocked "LOCAL_SOURCE_UNTRUSTED"
  }
 }
 $cfg=[IO.File]::ReadAllText($approval,[Text.Encoding]::UTF8) | ConvertFrom-Json -ErrorAction Stop
 if ($null -eq $cfg -or $cfg -isnot [pscustomobject] -or
     $cfg.PSObject.Properties.Name.Count -ne 4 -or
     $cfg.PSObject.Properties.Name -notcontains "schema" -or
     $cfg.PSObject.Properties.Name -notcontains "branch" -or
     $cfg.PSObject.Properties.Name -notcontains "commit_sha" -or
     $cfg.PSObject.Properties.Name -notcontains "real_submit_allowed" -or
     [string]$cfg.schema -cne "v10_approved_source_v1" -or
     [string]$cfg.branch -cne "main" -or
     $cfg.commit_sha -isnot [string] -or
     $cfg.commit_sha -cnotmatch '^[0-9a-fA-F]{40}$' -or
     $cfg.real_submit_allowed -isnot [bool] -or $cfg.real_submit_allowed) {
  Finish-Blocked "OWNER_SOURCE_PIN_INVALID"
 }
 # Independent reviewed source admission; no self-approval from git HEAD.
 $stage="SOURCE_PIN_BLOCKED"
 $sourceLines=@(& powershell.exe -NoLogo -NoProfile -NonInteractive -File $verify -RepoRoot $repo -ApprovalFile $approval 2>&1)
 $sourceExit=$LASTEXITCODE
 if (-not (Test-ExactProof $sourceExit $sourceLines $sourceProof)) {
  Finish-Blocked "SOURCE_PIN_BLOCKED"
 }
 # Independent Controller/Brain process, quote-freshness and safety preflight.
 $stage="V10_BRAIN_HEALTH_BLOCKED"
 $brainLines=@(& powershell.exe -NoLogo -NoProfile -NonInteractive -File $preflight -RepoRoot $repo -StateRoot $state -ExpectedSha ([string]$cfg.commit_sha) -ExpectedBranch "main" 2>&1)
 $brainExit=$LASTEXITCODE
 $expectedBrain=@(
  "V10_BRAIN_PREFLIGHT=OBSERVATION_ONLY",
  "VERIFIED_SHA=" + [string]$cfg.commit_sha,
  "EXCHANGE_TICK_DATE_VERIFIED=0",
  "EXPECTED_RETURN_VALIDATED=0",
  "SOURCE_AUTHENTICATED=0",
  "REAL_SUBMIT_ALLOWED=0"
 )
 if (-not (Test-ExactProof $brainExit $brainLines $expectedBrain)) {
  Finish-Blocked "V10_BRAIN_HEALTH_BLOCKED"
 }
 Write-Output "V10_WINDOWS_READONLY_ACCEPTANCE=OBSERVATION_ONLY"
 Write-Output "V10_LOCAL_SOURCE_PIN=PASS"
 Write-Output "V10_BRAIN_LOCAL_HEALTH=PASS"
 Write-Output "V10_REAL_MARKET_AUTHENTICITY=NOT_VERIFIED"
 Write-Output "V10_REAL_TRADING_ACCEPTANCE=NOT_APPROVED"
 Write-Output "CONTROLLER_STARTED_BY_THIS_CHECK=0"
 Write-Output "REAL_SUBMIT_ALLOWED=0"
 exit 0
} catch {
 # The error may include paths, command lines or private data. Sanitize it.
 Finish-Blocked $stage
}
