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
 [switch]$VerifyShortcuts,
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
 $stopName = ('A' + 'I' + ([char]0x30B3) + ([char]0x30AF) + ([char]0x30D4) + ([char]0x30C3) + ([char]0x30C8) + '_' + ([char]0x5B89) + ([char]0x5168) + ([char]0x505C) + ([char]0x6B62) + '.' + 'c' + 'm' + 'd')
 $stopCandidates = @(Get-ChildItem -LiteralPath $Desktop -File -ErrorAction Stop |
     Where-Object { $_.Name -ceq $stopName })
 $startName = ('A' + 'I' + ([char]0x30B3) + ([char]0x30AF) + ([char]0x30D4) + ([char]0x30C3) + ([char]0x30C8) + '_' + ([char]0x8D77) + ([char]0x52D5) + '.' + 'c' + 'm' + 'd')
 $startCandidates = @(Get-ChildItem -LiteralPath $Desktop -File -ErrorAction Stop |
     Where-Object { $_.Name -ceq $startName })
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


# WScript.Shell.CreateShortcut opens a local .lnk without executing it. Never call Save().
# Strict acceptance: one recognized START and one recognized STOP shortcut, each
# pointing DIRECTLY to the pinned tracked V10 .cmd; wrappers are parsed, not run.
function Test-V10TrackedCmd([string]$Repo,[string]$Role) {
 try {
  $name = if ($Role -eq "START") { "START_AI_COCKPIT_V10" } else { "STOP_AI_COCKPIT_V10" }
  $cmdPath = Join-Path $Repo ("downloads\" + $name + ".cmd")
  $info = Get-Item -LiteralPath $cmdPath -ErrorAction Stop
  if (($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $info.Length -gt 2048) {
   return $false
  }
  $actual = [IO.File]::ReadAllText($cmdPath,[Text.Encoding]::UTF8).TrimStart([char]0xFEFF)
  $actual = $actual.Replace(([string][char]13 + [string][char]10),[string][char]10).Trim()
  $expected = @(
   '@echo off',
   'setlocal',
   ('set "SCRIPT=%~dp0' + $name.Replace('_V10','_V10') + '.ps1"'),
   'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"',
   'set "RC=%ERRORLEVEL%"',
   'if not "%RC%"=="0" pause',
   'exit /b %RC%'
  )
  # START's script is RUN_AI_COCKPIT_V10.ps1, not START_AI_COCKPIT_V10.ps1.
  if ($Role -eq "START") { $expected[2] = 'set "SCRIPT=%~dp0RUN_AI_COCKPIT_V10.ps1"' }
  return [string]::Equals($actual,[string]::Join([string][char]10,$expected),
                         [StringComparison]::Ordinal)
 } catch { return $false }
}

function Get-V10ShortcutInventory([string]$Desktop,[string]$Repo) {
 $result = [ordered]@{ Start = "MISSING"; Stop = "MISSING"; Other = "NONE" }
 try {
  $items = @(Get-ChildItem -LiteralPath $Desktop -File -Filter "*.lnk" -ErrorAction Stop)
  $jaPrefix = 'AI' + ([char]0x30B3) + ([char]0x30AF) + ([char]0x30D4) +
              ([char]0x30C3) + ([char]0x30C8)
  $jaStart = ([char]0x8D77) + ([string][char]0x52D5)
  $jaStop = ([char]0x5B89) + ([string][char]0x5168) + ([string][char]0x505C) +
            ([string][char]0x6B62)
  $counts = @{ START = 0; STOP = 0 }
  $ws = $null
  foreach ($file in $items) {
   $label = [IO.Path]::GetFileNameWithoutExtension($file.Name)
   if (-not ($label.StartsWith($jaPrefix,[StringComparison]::OrdinalIgnoreCase) -or
             $label.StartsWith("AI Cockpit",[StringComparison]::OrdinalIgnoreCase))) {
    continue
   }
   $isStart = ($label.IndexOf($jaStart,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or
               $label -match '(?i)\bSTART\b')
   $isStop = ($label.IndexOf($jaStop,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or
              $label -match '(?i)\bSTOP\b')
   if ($isStart -eq $isStop) { $result.Other = "UNKNOWN_AI_SHORTCUT"; continue }
   $role = if ($isStart) { "START" } else { "STOP" }
   $counts[$role] += 1
   $class = "BLOCKED"
   $shortcut = $null
   try {
    if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $file.Length -le 0 -or $file.Length -gt 65536 -or
        -not (Test-V10TrackedCmd $Repo $role)) { throw "BAD_SHORTCUT_OR_WRAPPER" }
    if ($null -eq $ws) { $ws = New-Object -ComObject WScript.Shell -ErrorAction Stop }
    $shortcut = $ws.CreateShortcut($file.FullName)
    $target = [string]$shortcut.TargetPath
    $arguments = [string]$shortcut.Arguments
    $workdir = [string]$shortcut.WorkingDirectory
    $cmd = if ($role -eq "START") { "START_AI_COCKPIT_V10.cmd" } else { "STOP_AI_COCKPIT_V10.cmd" }
    $expected = [IO.Path]::GetFullPath((Join-Path $Repo ("downloads\" + $cmd)))
    if (-not [IO.Path]::IsPathRooted($target) -or $target.StartsWith('\\') -or
        $target.Contains('%') -or -not [string]::IsNullOrWhiteSpace($arguments) -or
        -not [string]::Equals([IO.Path]::GetFullPath($target),$expected,
                             [StringComparison]::OrdinalIgnoreCase)) { throw "TARGET_NOT_PINNED" }
    if ($workdir -and -not [string]::Equals([IO.Path]::GetFullPath($workdir),
                       [IO.Path]::GetFullPath((Join-Path $Repo "downloads")),
                       [StringComparison]::OrdinalIgnoreCase)) { throw "WORKDIR_UNTRUSTED" }
    $class = "EXPECTED"
   } catch { $class = "BLOCKED" }
   finally {
    if ($null -ne $shortcut) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut) } catch {} }
   }
   $result[$role.Substring(0,1) + $role.Substring(1).ToLowerInvariant()] = $class
  }
  if ($counts.START -gt 1) { $result.Start = "AMBIGUOUS" }
  if ($counts.STOP -gt 1) { $result.Stop = "AMBIGUOUS" }
  if ($null -ne $ws) { try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ws) } catch {} }
 } catch { $result.Other = "BLOCKED" }
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
$shortcutStart = "NOT_CHECKED"
$shortcutStop = "NOT_CHECKED"
$shortcutOther = "NOT_CHECKED"
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
 if ($VerifyShortcuts) {
  $shortcuts = Get-V10ShortcutInventory $desktop $root
  $shortcutStart = $shortcuts.Start
  $shortcutStop = $shortcuts.Stop
  $shortcutOther = $shortcuts.Other
 }
} catch {
 # Deliberately do not print absolute Windows paths, CMD text, JSON, or secrets.
}
Write-Output ("V10_PIN="+$pin)
Write-Output ("V10_STOP_SOURCE="+$source)
Write-Output ("V10_START_SOURCE="+$startSource)
Write-Output ("DESKTOP_STOP_ROUTE="+$desktopStop)
Write-Output ("DESKTOP_START_ROUTE="+$desktopStart)
Write-Output ("SHORTCUT_START_ROUTE="+$shortcutStart)
Write-Output ("SHORTCUT_STOP_ROUTE="+$shortcutStop)
Write-Output ("SHORTCUT_OTHER="+$shortcutOther)
Write-Output "OWNER_LIVE_RUNTIME_VERIFIED=0"
Write-Output "REAL_SUBMIT_ALLOWED=0"
if ($pin -eq "VERIFIED" -and $source -eq "PRESENT" -and $startSource -eq "PRESENT" -and $desktopStop -eq "EXPECTED" -and $desktopStart -eq "EXPECTED" -and
    (-not $VerifyShortcuts -or ($shortcutStart -eq "EXPECTED" -and $shortcutStop -eq "EXPECTED" -and $shortcutOther -eq "NONE"))) {
 if ($VerifyShortcuts) { Write-Output "V10_OWNER_DESKTOP_INVENTORY=ROUTES_AND_SHORTCUTS_READONLY_VERIFIED" }
 else { Write-Output "V10_OWNER_DESKTOP_INVENTORY=ROUTES_READONLY_VERIFIED" }
 exit 0
}
Write-Output "V10_OWNER_DESKTOP_INVENTORY=BLOCKED"
exit 2
