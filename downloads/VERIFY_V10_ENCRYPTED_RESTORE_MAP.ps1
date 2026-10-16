<#
P0-22: Independent verifier for a DPAPI CurrentUser encrypted local-only
source -> original-target evidence record. Never restores, starts, stops,
uses external account profiles, accesses workbooks, networks or places orders.
#>
param(
 [Parameter(Mandatory=$true)][string]$MapId,
 [string]$StateRoot="C:\AI_Cockpit_OneClick_Starter",
 [string]$RepoRoot="C:\AI_Cockpit_Current\trade-cockpit"
)
$ErrorActionPreference="Stop"
$stage="INPUT"
function Fail([string]$Reason) { throw $Reason }
function Regular([string]$Path) {
 $item=Get-Item -LiteralPath $Path -ErrorAction Stop
 if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
  Fail "REPARSE_REFUSED"
 }
 return $item
}
function EqualsPath([string]$A,[string]$B) {
 return [string]::Equals([IO.Path]::GetFullPath($A).TrimEnd([char]92),
   [IO.Path]::GetFullPath($B).TrimEnd([char]92),
   [StringComparison]::OrdinalIgnoreCase)
}
try {
 if ($MapId -cnotmatch '^[0-9a-f]{32}$') { Fail "BAD_MAP_ID" }
 $state=[IO.Path]::GetFullPath($StateRoot)
 $repo=[IO.Path]::GetFullPath($RepoRoot)
 [void](Regular $state)
 [void](Regular $repo)
 $dir=Join-Path $state "V10_private_restore_maps"
 [void](Regular $dir)
 $file=Join-Path $dir ($MapId+".dpapi")
 $info=Regular $file
 if ($info.PSIsContainer -or $info.Length -le 32 -or $info.Length -gt 262144) {
  Fail "BAD_CIPHER_SIZE"
 }
 $stage="DECRYPT"
 Add-Type -AssemblyName System.Security -ErrorAction Stop
 $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
 $entropy=[Text.Encoding]::UTF8.GetBytes("100B_PROJECT_P0_22_LOCAL_RESTORE_MAP_V1")
 $encrypted=[IO.File]::ReadAllBytes($file)
 $plain=[Security.Cryptography.ProtectedData]::Unprotect(
  $encrypted,$entropy,[Security.Cryptography.DataProtectionScope]::CurrentUser)
 try {
  $record=([Text.Encoding]::UTF8.GetString($plain) |
           ConvertFrom-Json -ErrorAction Stop)
 } finally { [Array]::Clear($plain,0,$plain.Length) }
 if ($record.schema -cne "v10_restore_private_map_v1" -or
     $record.owner_sid -cne $identity.User.Value -or
     $record.cutover_eligible -cne $false -or
     $record.real_submit_allowed -cne $false -or
     -not (EqualsPath ([string]$record.state_root) $state) -or
     -not (EqualsPath ([string]$record.repo_root) $repo)) {
  Fail "MAP_CONTRACT_INVALID"
 }
 $entries=@($record.matches)
 if ($entries.Count -lt 1 -or $entries.Count -gt 110 -or
     $entries.Count -ne [int]$record.matched_entry_count) {
  Fail "MAP_COUNT_INVALID"
 }
 $roots=@($record.desktop_roots)
 if ($roots.Count -lt 1 -or $roots.Count -gt 10) {
  Fail "MAP_ROOTS_INVALID"
 }
 foreach ($root in $roots) {
  if (-not [IO.Path]::IsPathRooted([string]$root)) { Fail "MAP_ROOTS_INVALID" }
 }
 $stage="SNAPSHOT_REVERIFY"
 $snapshot=[string]$record.snapshot
 if (-not [IO.Path]::IsPathRooted($snapshot)) { Fail "MAP_CONTRACT_INVALID" }
 $script=Join-Path $PSScriptRoot "VERIFY_V10_SNAPSHOT_RESTORE_REHEARSAL.ps1"
 [void](Regular $script)
 $check=@(& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -Snapshot $snapshot -Mode VerifyOnly)
 if ($LASTEXITCODE -ne 0 -or
     -not (@($check) -ccontains "SNAPSHOT_RECEIPT=VERIFY_PASS")) {
  Fail "SNAPSHOT_CHANGED"
 }
 $manifest=Join-Path $snapshot "manifest.json"
 if ((Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash -ine
     [string]$record.manifest_sha256) { Fail "MANIFEST_CHANGED" }
 $m=([IO.File]::ReadAllText($manifest,[Text.Encoding]::UTF8) |
     ConvertFrom-Json -ErrorAction Stop)
 $receipts=@{}
 foreach ($entry in @($m.files)) {
  $key=[string]$entry.name
  if ($receipts.ContainsKey($key)) { Fail "MANIFEST_AMBIGUOUS" }
  $receipts[$key]=$entry
 }
 $stage="TARGET_RECHECK"
 $seenSources=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
 $seenTargets=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
 $stale=0
 $matched=0
 foreach ($item in $entries) {
  $relative=[string]$item.source
  $target=[string]$item.target
  if (-not $receipts.ContainsKey($relative) -or
      -not $seenSources.Add($relative) -or
      -not [IO.Path]::IsPathRooted($target)) { Fail "TARGET_MAP_INVALID" }
  $parts=$relative.Split('/')
  if ($parts.Count -ne 2) { Fail "TARGET_MAP_INVALID" }
  $filename=$parts[1]
  $permitted=$false
  if ($parts[0] -ceq "starter") {
   $permitted=(EqualsPath $target (Join-Path $state $filename))
  } elseif ($parts[0] -ceq "repo") {
   $expected=if($filename -ceq "ai_brain_observer.py") {
    Join-Path $repo ("scripts\"+$filename)
   } else { Join-Path $repo ("downloads\"+$filename) }
   $permitted=(EqualsPath $target $expected)
  } elseif ($parts[0] -cmatch '^desktop[0-9]+$') {
   foreach ($root in $roots) {
    if (EqualsPath $target (Join-Path ([string]$root) $filename)) {
     $permitted=$true
     break
    }
   }
  }
  if (-not $permitted -or -not $seenTargets.Add($target)) {
   Fail "TARGET_MAP_INVALID"
  }
  $saved=$receipts[$relative]
  if ([string]$item.sha256 -ine [string]$saved.sha256 -or
      [long]$item.bytes -ne [long]$saved.bytes) {
   Fail "TARGET_MAP_INVALID"
  }
  $targetOk=$false
  try {
   if (Test-Path -LiteralPath $target -PathType Leaf) {
    $current=Regular $target
    if ($current.Length -eq [long]$saved.bytes) {
     $targetOk=((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ieq
                [string]$saved.sha256)
    }
   }
  } catch { $targetOk=$false }
  if ($targetOk) { $matched++ } else { $stale++ }
 }
 $partial=([bool]$record.desktop_inventory_partial -or
           ($m.desktop_inventory_complete -cne $true) -or
           @($record.unverified_root_indexes).Count -gt 0 -or
           [int]$record.missing_count -gt 0 -or
           [int]$record.ambiguous_count -gt 0)
 Write-Output ("MAP_RECHECK_MATCHED="+$matched)
 Write-Output ("MAP_RECHECK_STALE="+$stale)
 Write-Output ("MAP_TOTAL_ARCHIVED="+@($m.files).Count)
 Write-Output ("MAP_INVENTORY_PARTIAL="+$partial.ToString().ToLowerInvariant())
 Write-Output "ABSOLUTE_PATHS_EXPORTED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 if ($stale -gt 0) {
  Write-Output "ENCRYPTED_MAP_RECEIPT=STALE_HOLD"
 } elseif ($partial) {
  Write-Output "ENCRYPTED_MAP_RECEIPT=VERIFIED_PARTIAL_HOLD"
 } else {
  Write-Output "ENCRYPTED_MAP_RECEIPT=VERIFIED_READONLY_NOT_AUTHORIZED"
 }
 exit 0
} catch {
 $known=@("BAD_MAP_ID","REPARSE_REFUSED","BAD_CIPHER_SIZE",
  "MAP_CONTRACT_INVALID","MAP_COUNT_INVALID","MAP_ROOTS_INVALID",
  "SNAPSHOT_CHANGED","MANIFEST_CHANGED","MANIFEST_AMBIGUOUS",
  "TARGET_MAP_INVALID")
 $reason="UNCLASSIFIED"
 if ($known -ccontains [string]$_.Exception.Message) {
  $reason=[string]$_.Exception.Message
 }
 Write-Output ("BLOCK_STAGE="+$stage)
 Write-Output ("BLOCK_REASON="+$reason)
 Write-Output "ENCRYPTED_MAP_RECEIPT=BLOCKED"
 Write-Output "ABSOLUTE_PATHS_EXPORTED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 2
}
