<#
P0-23: one-entry, locally bounded delivery for P0-20/21/22.
Inspect: verified DOWNLOAD TO TEMP, local immutable snapshot check, read-only mapping.
SaveAndVerify: additionally writes DPAPI CurrentUser evidence under StateRoot,
then independently verifies that evidence. It NEVER starts/stops/cuts over,
modifies Git/repo/legacy CMD/LNK/Excel/MS2, makes broker calls, or uploads data.
Strict blob pinning applies to every downloaded executable script.
#>
param(
 [ValidateSet("Inspect","SaveAndVerify")][string]$Mode="Inspect",
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{40}$')]
 [string]$PinnedCommit,
 [Parameter(Mandatory=$true)][ValidatePattern('^\d{8}_\d{6}_[0-9a-f]{12}$')]
 [string]$SnapshotId,
 [string]$RepoRoot="C:\AI_Cockpit_Current\trade-cockpit",
 [string]$StateRoot="C:\AI_Cockpit_OneClick_Starter",
 [string]$FixtureRoot=""
)
$ErrorActionPreference="Stop"
$stage="INPUT"
function Block([string]$Reason) { throw $Reason }
function BHash([byte[]]$Bytes) {
 $prefix=[Text.Encoding]::ASCII.GetBytes("blob "+$Bytes.Length+[char]0)
 $all=New-Object byte[] ($prefix.Length+$Bytes.Length)
 [Array]::Copy($prefix,0,$all,0,$prefix.Length)
 [Array]::Copy($Bytes,0,$all,$prefix.Length,$Bytes.Length)
 $sha=[Security.Cryptography.SHA1]::Create()
 try { return ([BitConverter]::ToString($sha.ComputeHash($all))).Replace("-","").ToLowerInvariant() }
 finally { $sha.Dispose() }
}
function Quote([string]$s) { return "'"+$s.Replace("'","''")+"'" }
function RunPS([string]$Snippet) {
 $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Snippet))
 $output=@(& powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand $encoded 2>$null)
 $rc=$LASTEXITCODE
 return [pscustomobject]@{ Code=[int]$rc; Lines=@($output) }
}
function EmitPublic([string[]]$Lines) {
 $allowed=@("SNAPSHOT_ENTRY_COUNT","TARGET_MATCHED","TARGET_MISSING_OR_CHANGED",
   "TARGET_AMBIGUOUS","DESKTOP_TARGETS_MATCHED","DESKTOP_TARGETS_EXPECTED",
   "UNVERIFIED_DESKTOP_ROOTS","UNVERIFIED_DESKTOP_ROOT_INDEX",
   "SNAPSHOT_INVENTORY_PARTIAL","TARGET_MAP_STATUS","CUTOVER_ELIGIBLE",
   "REAL_SUBMIT_ALLOWED","ORIGINAL_ABSOLUTE_PATHS_EXPORTED",
   "ENCRYPTED_MAP_RESULT","ENCRYPTED_MAP_CUTOVER_READY",
   "MAP_RECHECK_MATCHED","MAP_RECHECK_STALE","MAP_TOTAL_ARCHIVED",
   "MAP_INVENTORY_PARTIAL","ABSOLUTE_PATHS_EXPORTED","ENCRYPTED_MAP_RECEIPT",
   "BLOCK_STAGE","BLOCK_REASON")
 foreach ($ln in $Lines) {
  if ([string]$ln -match '^([A-Z_]+)=(?:[A-Za-z_0-9-]+)$' -and
      $allowed -ccontains $Matches[1]) { Write-Output $ln }
 }
}
$tempRoot=$null
try {
 $repo=[IO.Path]::GetFullPath($RepoRoot)
 $state=[IO.Path]::GetFullPath($StateRoot)
 $snapshot=Join-Path (Join-Path $state "V10_cutover_snapshots") $SnapshotId
 $stage="SNAPSHOT_PRECHECK"
 if (-not (Test-Path -LiteralPath $snapshot -PathType Container) -or
     -not (Test-Path -LiteralPath (Join-Path $snapshot "manifest.json") -PathType Leaf)) {
  Block "SNAPSHOT_NOT_FOUND"
 }
 if (-not (Test-Path -LiteralPath $repo -PathType Container)) { Block "REPO_NOT_FOUND" }
 $spec=@(
  @{Name="VERIFY_V10_SNAPSHOT_RESTORE_REHEARSAL.ps1";Blob="bfa57a51e603e465cbe91d22eb95f509614dfc9e"},
  @{Name="VERIFY_V10_RESTORE_TARGET_MAP.ps1";Blob="3f3bad88d490ee5a44f1c45461df58c72672aae2"},
  @{Name="VERIFY_V10_ENCRYPTED_RESTORE_MAP.ps1";Blob="dc17bfd27a140c85cc9e886269fc004e24a9c71f"}
 )
 $stage="PACKAGE_DOWNLOAD_AND_VERIFY"
 $tempRoot=Join-Path ([IO.Path]::GetTempPath()) ("v10_private_audit_"+[guid]::NewGuid().ToString("N"))
 [void](New-Item -ItemType Directory -Path $tempRoot -ErrorAction Stop)
 if ($FixtureRoot) {
  if ($env:GITHUB_ACTIONS -cne "true" -or $env:RUNNER_OS -cne "Windows") {
   Block "FIXTURE_RESTRICTED"
  }
 }
 foreach ($entry in $spec) {
  $dest=Join-Path $tempRoot $entry.Name
  if ($FixtureRoot) {
   Copy-Item -LiteralPath (Join-Path $FixtureRoot $entry.Name) -Destination $dest -ErrorAction Stop
  } else {
   $uri="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/"+$PinnedCommit+
        "/downloads/"+$entry.Name
   Invoke-WebRequest -Uri $uri -OutFile $dest -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop
  }
  $bytes=[IO.File]::ReadAllBytes($dest)
  if ($bytes.Length -lt 500 -or $bytes.Length -gt 100000 -or
      (BHash $bytes) -cne $entry.Blob) {
   Block "SCRIPT_BLOB_MISMATCH"
  }
 }
 $stage="SNAPSHOT_VERIFY"
 $verifier=Join-Path $tempRoot "VERIFY_V10_SNAPSHOT_RESTORE_REHEARSAL.ps1"
 $s=RunPS ("& "+(Quote $verifier)+" -Snapshot "+(Quote $snapshot)+" -Mode VerifyOnly")
 if ($s.Code -ne 0 -or @($s.Lines) -cnotcontains "SNAPSHOT_RECEIPT=VERIFY_PASS") {
  Block "SNAPSHOT_VERIFICATION_FAILED"
 }
 $stage="DESKTOP_SCOPE"
 $paths=@(
  [Environment]::GetFolderPath("Desktop"),
  (Join-Path $env:USERPROFILE "Desktop"),
  (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
  [Environment]::GetFolderPath("CommonDesktopDirectory")
 )
 $allowedRoots=New-Object 'System.Collections.Generic.List[string]'
 $unique=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
 foreach ($p in $paths) {
  if (-not $p) { continue }
  $full=[IO.Path]::GetFullPath([string]$p)
  if ($unique.Add($full.TrimEnd([char]92))) { [void]$allowedRoots.Add($full) }
 }
 if ($allowedRoots.Count -lt 1 -or $allowedRoots.Count -gt 4) { Block "DESKTOP_SCOPE_INVALID" }
 $stage="MAP_SCAN"
 $scan=Join-Path $tempRoot "VERIFY_V10_RESTORE_TARGET_MAP.ps1"
 $roots=@($allowedRoots.ToArray() | ForEach-Object { Quote $_ })
 $snippet="& "+(Quote $scan)+" -Snapshot "+(Quote $snapshot)+
   " -RepoRoot "+(Quote $repo)+" -StateRoot "+(Quote $state)+
   " -DesktopRoots @("+($roots -join ",")+")"
 if ($Mode -eq "SaveAndVerify") { $snippet+=" -SaveEncryptedMap" }
 $result=RunPS $snippet
 EmitPublic $result.Lines
 if ($result.Code -ne 0 -or
     -not (@($result.Lines) -match '^TARGET_MAP_STATUS=(READONLY_MATCH_ONLY|PARTIAL_HOLD)$')) {
  Block "MAP_SCAN_FAILED"
 }
 if ($Mode -eq "Inspect") {
  Write-Output "P0_23_RESULT=INSPECT_ONLY"
  Write-Output "CUTOVER_ELIGIBLE=false"
  Write-Output "REAL_SUBMIT_ALLOWED=false"
  exit 0
 }
 $stage="ENCRYPTED_MAP_VERIFY"
 if (@($result.Lines) -cnotcontains "ENCRYPTED_MAP_RESULT=SAVED_PRIVATE_ONLY") {
  Block "PRIVATE_MAP_NOT_SAVED"
 }
 $idLines=@($result.Lines | Where-Object { [string]$_ -cmatch '^ENCRYPTED_MAP_ID=[0-9a-f]{32}$' })
 if ($idLines.Count -ne 1) { Block "MAP_ID_MISSING" }
 $mapId=([string]$idLines[0]).Substring(17)
 $independent=Join-Path $tempRoot "VERIFY_V10_ENCRYPTED_RESTORE_MAP.ps1"
 $check=RunPS ("& "+(Quote $independent)+" -MapId "+(Quote $mapId)+
   " -RepoRoot "+(Quote $repo)+" -StateRoot "+(Quote $state))
 EmitPublic $check.Lines
 if ($check.Code -ne 0 -or
     -not (@($check.Lines) -match '^ENCRYPTED_MAP_RECEIPT=VERIFIED_PARTIAL_HOLD$')) {
  Block "PRIVATE_MAP_VERIFICATION_FAILED"
 }
 Write-Output "P0_23_RESULT=ENCRYPTED_PARTIAL_HOLD"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 0
} catch {
 $safe="GENERIC_FAILURE"
 $known=@("SNAPSHOT_NOT_FOUND","REPO_NOT_FOUND","FIXTURE_RESTRICTED",
  "SCRIPT_BLOB_MISMATCH","SNAPSHOT_VERIFICATION_FAILED","DESKTOP_SCOPE_INVALID",
  "MAP_SCAN_FAILED","PRIVATE_MAP_NOT_SAVED","MAP_ID_MISSING",
  "PRIVATE_MAP_VERIFICATION_FAILED")
 if ($known -ccontains [string]$_.Exception.Message) {
  $safe=[string]$_.Exception.Message
 }
 Write-Output ("P0_23_BLOCK_STAGE="+$stage)
 Write-Output ("P0_23_BLOCK_REASON="+$safe)
 Write-Output "P0_23_RESULT=BLOCKED"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 2
} finally {
 if ($tempRoot -and (Test-Path -LiteralPath $tempRoot)) {
  Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
 }
}
