<#
P0-20: Verify a local P0-19 snapshot and rehearse a copy to disposable TEMP.
Never applies to live CMD/LNK, Git, running processes, Controller, BRAIN, MS2,
Excel, accounts or real trade. This is NOT a production restore utility.
PowerShell 5.1; ASCII source; no network or remote upload.
#>
param(
 [Parameter(Mandatory=$true)][string]$Snapshot,
 [ValidateSet("VerifyOnly","Rehearse")][string]$Mode="VerifyOnly",
 [string]$StageParent=""
)
$ErrorActionPreference="Stop"
$stage="INPUT"
$reason="UNKNOWN"
function Fail([string]$Kind) { throw $Kind }
function Regular([string]$Path) {
 $item=Get-Item -LiteralPath $Path -ErrorAction Stop
 if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
  Fail "REPARSE_REFUSED"
 }
 return $item
}
function Is-SafeName([string]$Name) {
 if ($Name.Length -lt 1 -or $Name.Length -gt 150 -or
     $Name.IndexOfAny([char[]]@(':','*','?','"','<','>','|')) -ge 0 -or
     $Name.IndexOf([char]92) -ge 0 -or
     $Name.IndexOf([char]0) -ge 0 -or
     $Name.EndsWith(".") -or $Name.EndsWith(" ")) { return $false }
 if ($Name -match '^[.]+$' -or
     $Name -match '^(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)' -or
     $Name -match '[\x00-\x1F]') { return $false }
 return $true
}
function Allowed-Relative([string]$Rel) {
 if ($Rel.Length -gt 220 -or $Rel -match '\\' -or $Rel -match '\.\.') {
  return $false
 }
 $parts=$Rel.Split('/')
 if ($parts.Count -ne 2) { return $false }
 if (-not (Is-SafeName $parts[0]) -or -not (Is-SafeName $parts[1])) {
  return $false
 }
 if ($parts[0] -ceq 'starter') {
  return $parts[1] -cin @('START_AI_COCKPIT.ps1','AI_COCKPIT_START_DEBUG.cmd')
 }
 if ($parts[0] -ceq 'repo') {
  return $parts[1] -cin @('RUN_AI_COCKPIT_V10.ps1',
   'STOP_AI_COCKPIT_V10.ps1','AI_COCKPIT_CONTROLLER_V10.ps1',
   'AI_COCKPIT_GATEWAY_V10.ps1','START_AI_COCKPIT_V10.cmd',
   'STOP_AI_COCKPIT_V10.cmd','ai_brain_observer.py')
 }
 if ($parts[0] -cmatch '^desktop([1-9]|[1-9][0-9])$') {
  return ($parts[1] -cmatch '^AI.{0,120}\.(cmd|lnk)$')
 }
 return $false
}
function Below([string]$Child,[string]$Parent) {
 $base=$Parent.TrimEnd([char]92,[char]47)
 return $Child.StartsWith($base+[string][char]92,
                         [StringComparison]::OrdinalIgnoreCase)
}
try {
 if (-not [IO.Path]::IsPathRooted($Snapshot)) { Fail "ABSOLUTE_PATH_REQUIRED" }
 $dir=[IO.Path]::GetFullPath($Snapshot)
 $rootItem=Regular $dir
 if (-not $rootItem.PSIsContainer) { Fail "SNAPSHOT_DIR_REQUIRED" }
 if (-not ($rootItem.Name -match '^\d{8}_\d{6}_[0-9a-f]{12}$')) {
  Fail "SNAPSHOT_ID_UNVERIFIED"
 }
 $manifestPath=Join-Path $dir "manifest.json"
 $info=Regular $manifestPath
 if ($info.PSIsContainer -or $info.Length -gt 65536 -or $info.Length -lt 10) {
  Fail "MANIFEST_SIZE_INVALID"
 }
 $stage="MANIFEST"
 $m=([IO.File]::ReadAllText($manifestPath,[Text.Encoding]::UTF8) |
    ConvertFrom-Json -ErrorAction Stop)
 if ($m.schema -cne "v10_cutover_backup_v1" -or
     $m.evidence_only -cne $true -or
     $m.no_changes_to_active_files -cne $true -or
     $m.real_submit_allowed -cne $false -or
     $m.cutover_eligible -cne $false) { Fail "MANIFEST_CONTRACT_INVALID" }
 $files=@($m.files)
 if ($files.Count -lt 1 -or $files.Count -gt 110) { Fail "FILE_COUNT_INVALID" }
 $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
 $paths=New-Object 'System.Collections.Generic.List[object]'
 $stage="FILE_VERIFY"
 foreach ($entry in $files) {
  $rel=[string]$entry.name
  if (-not (Allowed-Relative $rel)) { Fail "UNSAFE_ENTRY_PATH" }
  if (-not $seen.Add($rel)) { Fail "DUPLICATE_ENTRY" }
  if ([string]$entry.sha256 -cnotmatch '^[0-9A-Fa-f]{64}$') {
   Fail "ENTRY_HASH_INVALID"
  }
  $expectedBytes=[long]$entry.bytes
  if ($expectedBytes -lt 1 -or $expectedBytes -gt 1048576) {
   Fail "ENTRY_SIZE_INVALID"
  }
  $group=Join-Path $dir $rel.Split('/')[0]
  [void](Regular $group)
  $source=Join-Path $dir ($rel.Replace('/',[string][char]92))
  $sourceInfo=Regular $source
  if ($sourceInfo.PSIsContainer -or $sourceInfo.Length -ne $expectedBytes) {
   Fail "ENTRY_SIZE_MISMATCH"
  }
  $sha=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  if ($sha -ine [string]$entry.sha256) { Fail "ENTRY_HASH_MISMATCH" }
  [void]$paths.Add([pscustomobject]@{Rel=$rel;Full=$source;Hash=$sha})
 }
 # Require the key historical entrypoints, otherwise a valid subset of files
 # cannot be passed off as a usable rollback inventory.
 foreach ($required in @('starter/START_AI_COCKPIT.ps1',
   'starter/AI_COCKPIT_START_DEBUG.cmd',
   'repo/RUN_AI_COCKPIT_V10.ps1',
   'repo/STOP_AI_COCKPIT_V10.ps1',
   'repo/AI_COCKPIT_CONTROLLER_V10.ps1')) {
  if (-not $seen.Contains($required)) { Fail "REQUIRED_ENTRY_ABSENT" }
 }
 $verifiedPartial=($m.desktop_inventory_complete -cne $true)
 $stage="VERIFY_COMPLETE"
 Write-Output ("SNAPSHOT_FILES_VERIFIED="+$paths.Count)
 Write-Output ("SNAPSHOT_INVENTORY="+$(if($verifiedPartial){"PARTIAL"}else{"COMPLETE"}))
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 if ($Mode -eq "VerifyOnly") {
  Write-Output "SNAPSHOT_RECEIPT=VERIFY_PASS"
  exit 0
 }
 # Staged rehearsal NEVER copies into the repo, state root or Desktop.
 # StageParent must live under system TEMP, using a fresh unique child.
 $stage="STAGE_ROOT"
 $temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char]92)
 if (-not $StageParent) { $StageParent=Join-Path $temp "V10_snapshot_rehearsals" }
 $parent=[IO.Path]::GetFullPath($StageParent)
 if (-not (Below $parent $temp)) { Fail "STAGING_MUST_BE_IN_TEMP" }
 # Reject existing junctions anywhere between TEMP and destination before
 # creating any directory. Never resolve through a redirected TEMP subtree.
 $cursor=$parent
 while ($true) {
  if (Test-Path -LiteralPath $cursor) { [void](Regular $cursor) }
  if ([string]::Equals($cursor,$temp,[StringComparison]::OrdinalIgnoreCase)) {
   break
  }
  $ancestor=Split-Path -Parent $cursor
  if (-not $ancestor -or $ancestor -ieq $cursor) { Fail "STAGING_ROOT_UNVERIFIED" }
  $cursor=$ancestor
 }
 if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
  New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop | Out-Null
 }
 [void](Regular $parent)
 # Parent is already constrained to temp, with no active source in this temp
 # subtree. Source snapshot must not be copied into itself.
 if ($parent -ieq $dir -or (Below $parent $dir) -or (Below $dir $parent)) {
  Fail "STAGING_SOURCE_COLLISION"
 }
 $target=Join-Path $parent ("rehearsal_"+[guid]::NewGuid().ToString("N"))
 New-Item -ItemType Directory -Path $target -ErrorAction Stop | Out-Null
 $stage="STAGE_COPY"
 foreach ($entry in $paths) {
  $relative=$entry.Rel.Replace('/',[string][char]92)
  $dest=Join-Path $target $relative
  $destDir=Split-Path -Parent $dest
  if (-not (Test-Path -LiteralPath $destDir)) {
   New-Item -ItemType Directory -Path $destDir -Force -ErrorAction Stop | Out-Null
  }
  Copy-Item -LiteralPath $entry.Full -Destination $dest -ErrorAction Stop
  $copied=(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
  if ($copied -ine $entry.Hash) { Fail "STAGING_HASH_MISMATCH" }
 }
 Write-Output ("REHEARSED_FILES="+$paths.Count)
 Write-Output "REHEARSAL_ISOLATED_TEMP=true"
 Write-Output "LIVE_FILES_MODIFIED=false"
 Write-Output "SNAPSHOT_RECEIPT=REHEARSAL_PASS"
 exit 0
} catch {
 # No raw exception messages or absolute paths leave this diagnostic.
 $reason="GENERIC_FAILURE"
 $msg=[string]$_.Exception.Message
 $known=@('ABSOLUTE_PATH_REQUIRED','REPARSE_REFUSED','SNAPSHOT_DIR_REQUIRED',
  'SNAPSHOT_ID_UNVERIFIED','MANIFEST_SIZE_INVALID','MANIFEST_CONTRACT_INVALID',
  'FILE_COUNT_INVALID','UNSAFE_ENTRY_PATH','DUPLICATE_ENTRY','ENTRY_HASH_INVALID',
  'ENTRY_SIZE_INVALID','ENTRY_SIZE_MISMATCH','ENTRY_HASH_MISMATCH',
  'REQUIRED_ENTRY_ABSENT','STAGING_MUST_BE_IN_TEMP',
  'STAGING_SOURCE_COLLISION','STAGING_HASH_MISMATCH','STAGING_ROOT_UNVERIFIED')
 if ($known -ccontains $msg) { $reason=$msg }
 elseif ($_.Exception -is [System.UnauthorizedAccessException]) {
  $reason="ACCESS_DENIED"
 } elseif ($_.Exception -is [System.IO.IOException]) {
  $reason="IO_FAILURE"
 }
 Write-Output ("BLOCK_STAGE="+$stage)
 Write-Output ("BLOCK_REASON="+$reason)
 Write-Output "SNAPSHOT_RECEIPT=BLOCKED"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 2
}
