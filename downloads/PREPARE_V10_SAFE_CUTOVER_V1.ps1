<#
P0-19: staged transition checkpoint for the *observed* old Starter/DEBUG entry.
Plan is read-only. BackupOnly copies whitelisted entry/code files to a NEW
private local snapshot and verifies every hash. No startup, stop, git checkout,
network, process scan, Excel, broker, account, data CSV, CMD/shortcut mutation,
or rollback/apply is implemented. Windows PowerShell 5.1 compatible, ASCII source.
#>
param(
 [ValidateSet("Plan","BackupOnly")][string]$Mode = "Plan",
 [string]$RepoRoot = "C:\AI_Cockpit_Current\trade-cockpit",
 [string]$StateRoot = "C:\AI_Cockpit_OneClick_Starter",
 [string]$BackupRoot = "",
 [string[]]$DesktopRoots = @(),
 [string]$ExpectedBranch = "fix/p0-v10-brain-safe-stop-preflight-20261017",
 [string]$ExpectedSha = "",
 [switch]$SelfTest
)
$ErrorActionPreference = "Stop"
function Assert-Regular([string]$Path) {
 $entry = Get-Item -LiteralPath $Path -ErrorAction Stop
 if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
  throw "REPARSE_REFUSED"
 }
 return $entry
}
function Get-Hash([string]$Path) {
 return (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToUpperInvariant()
}
function Get-Candidates([string]$Repo,[string]$State,[string[]]$Desktops) {
 $items = New-Object 'System.Collections.Generic.List[object]'
 foreach ($x in @(
   @{ Path=(Join-Path $State "START_AI_COCKPIT.ps1"); Key="starter/START_AI_COCKPIT.ps1"; Essential=$true },
   @{ Path=(Join-Path $State "AI_COCKPIT_START_DEBUG.cmd"); Key="starter/AI_COCKPIT_START_DEBUG.cmd"; Essential=$true },
   @{ Path=(Join-Path $Repo "downloads\RUN_AI_COCKPIT_V10.ps1"); Key="repo/RUN_AI_COCKPIT_V10.ps1"; Essential=$true },
   @{ Path=(Join-Path $Repo "downloads\STOP_AI_COCKPIT_V10.ps1"); Key="repo/STOP_AI_COCKPIT_V10.ps1"; Essential=$true },
   @{ Path=(Join-Path $Repo "downloads\AI_COCKPIT_CONTROLLER_V10.ps1"); Key="repo/AI_COCKPIT_CONTROLLER_V10.ps1"; Essential=$true },
   @{ Path=(Join-Path $Repo "downloads\AI_COCKPIT_GATEWAY_V10.ps1"); Key="repo/AI_COCKPIT_GATEWAY_V10.ps1"; Essential=$false },
   @{ Path=(Join-Path $Repo "downloads\START_AI_COCKPIT_V10.cmd"); Key="repo/START_AI_COCKPIT_V10.cmd"; Essential=$false },
   @{ Path=(Join-Path $Repo "downloads\STOP_AI_COCKPIT_V10.cmd"); Key="repo/STOP_AI_COCKPIT_V10.cmd"; Essential=$false },
   @{ Path=(Join-Path $Repo "scripts\ai_brain_observer.py"); Key="repo/ai_brain_observer.py"; Essential=$false }
 )) { [void]$items.Add($x) }
 $i = 0
 foreach ($d in $Desktops) {
  $i += 1
  if (-not (Test-Path -LiteralPath $d -PathType Container)) { continue }
  [void](Assert-Regular $d)
  # Only entry files; never back up personal workbooks, runtime or market data.
  $found = @(Get-ChildItem -LiteralPath $d -File -ErrorAction Stop |
     Where-Object { $_.Name -like "AI*.cmd" -or $_.Name -like "AI*.lnk" })
  if ($found.Count -gt 40) { throw "TOO_MANY_DESKTOP_ENTRIES" }
  foreach ($file in $found) {
   [void]$items.Add(@{
      Path=$file.FullName
      Key=("desktop" + $i + "/" + $file.Name)
      Essential=$false
   })
  }
 }
 return $items.ToArray()
}

if ($SelfTest) {
 if ($Mode -ne "Plan") { throw "SELFTEST_PLAN_ONLY" }
 Write-Output "PASS: P0_19_PARSE_AND_PLAN_ENTRY"
 exit 0
}
$modeResult="BLOCKED"
$stage = "VALIDATE_ARGS"
try {
 if (-not [string]::IsNullOrWhiteSpace($ExpectedSha) -and
     $ExpectedSha -cnotmatch '^[0-9a-fA-F]{40}$') { throw "BAD_PIN" }
 if ([string]::IsNullOrWhiteSpace($ExpectedBranch)) { throw "BRANCH_REQUIRED" }
 $stage = "VALIDATE_ROOTS"
 $repo = [IO.Path]::GetFullPath($RepoRoot)
 $state = [IO.Path]::GetFullPath($StateRoot)
 [void](Assert-Regular $repo)
 [void](Assert-Regular $state)
 $stage = "RESOLVE_DESKTOPS"
 $desktops = @()
 if ($DesktopRoots.Count -gt 0) {
  $desktops = @($DesktopRoots | Where-Object { $_ } |
   ForEach-Object { [IO.Path]::GetFullPath($_) } | Select-Object -Unique)
 } else {
  $desktops = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
    [Environment]::GetFolderPath("CommonDesktopDirectory")
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    ForEach-Object { [IO.Path]::GetFullPath($_) } | Select-Object -Unique
 }
 if ($desktops.Count -lt 1) { throw "DESKTOP_REQUIRED" }
 $stage = "DISCOVER_CANDIDATES"
 $items=@(Get-Candidates $repo $state $desktops)
 if ($items.Count -lt 5 -or $items.Count -gt 110) { throw "INVALID_INPUT_COUNT" }
 $present=New-Object 'System.Collections.Generic.List[object]'
 $essentialMissing=0
 $desktopCmds=0
 $desktopLinks=0
 $stage = "VERIFY_FILES"
 foreach ($item in $items) {
  if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) {
   if ($item.Essential) { $essentialMissing+=1 }
   continue
  }
  $info=Assert-Regular $item.Path
  if ($info.Length -le 0 -or $info.Length -gt 1048576) { throw "INVALID_ENTRY_SIZE" }
  if ([string]$item.Key -like "desktop*/*.cmd") { $desktopCmds+=1 }
  if ([string]$item.Key -like "desktop*/*.lnk") { $desktopLinks+=1 }
  [void]$present.Add([pscustomobject]@{
     Key=[string]$item.Key; Path=[string]$item.Path; Sha256=(Get-Hash $item.Path);
     Bytes=[long]$info.Length
  })
 }
 $stage = "VERIFY_GIT_STATE"
 $head=(& git -C $repo rev-parse HEAD 2>$null)
 $gitStatus=$LASTEXITCODE
 $actualBranch=(& git -C $repo rev-parse --abbrev-ref HEAD 2>$null)
 $branchStatus=$LASTEXITCODE
 $dirty=@(& git -C $repo status --porcelain --untracked-files=no 2>$null)
 $dirtyStatus=$LASTEXITCODE
 $pinMatch=($gitStatus -eq 0 -and $branchStatus -eq 0 -and $dirtyStatus -eq 0 -and
   $dirty.Count -eq 0 -and $ExpectedSha -and
   [string]$head -ceq $ExpectedSha -and [string]$actualBranch -ceq $ExpectedBranch)
 Write-Output ("SOURCE_PIN_MATCH=" + ([bool]$pinMatch).ToString().ToLowerInvariant())
 Write-Output ("ENTRY_FILE_COUNT=" + $present.Count)
 Write-Output ("DESKTOP_CMD_COUNT=" + $desktopCmds)
 Write-Output ("DESKTOP_LNK_COUNT=" + $desktopLinks)
 Write-Output ("ESSENTIAL_MISSING=" + $essentialMissing)
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 $stage = "PLAN_COMPLETE"
 if ($Mode -eq "Plan") {
  Write-Output "CUTOVER_PLAN=READ_ONLY"
  exit 0
 }
 $stage = "BACKUP_PRECONDITIONS"
 if ($essentialMissing -ne 0 -or $desktopCmds -lt 2 -or $desktopLinks -lt 1) {
  throw "BACKUP_INPUT_INCOMPLETE"
 }
 $stage = "BACKUP_TARGET"
 if (-not $BackupRoot) { $BackupRoot=Join-Path $state "V10_cutover_snapshots" }
 $root=[IO.Path]::GetFullPath($BackupRoot)
 foreach ($source in @($repo,$state)+$desktops) {
  if ($root.StartsWith($source.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase) -and
      -not [string]::Equals($source,$state,[StringComparison]::OrdinalIgnoreCase)) {
   throw "BACKUP_ROOT_INSIDE_SOURCE"
  }
 }
 if ([string]::Equals($root,$repo,[StringComparison]::OrdinalIgnoreCase) -or
     [string]::Equals($root,$state,[StringComparison]::OrdinalIgnoreCase)) {
  throw "BACKUP_ROOT_COLLISION"
 }
 if (-not (Test-Path -LiteralPath $root -PathType Container)) {
  New-Item -ItemType Directory -Path $root -ErrorAction Stop | Out-Null
 }
 [void](Assert-Regular $root)
 # Random local snapshot id, create-only. Never overwrite an existing backup.
 $id=(Get-Date -Format "yyyyMMdd_HHmmss") + "_" + [guid]::NewGuid().ToString("N").Substring(0,12)
 $snapshot=Join-Path $root $id
 New-Item -ItemType Directory -Path $snapshot -ErrorAction Stop | Out-Null
 $stage = "BACKUP_COPY_VERIFY"
 $receipts=New-Object 'System.Collections.Generic.List[object]'
 foreach ($entry in $present) {
  $dest=Join-Path $snapshot ($entry.Key.Replace('/',[IO.Path]::DirectorySeparatorChar))
  $parent=Split-Path -Parent $dest
  if (-not (Test-Path -LiteralPath $parent)) {
   New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop | Out-Null
  }
  if (Test-Path -LiteralPath $dest) { throw "BACKUP_DEST_COLLISION" }
  Copy-Item -LiteralPath $entry.Path -Destination $dest -ErrorAction Stop
  $before=(Get-Hash $entry.Path)
  $after=(Get-Hash $dest)
  if ($before -cne $entry.Sha256 -or $after -cne $before) {
   throw "BACKUP_HASH_MISMATCH"
  }
  [void]$receipts.Add([ordered]@{ name=$entry.Key; sha256=$after; bytes=$entry.Bytes })
 }
 $stage = "BACKUP_MANIFEST"
 $manifest=[ordered]@{
   schema="v10_cutover_backup_v1"
   evidence_only=$true
   no_changes_to_active_files=$true
   real_submit_allowed=$false
   source_pin_match=[bool]$pinMatch
   files=@($receipts.ToArray())
 }
 $receiptFile=Join-Path $snapshot "manifest.json"
 [IO.File]::WriteAllText($receiptFile,($manifest | ConvertTo-Json -Depth 5),
                         (New-Object Text.UTF8Encoding($false)))
 if (-not (Test-Path -LiteralPath $receiptFile)) { throw "MANIFEST_MISSING" }
 $modeResult="BACKUP_VERIFIED"
 Write-Output "BACKUP_RESULT=VERIFIED_LOCAL_ONLY"
 Write-Output ("BACKUP_FILES=" + $receipts.Count)
 Write-Output ("BACKUP_SNAPSHOT_ID=" + $id)
 Write-Output "ACTIVE_ENTRY_FILES_MODIFIED=false"
 Write-Output "CUTOVER_APPLIED=false"
 exit 0
} catch {
 # Never echo the original exception text: OS paths can contain user identity,
 # private Desktop folders or account-related filenames.
 $reason="UNCLASSIFIED"
 $message=[string]$_.Exception.Message
 foreach ($known in @(
  "BAD_PIN","BRANCH_REQUIRED","REPARSE_REFUSED","TOO_MANY_DESKTOP_ENTRIES",
  "DESKTOP_REQUIRED","INVALID_INPUT_COUNT","INVALID_ENTRY_SIZE",
  "BACKUP_INPUT_INCOMPLETE","BACKUP_ROOT_INSIDE_SOURCE",
  "BACKUP_ROOT_COLLISION","BACKUP_DEST_COLLISION",
  "BACKUP_HASH_MISMATCH","MANIFEST_MISSING"
 )) {
  if ($message -ceq $known) { $reason=$known; break }
 }
 if ($reason -eq "UNCLASSIFIED") {
  $ex=$_.Exception
  if ($ex -is [System.UnauthorizedAccessException]) { $reason="ACCESS_DENIED" }
  elseif ($ex -is [System.IO.FileNotFoundException] -or
          $ex -is [System.Management.Automation.ItemNotFoundException] -or
          $ex -is [System.IO.DirectoryNotFoundException]) {
   $reason="PATH_NOT_FOUND"
  }
  elseif ($ex -is [System.IO.IOException]) { $reason="IO_FAILURE" }
  elseif ($ex -is [System.Management.Automation.RuntimeException]) {
   $reason="POWERSHELL_RUNTIME"
  }
 }
 Write-Output ("BLOCK_STAGE="+$stage)
 Write-Output ("BLOCK_REASON="+$reason)
 Write-Output "CUTOVER_PLAN=BLOCKED"
 Write-Output "CUTOVER_APPLIED=false"
 Write-Output "REAL_SUBMIT_ALLOWED=false"
 exit 2
}
