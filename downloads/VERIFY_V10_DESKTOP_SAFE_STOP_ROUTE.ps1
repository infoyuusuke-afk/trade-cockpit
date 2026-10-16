<#
Read-only P0-15 verification of an explicitly supplied OWNER Desktop CMD stop route.
No command execution, shutdown, Git mutation, installation, or private data export.
VERIFIED_READONLY only means the CMD text calls the pinned local STOP script.
#>
param(
 [string]$RepoRoot = "",
 [string]$DesktopStopCmd = "",
 [string]$ExpectedBranch = "",
 [string]$ExpectedSha = "",
 [switch]$SelfTest
)
$ErrorActionPreference = "Stop"

function Resolve-V10StopCmdTarget([string]$Body,[string]$CmdDir) {
 $scriptVar = ""
 $targets = New-Object 'System.Collections.Generic.List[string]'
 foreach ($rawLine in ($Body -split '\r?\n')) {
  $line = $rawLine.Trim()
  if ([string]::IsNullOrWhiteSpace($line) -or
      $line -match '^(?i)(@echo off|setlocal|endlocal|pause|rem(\s+.*)?|::.*|title\s+.*|chcp\s+\d+)$') { continue }
  if ($line -match '^(?i)set\s+"SCRIPT=([^"]+)"$') {
   if ($scriptVar -ne "") { throw "DUPLICATE_SCRIPT_VARIABLE" }
   $scriptVar = $Matches[1]
   continue
  }
  if ($line -match '^(?i)set\s+"RC=%ERRORLEVEL%"$' -or
      $line -match '^(?i)if not "%RC%"=="0" pause$' -or
      $line -match '^(?i)exit /b %RC%$') { continue }
  if ($line -notmatch '^(?i)powershell(?:\.exe)?\s+') { throw "UNAPPROVED_CMD_OPERATION" }
  if ($targets.Count -gt 0 -or $line -match '[&|<>^]') { throw "MULTIPLE_OR_UNSAFE_COMMAND" }
  $fileArg = [regex]::Match($line,'(?i)\s-File\s+"([^"]+)"\s*$')
  if (-not $fileArg.Success) { throw "STOP_SCRIPT_TARGET_NOT_EXPLICIT" }
  $prefix = $line.Substring(0,$fileArg.Index)
  if ($prefix -notmatch '^(?i)powershell(?:\.exe)?(?:\s+-(?:NoLogo|NoProfile|NonInteractive)|\s+-ExecutionPolicy\s+Bypass)*$') {
   throw "UNAPPROVED_POWERSHELL_OPTIONS"
  }
  $dest = $fileArg.Groups[1].Value
  if ($dest -ieq '%SCRIPT%') { $dest = $scriptVar }
  if ([string]::IsNullOrWhiteSpace($dest)) { throw "EMPTY_STOP_SCRIPT_PATH" }
  if ($dest.StartsWith('%~dp0',[StringComparison]::OrdinalIgnoreCase)) {
   $dest = Join-Path $CmdDir $dest.Substring(5)
  } elseif ($dest.Contains('%')) { throw "UNRESOLVED_CMD_VARIABLE" }
  if (-not [IO.Path]::IsPathRooted($dest)) { throw "NONABSOLUTE_STOP_SCRIPT" }
  [void]$targets.Add([IO.Path]::GetFullPath($dest))
 }
 if ($targets.Count -ne 1) { throw "STOP_COMMAND_NOT_UNIQUE" }
 return $targets[0]
}

if ($SelfTest) {
 $dir = "C:\test-v10\downloads"
 $caseA = '@echo off'+[char]10+'setlocal'+[char]10+'set "SCRIPT=%~dp0STOP_AI_COCKPIT_V10.ps1"'+[char]10+'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"'+[char]10+'set "RC=%ERRORLEVEL%"'+[char]10+'if not "%RC%"=="0" pause'+[char]10+'exit /b %RC%'
 $expected = [IO.Path]::GetFullPath((Join-Path $dir 'STOP_AI_COCKPIT_V10.ps1'))
 if ((Resolve-V10StopCmdTarget $caseA $dir) -cne $expected) { throw "VALID_WRAPPER_REFUSED" }
 foreach ($unsafe in @(
  'powershell.exe -NoProfile -EncodedCommand evil -File "C:\test-v10\downloads\STOP_AI_COCKPIT_V10.ps1"',
  'powershell.exe -NoProfile -File "C:\test-v10\downloads\STOP_AI_COCKPIT_V10.ps1" & taskkill /f /im python.exe',
  'powershell.exe -NoProfile -File "%UNVERIFIED%"',
  'call stop-everything.cmd'
 )) {
  $rejected = $false
  try { $parsed = Resolve-V10StopCmdTarget $unsafe $dir } catch { $rejected = $true }
  if (-not $rejected) { throw "UNSAFE_WRAPPER_ACCEPTED" }
 }
 Write-Output "PASS: V10_DESKTOP_STOP_CMD_READONLY_PARSER"
 exit 0
}

try {
 if ($ExpectedSha -cnotmatch '^[0-9a-fA-F]{40}$' -or
     [string]::IsNullOrWhiteSpace($ExpectedBranch) -or
     [string]::IsNullOrWhiteSpace($RepoRoot) -or
     [string]::IsNullOrWhiteSpace($DesktopStopCmd)) { throw "PIN_REQUIRED" }
 $repo = [IO.Path]::GetFullPath($RepoRoot)
 $cmdPath = [IO.Path]::GetFullPath($DesktopStopCmd)
 $expected = [IO.Path]::GetFullPath((Join-Path $repo 'downloads\STOP_AI_COCKPIT_V10.ps1'))
 foreach ($p in @($repo,$cmdPath,(Split-Path -Parent $cmdPath),$expected)) {
  if (-not (Test-Path -LiteralPath $p)) { throw "PATH_MISSING" }
  $item = Get-Item -LiteralPath $p -ErrorAction Stop
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
   throw "REPARSE_PATH_NOT_APPROVED"
  }
 }
 $head = (& git -C $repo rev-parse HEAD 2>$null)
 if ($LASTEXITCODE -ne 0 -or [string]$head -cne $ExpectedSha) { throw "PIN_SHA_MISMATCH" }
 $branch = (& git -C $repo rev-parse --abbrev-ref HEAD 2>$null)
 if ($LASTEXITCODE -ne 0 -or [string]$branch -cne $ExpectedBranch) {
  throw "PIN_BRANCH_MISMATCH"
 }
 $dirty = @(& git -C $repo status --porcelain --untracked-files=no 2>$null)
 if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "TRACKED_CHECKOUT_DIRTY" }
 $body = [IO.File]::ReadAllText($cmdPath,[Text.Encoding]::UTF8)
 $actual = Resolve-V10StopCmdTarget $body (Split-Path -Parent $cmdPath)
 if (-not [string]::Equals($actual,$expected,[StringComparison]::OrdinalIgnoreCase)) {
  throw "CMD_TARGET_NOT_PINNED_STOP"
 }
 $stopText = [IO.File]::ReadAllText($expected,[Text.Encoding]::UTF8)
 foreach ($token in @('Test-ExactBrainHandle','brain_observer_pid','WaitForExit(5000)',
                      'Latest BRAIN PID/state unverified')) {
  if (-not $stopText.Contains($token)) { throw "STOP_CONTRACT_UNVERIFIED" }
 }
} catch {
 Write-Output "V10_SAFE_STOP_ROUTE=BLOCKED"
 Write-Output "REAL_SUBMIT_ALLOWED=0"
 exit 2
}
Write-Output "V10_SAFE_STOP_ROUTE=VERIFIED_READONLY"
Write-Output ("VERIFIED_SHA="+$ExpectedSha)
Write-Output "OWNER_LIVE_STOP_VERIFIED=0"
Write-Output "REAL_SUBMIT_ALLOWED=0"
exit 0
