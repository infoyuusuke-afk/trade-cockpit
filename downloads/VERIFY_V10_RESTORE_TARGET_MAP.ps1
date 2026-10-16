<#
P0-21: Read-only, hash-exact source-to-original-target matching for a local
P0-19 snapshot. No actual restore, change, process stop, launch, Git mutation,
network, cross-account discovery, Excel or trade. Optional SaveEncryptedMap
writes a DPAPI CurrentUser-only PRIVATE evidence file, never live launchers.
Use explicit DesktopRoots to avoid accidentally scanning a rejected old account.
Desktop ordinal in the snapshot is NOT a path and is NEVER used as an identity.
#>
param(
 [Parameter(Mandatory=$true)][string]$Snapshot,
 [string]$RepoRoot = "C:\AI_Cockpit_Current\trade-cockpit",
 [string]$StateRoot = "C:\AI_Cockpit_OneClick_Starter",
 [string[]]$DesktopRoots = @(),
 [switch]$SaveEncryptedMap
)
$ErrorActionPreference="Stop"
$stage="ARGUMENTS"
function Fail([string]$Message) { throw $Message }
function Checked([string]$Path) {
 $item=Get-Item -LiteralPath $Path -ErrorAction Stop
 if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
  Fail "REPARSE_REFUSED"
 }
 return $item
}
function SourceCandidates([string]$Folder,[string]$Suffix) {
 $results=@()
 foreach ($entry in @(Get-ChildItem -LiteralPath $Folder -File -Filter ("AI*."+$Suffix) -ErrorAction Stop)) {
  if ($entry.Length -le 0 -or $entry.Length -gt 1048576 -or
      (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
   # A suspicious shortcut cannot be quietly ignored as 'missing'.
   Fail "UNTRUSTED_DESKTOP_ENTRY"
  }
  $results+=@([pscustomobject]@{
    Full=$entry.FullName; Name=$entry.Name; Bytes=[long]$entry.Length
  })
 }
 return $results
}
function FileMatch([string]$Path,[object]$Receipt) {
 if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
 $file=Checked $Path
 if ($file.Length -ne [long]$Receipt.bytes) { return $false }
 $sha=(Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash
 return [string]::Equals($sha,[string]$Receipt.sha256,
                         [StringComparison]::OrdinalIgnoreCase)
}
try {
 $stage="REQUIRE_VERIFIED_SNAPSHOT"
 $verifier=Join-Path $PSScriptRoot "VERIFY_V10_SNAPSHOT_RESTORE_REHEARSAL.ps1"
 [void](Checked $verifier)
 $verification=@(& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $verifier -Snapshot $Snapshot -Mode VerifyOnly)
 if ($LASTEXITCODE -ne 0 -or
     -not (@($verification) -ccontains "SNAPSHOT_RECEIPT=VERIFY_PASS")) {
  Fail "SNAPSHOT_NOT_VERIFIED"
 }
 $dir=[IO.Path]::GetFullPath($Snapshot)
 $m=([IO.File]::ReadAllText((Join-Path $dir "manifest.json"),[Text.Encoding]::UTF8) |
     ConvertFrom-Json -ErrorAction Stop)
 $files=@($m.files)
 $stage="ROOTS"
 $repo=[IO.Path]::GetFullPath($RepoRoot)
 $state=[IO.Path]::GetFullPath($StateRoot)
 [void](Checked $repo);[void](Checked $state)
 [void](Checked (Join-Path $repo "downloads"))
 if ($DesktopRoots.Count -lt 1) { Fail "EXPLICIT_DESKTOP_ROOTS_REQUIRED" }
 if ($DesktopRoots.Count -gt 10) { Fail "TOO_MANY_ROOTS" }
 $roots=New-Object 'System.Collections.Generic.List[string]'
 $rootSeen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
 foreach ($r in $DesktopRoots) {
  if (-not [IO.Path]::IsPathRooted($r)) { Fail "ROOT_NOT_ABSOLUTE" }
  $normalized=[IO.Path]::GetFullPath($r)
  if (-not $rootSeen.Add($normalized.TrimEnd([char]92))) {
   Fail "DUPLICATE_ROOT"
  }
  # Require each explicitly passed root to be a different folder from the
  # checkout and the Starter; no recursion into any user profile is allowed.
  if ($normalized -ieq $repo -or $normalized -ieq $state) {
   Fail "INVALID_DESKTOP_ROOT"
  }
  [void]$roots.Add($normalized)
 }
 $stage="DESKTOP_DISCOVERY"
 $candidates=New-Object 'System.Collections.Generic.List[object]'
 $unverified=New-Object 'System.Collections.Generic.List[int]'
 for ($i=0;$i -lt $roots.Count;$i++) {
  $root=$roots[$i]
  try {
   $di=Checked $root
   if (-not $di.PSIsContainer) { throw "NOT_DESKTOP_DIRECTORY" }
   $entries=@(SourceCandidates $root "cmd") + @(SourceCandidates $root "lnk")
   if ($entries.Count -gt 40) { throw "TOO_MANY_DESKTOP_ENTRIES" }
   foreach ($item in $entries) { [void]$candidates.Add($item) }
  } catch {
   # Quarantine this entire root; no path, username or exception details.
   [void]$unverified.Add($i+1)
  }
 }
 $stage="HASH_MAPPING"
 $mapped=0; $missing=0; $ambiguous=0
 $desktopExpected=0; $desktopMatched=0
 $used=new-object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
 $unresolved=New-Object 'System.Collections.Generic.List[string]'
 $localMatches=New-Object 'System.Collections.Generic.List[object]'
 foreach ($receipt in $files) {
  $rel=[string]$receipt.name
  $part=$rel.Split('/')
  $hits=@()
  if ($part[0] -eq "starter") {
   $candidate=Join-Path $state $part[1]
   if (FileMatch $candidate $receipt) { $hits=@($candidate) }
  } elseif ($part[0] -eq "repo") {
   $candidate=if ($part[1] -eq "ai_brain_observer.py") {
      Join-Path $repo "scripts\ai_brain_observer.py"
   } else { Join-Path (Join-Path $repo "downloads") $part[1] }
   if (FileMatch $candidate $receipt) { $hits=@($candidate) }
  } elseif ($part[0] -cmatch '^desktop[0-9]+$') {
   $desktopExpected++
   # Never use part[0] as a Desktop number: it reflects old enumeration
   # order, not a recoverable original absolute path.
   foreach ($item in $candidates) {
    if ([string]::Equals($item.Name,$part[1],[StringComparison]::OrdinalIgnoreCase) -and
        $item.Bytes -eq [long]$receipt.bytes -and
        (FileMatch $item.Full $receipt)) {
       $hits+=@($item.Full)
    }
   }
  } else { Fail "ENTRY_CLASS_UNEXPECTED" }
  if ($hits.Count -eq 1 -and $used.Add($hits[0])) {
   $mapped++
   [void]$localMatches.Add([ordered]@{
      source=[string]$rel; target=[string]$hits[0];
      sha256=[string]$receipt.sha256; bytes=[long]$receipt.bytes
   })
   if ($part[0] -cmatch '^desktop[0-9]+$') { $desktopMatched++ }
  } elseif ($hits.Count -gt 1) {
   $ambiguous++
   [void]$unresolved.Add($rel)
  } else {
   $missing++
   [void]$unresolved.Add($rel)
  }
 }
 $partial=($m.desktop_inventory_complete -cne $true)
 Write-Output ("SNAPSHOT_ENTRY_COUNT="+$files.Count)
 Write-Output ("TARGET_MATCHED="+$mapped)
 Write-Output ("TARGET_MISSING_OR_CHANGED="+$missing)
 Write-Output ("TARGET_AMBIGUOUS="+$ambiguous)
 Write-Output ("DESKTOP_TARGETS_MATCHED="+$desktopMatched)
 Write-Output ("DESKTOP_TARGETS_EXPECTED="+$desktopExpected)
 Write-Output ("UNVERIFIED_DESKTOP_ROOTS="+$unverified.Count)
 foreach ($idx in $unverified) { Write-Output ("UNVERIFIED_DESKTOP_ROOT_INDEX="+$idx) }
 Write-Output ("SNAPSHOT_INVENTORY_PARTIAL="+$partial.ToString().ToLowerInvariant())
 Write-Output "ORIGINAL_ABSOLUTE_PATHS_EXPORTED=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 if ($mapped -eq $files.Count -and $unverified.Count -eq 0 -and
     -not $partial -and $ambiguous -eq 0) {
  Write-Output "TARGET_MAP_STATUS=READONLY_MATCH_ONLY"
 } else {
  Write-Output "TARGET_MAP_STATUS=PARTIAL_HOLD"
 }
 # Optional OWNER-local-only encrypted receipt. This is NOT a restore map
 # authorization: even when all matches are unique, never mark cutover ready.
 # Absolute targets remain only in a DPAPI CurrentUser-protected payload.
 if ($SaveEncryptedMap) {
  $stage="PRIVATE_MAP_SAVE"
  if ($mapped -lt 1) { Fail "NO_MATCHES_TO_SAVE" }
  Add-Type -AssemblyName System.Security -ErrorAction Stop
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
  if ($null -eq $identity.User) { Fail "WINDOWS_IDENTITY_REQUIRED" }
  $manifestHash=(Get-FileHash -LiteralPath (Join-Path $dir "manifest.json") -Algorithm SHA256).Hash
  $payload=[ordered]@{
   schema="v10_restore_private_map_v1"
   snapshot=$dir
   state_root=$state
   repo_root=$repo
   manifest_sha256=$manifestHash
   owner_sid=$identity.User.Value
   created_utc=[DateTime]::UtcNow.ToString("o")
   desktop_roots=@($roots.ToArray())
   backed_up_entry_count=[int]$files.Count
   matched_entry_count=[int]$mapped
   missing_count=[int]$missing
   ambiguous_count=[int]$ambiguous
   unverified_root_indexes=@($unverified.ToArray())
   desktop_inventory_partial=[bool]$partial
   cutover_eligible=$false
   real_submit_allowed=$false
   matches=@($localMatches.ToArray())
  }
  $json=$payload | ConvertTo-Json -Depth 7 -Compress
  $clear=[Text.Encoding]::UTF8.GetBytes($json)
  $entropy=[Text.Encoding]::UTF8.GetBytes("100B_PROJECT_P0_22_LOCAL_RESTORE_MAP_V1")
  try {
   $cipher=[Security.Cryptography.ProtectedData]::Protect(
    $clear,$entropy,[Security.Cryptography.DataProtectionScope]::CurrentUser)
  } finally {
   [Array]::Clear($clear,0,$clear.Length)
  }
  $root=Join-Path $state "V10_private_restore_maps"
  if (-not (Test-Path -LiteralPath $root -PathType Container)) {
   New-Item -ItemType Directory -Path $root -ErrorAction Stop | Out-Null
  }
  [void](Checked $root)
  $mapId=[guid]::NewGuid().ToString("N")
  $mapPath=Join-Path $root ($mapId+".dpapi")
  if (Test-Path -LiteralPath $mapPath) { Fail "MAP_FILE_COLLISION" }
  $outstream=New-Object IO.FileStream($mapPath,[IO.FileMode]::CreateNew,
       [IO.FileAccess]::Write,[IO.FileShare]::None)
  try { $outstream.Write($cipher,0,$cipher.Length); $outstream.Flush($true) }
  finally { $outstream.Dispose() }
  Write-Output "ENCRYPTED_MAP_RESULT=SAVED_PRIVATE_ONLY"
  Write-Output ("ENCRYPTED_MAP_ID="+$mapId)
  Write-Output "ENCRYPTED_MAP_CUTOVER_READY=false"
 }
 # Without the switch absolutely no local files are created or edited.
 exit 0
} catch {
 $message=[string]$_.Exception.Message
 $safe="UNCLASSIFIED"
 $allow=@("REPARSE_REFUSED","UNTRUSTED_DESKTOP_ENTRY","SNAPSHOT_NOT_VERIFIED",
  "EXPLICIT_DESKTOP_ROOTS_REQUIRED","TOO_MANY_ROOTS","ROOT_NOT_ABSOLUTE",
  "DUPLICATE_ROOT","INVALID_DESKTOP_ROOT","ENTRY_CLASS_UNEXPECTED",
  "NO_MATCHES_TO_SAVE","WINDOWS_IDENTITY_REQUIRED","MAP_FILE_COLLISION")
 if ($allow -ccontains $message) { $safe=$message }
 Write-Output ("BLOCK_STAGE="+$stage)
 Write-Output ("BLOCK_REASON="+$safe)
 Write-Output "TARGET_MAP_STATUS=BLOCKED"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 Write-Output "CUTOVER_ELIGIBLE=false"
 exit 2
}
