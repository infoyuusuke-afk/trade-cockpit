<#
P0-16: Strictly read-only OWNER desktop launch/stop route inventory.
No launch, stop, PowerShell command evaluation, mutation, Excel COM, network or upload.
Reports only coarse classifications. Running state is not accepted by this scan.
#>
param(
 [string]$RepoRoot = "C:\AI_Cockpit_Current\trade-cockpit",
 [string]$DesktopRoot = "",
 [string]$ExpectedBranch = "",
 [string]$ExpectedSha = "",
 [switch]$SelfTest
)
$ErrorActionPreference = "Stop"

function Resolve-ApprovedCmd([string]$Text,[string]$CmdDir) {
 $scriptVar = ""
 $candidates = New-Object 'System.Collections.Generic.List[string]'
 foreach ($raw in ($Text -split '\r?\n')) {
  $line = $raw.Trim()
  if (-not $line -or $line -match '^(?i)(@?echo off|setlocal|endlocal|pause|rem(\s+.*)?|::.*)$') { continue }
  if ($line -match '^(?i)set\s+"SCRIPT=([^"]+)"$') {
   if ($scriptVar) { throw "DUPLICATE_SCRIPT_VARIABLE" }
   $scriptVar = $Matches[1]
   continue
  }
  if ($line -match '^(?i)set\s+"RC=%ERRORLEVEL%"$' -or
      $line -match '^(?i)if not "%RC%"=="0" pause$' -or
      $line -match '^(?i)exit /b %RC%$') { continue }
  if ($line -notmatch '^(?i)powershell(?:\.exe)?\s+' -or
      $line -match '[&|<>^]' -or $candidates.Count) { throw "CMD_UNAPPROVED_OPERATOR" }
  $m = [regex]::Match($line,'(?i)\s-File\s+"([^"]+)"\s*$')
  if (-not $m.Success) { throw "CMD_MISSING_EXPLICIT_FILE" }
  $prefix = $line.Substring(0,$m.Index)
  if ($prefix -notmatch '^(?i)powershell(?:\.exe)?(?:\s+-(?:NoLogo|NoProfile|NonInteractive)|\s+-ExecutionPolicy\s+Bypass)*$') {
   throw "CMD_UNAPPROVED_OPTIONS"
  }
  $dest = $m.Groups[1].Value
  if ($dest -ieq '%SCRIPT%') { $dest = $scriptVar }
  if (-not $dest) { throw "CMD_NO_SCRIPT" }
  if ($dest.StartsWith('%~dp0',[StringComparison]::OrdinalIgnoreCase)) {
   $dest = Join-Path $CmdDir $dest.Substring(5)
  } elseif ($dest.Contains('%')) { throw "CMD_UNRESOLVED_VARIABLE" }
  if (-not [IO.Path]::IsPathRooted($dest)) { throw "CMD_NONABSOLUTE_TARGET" }
  [void]$candidates.Add([IO.Path]::GetFullPath($dest))
 }
 if ($candidates.Count -ne 1) { throw "CMD_NOT_UNIQUE" }
 return $candidates[0]
}

function Get-TargetClass([string]$CmdPath,[string]$ExpectedFile) {
 try {
  $item = Get-Item -LiteralPath $CmdPath -ErrorAction Stop
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
       $item.Length -gt 16384) { return "BLOCKED" }
  $body = [IO.File]::ReadAllText($CmdPath,[Text.Encoding]::UTF8)
  $target = Resolve-ApprovedCmd $body (Split-Path -Parent $CmdPath)
  $expected = [IO.Path]::GetFullPath($ExpectedFile)
  if (-not [string]::Equals($target,$expected,[StringComparison]::OrdinalIgnoreCase)) {
   return "LEGACY_OR_FOREIGN"
  }
  return "EXPECTED"
 } catch { return "BLOCKED" }
}

function Test-StopCode([string]$Root) {
 try {
  $stop = Join-Path $Root "downloads\STOP_AI_COCKPIT_V10.ps1"
  $item = Get-Item -LiteralPath $stop -ErrorAction Stop
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return "BLOCKED" }
  $body = [IO.File]::ReadAllText($stop,[Text.Encoding]::UTF8)
  foreach ($required in @(
    'Test-ExactBrainHandle',
    'brain_observer_pid',
    'WaitForExit(5000)',
    'Latest BRAIN PID/state unverified'
  )) { if (-not $body.Contains($required)) { return "BLOCKED" } }
  return "PRESENT"
 } catch { return "BLOCKED" }
}

function Test-StartCode([string]$Root) {
 try {
  $runner = Join-Path $Root "downloads\RUN_AI_COCKPIT_V10.ps1"
  $item = Get-Item -LiteralPath $runner -ErrorAction Stop
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return "BLOCKED" }
  $body = [IO.File]::ReadAllText($runner,[Text.Encoding]::UTF8)
  foreach ($required in @('AI_COCKPIT_CONTROLLER_V10.ps1','ExpectedSha',
                          'Branch mismatch after checkout','SHA mismatch after checkout')) {
   if (-not $body.Contains($required)) { return "BLOCKED" }
  }
  return "PRESENT"
 } catch { return "BLOCKED" }
}

function Get-DesktopInventory([string]$Desktop,[string]$Root) {
 $result = [ordered]@{ Stop = "MISSING"; Start = "MISSING"; StopCount = 0; StartCount = 0 }
 if (-not (Test-Path -LiteralPath $Desktop -PathType Container)) { return $result }
 $dirInfo = Get-Item -LiteralPath $Desktop
 if (($dirInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
  $result.Stop = "BLOCKED"; $result.Start = "BLOCKED"; return $result
 }
 $stopCandidates = @(Get-ChildItem -LiteralPath $Desktop -File -ErrorAction Stop |
     Where-Object { $_.Name -ceq "AIコクピット_安全停止.cmd" })
 $startCandidates = @(Get-ChildItem -LiteralPath $Desktop -File -ErrorAction Stop |
     Where-Object { $_.Name -ceq "AIコクピット_起動.cmd" })
 $result.StopCount = $stopCandidates.Count
 $result.StartCount = $startCandidates.Count
 if ($stopCandidates.Count -gt 1 -or $startCandidates.Count -gt 1) {
  $result.Stop = "BLOCKED"; $result.Start = "BLOCKED"; return $result
 }
 if ($stopCandidates.Count -eq 1) {
  $result.Stop = Get-TargetClass $stopCandidates[0].FullName (Join-Path $Root "downloads\STOP_AI_COCKPIT_V10.ps1")
 }
 if ($startCandidates.Count -eq 1) {
  $result.Start = Get-TargetClass $startCandidates[0].FullName (Join-Path $Root "downloads\RUN_AI_COCKPIT_V10.ps1")
 }
 return $result
}

if ($SelfTest) {
 $root = Join-Path $env:TEMP "safe-test"
 $valid = '@echo off'+[char]10+'setlocal'+[char]10+'set "SCRIPT=%~dp0STOP_AI_COCKPIT_V10.ps1"'+[char]10+'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"'+[char]10+'set "RC=%ERRORLEVEL%"'+[char]10+'if not "%RC%"=="0" pause'+[char]10+'exit /b %RC%'
 if (-not (Resolve-ApprovedCmd $valid $root).EndsWith('STOP_AI_COCKPIT_V10.ps1',[StringComparison]::OrdinalIgnoreCase)) { throw "GOOD_CMD_REFUSED" }
 foreach ($bad in @(
  'powershell.exe -NoProfile -File "%UNTRUSTED%"',
  'powershell.exe -NoProfile -File "C:\safe\STOP_AI_COCKPIT_V10.ps1" & taskkill /im EXCEL.EXE',
  'cmd /c stop-all.cmd'
 )) {
  $rejected=$false
  try { [void](Resolve-ApprovedCmd $bad $root) } catch { $rejected=$true }
  if (-not $rejected) { throw "BAD_CMD_ACCEPTED" }
 }
 Write-Output "PASS: P0_16_DESKTOP_ROUTE_PARSER"
 exit 0
}

$pin = "BLOCKED"
$source = "BLOCKED"
$startSource = "BLOCKED"
$desktopStop = "MISSING"
$desktopStart = "MISSING"
try {
 if ($ExpectedSha -notmatch '^[0-9a-fA-F]{40}$' -or -not $ExpectedBranch) {
  throw "PIN_REQUIRED"
 }
 $root = [IO.Path]::GetFullPath($RepoRoot)
 $rootItem = Get-Item -LiteralPath $root -ErrorAction Stop
 if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "UNTRUSTED_REPO" }
 $head = (& git -C $root rev-parse HEAD 2>$null)
 if ($LASTEXITCODE -ne 0 -or [string]$head -cne $ExpectedSha) { throw "SHA_MISMATCH" }
 $branch = (& git -C $root rev-parse --abbrev-ref HEAD 2>$null)
 if ($LASTEXITCODE -ne 0 -or [string]$branch -cne $ExpectedBranch) { throw "BRANCH_MISMATCH" }
 $changes = @(& git -C $root status --porcelain --untracked-files=no 2>$null)
 if ($LASTEXITCODE -ne 0 -or $changes.Count -gt 0) { throw "DIRTY_CHECKOUT" }
 $pin = "VERIFIED"
 $source = Test-StopCode $root
 $startSource = Test-StartCode $root
 if (-not $DesktopRoot) {
  $DesktopRoot = [Environment]::GetFolderPath('Desktop')
 }
 if (-not $DesktopRoot) { throw "DESKTOP_NOT_RESOLVED" }
 $desktop = [IO.Path]::GetFullPath($DesktopRoot)
 $inventory = Get-DesktopInventory $desktop $root
 $desktopStop = $inventory.Stop
 $desktopStart = $inventory.Start
} catch {
 # Deliberately do not print absolute Windows paths, CMD text, JSON, or secrets.
}
Write-Output ("V10_PIN="+$pin)
Write-Output ("V10_STOP_SOURCE="+$source)
Write-Output ("V10_START_SOURCE="+$startSource)
Write-Output ("DESKTOP_STOP_ROUTE="+$desktopStop)
Write-Output ("DESKTOP_START_ROUTE="+$desktopStart)
Write-Output "OWNER_LIVE_RUNTIME_VERIFIED=0"
Write-Output "REAL_SUBMIT_ALLOWED=0"
if ($pin -eq "VERIFIED" -and $source -eq "PRESENT" -and $startSource -eq "PRESENT" -and $desktopStop -eq "EXPECTED" -and $desktopStart -eq "EXPECTED") {
 Write-Output "V10_OWNER_DESKTOP_INVENTORY=ROUTES_READONLY_VERIFIED"
 exit 0
}
Write-Output "V10_OWNER_DESKTOP_INVENTORY=BLOCKED"
exit 2
