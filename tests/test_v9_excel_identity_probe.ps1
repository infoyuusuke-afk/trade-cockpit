$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

function Import-Function([string]$RelativePath, [string]$Name) {
    $errors = $null
    $tokens = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $repo $RelativePath), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    $function = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $Name }, $true)
    if ($null -eq $function) { throw "Function missing: $Name" }
    return $function.Extent.Text
}

foreach ($name in @(
    'Get-ExcelIdentityProbeVerdict',
    'Resolve-ExcelIdentityFailureCode',
    'Stop-VerifiedOwnedExcel',
    'Invoke-TerminateIdentityProbeProcess',
    'Wait-BoundedHelperProcess'
)) {
    . ([scriptblock]::Create((Import-Function 'downloads/AI_COCKPIT_CONTROLLER_V9.ps1' $name)))
}

function Assert-Equal($Actual, $Expected, [string]$Label) {
    if ($Actual -ne $Expected) { throw "$Label : expected '$Expected' but got '$Actual'" }
}
function Assert-True($Value, [string]$Label) {
    if (-not $Value) { throw "$Label was false" }
}
function Assert-False($Value, [string]$Label) {
    if ($Value) { throw "$Label was true" }
}

$book = 'C:\rss\Kioxia_MS2_RSS_Live_Signals.xlsx'
$pidExpected = 99
$sessionExpected = 7

$missing = Get-ExcelIdentityProbeVerdict $null $book $pidExpected $sessionExpected
Assert-False $missing.ok 'null result ok'
Assert-False $missing.definitive_mismatch 'null result definitive'
Assert-Equal $missing.error 'NO_RESULT' 'null result error'

$starting = Get-ExcelIdentityProbeVerdict ([pscustomobject]@{
    full_name = $book; app_hwnd = 0; owner_pid = 0; session_id = -1; error = 'Workbook moniker not ready.'
}) $book $pidExpected $sessionExpected
Assert-True $starting.moniker 'starting moniker'
Assert-False $starting.hwnd 'starting hwnd'
Assert-False $starting.definitive_mismatch 'starting stays retryable'

$wrongBook = Get-ExcelIdentityProbeVerdict ([pscustomobject]@{
    full_name = 'C:\work\taxes.xlsx'; app_hwnd = 42; owner_pid = 99; session_id = 7; error = ''
}) $book $pidExpected $sessionExpected
Assert-False $wrongBook.moniker 'wrong book moniker'
Assert-True $wrongBook.definitive_mismatch 'wrong book is definitive'

$wrongPid = Get-ExcelIdentityProbeVerdict ([pscustomobject]@{
    full_name = $book; app_hwnd = 42; owner_pid = 100; session_id = 7; error = ''
}) $book $pidExpected $sessionExpected
Assert-True $wrongPid.moniker 'wrong pid moniker'
Assert-True $wrongPid.hwnd 'wrong pid hwnd'
Assert-False $wrongPid.pid 'wrong pid flag'
Assert-True $wrongPid.definitive_mismatch 'wrong pid is definitive'

$wrongSession = Get-ExcelIdentityProbeVerdict ([pscustomobject]@{
    full_name = $book; app_hwnd = 42; owner_pid = 99; session_id = 3; error = ''
}) $book $pidExpected $sessionExpected
Assert-True $wrongSession.pid 'wrong session still has pid'
Assert-False $wrongSession.session 'wrong session flag'
Assert-True $wrongSession.definitive_mismatch 'wrong session is definitive'
Assert-False $wrongSession.ok 'wrong session is not verified'

$verified = Get-ExcelIdentityProbeVerdict ([pscustomobject]@{
    full_name = 'c:\rss\kioxia_ms2_rss_live_signals.xlsx'; app_hwnd = 77; owner_pid = 99; session_id = 7; error = ''
}) $book $pidExpected $sessionExpected
Assert-True $verified.ok 'canonical path, hwnd, pid, and session verify'
Assert-False $verified.definitive_mismatch 'verified result is not a mismatch'

Assert-Equal (Resolve-ExcelIdentityFailureCode $true) 'EXCEL_IDENTITY_PROBE_FAILED' 'mismatch code'
Assert-Equal (Resolve-ExcelIdentityFailureCode $false) 'EXCEL_IDENTITY_PROBE_TIMEOUT' 'timeout code'
Write-Output 'PASS: identity verdict requires canonical path, HWND, PID, and session; timeout code is EXCEL_IDENTITY_PROBE_TIMEOUT'

function Get-CurrentSessionId { return 7 }
$script:stopped = @()
$script:cimByPid = @{}
function Get-Process {
    param($Id, $Name, $ErrorAction)
    $idValue = [int]$Id
    if ($script:stopped -contains $idValue) { return $null }
    if ($script:visiblePids -contains $idValue) {
        return @{ Id = $idValue; SessionId = $script:sessionByPid[$idValue] }
    }
    return $null
}
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    foreach ($key in @($script:cimByPid.Keys)) {
        if ($Filter -like ("*" + $key + "*")) { return $script:cimByPid[$key] }
    }
    return $null
}
function Stop-Process {
    param($Id, [switch]$Force, $ErrorAction)
    $script:stopped += [int]$Id
}

function Reset-OwnedExcelMock {
    $script:stopped = @()
    $script:visiblePids = @(99, 100)
    $script:sessionByPid = @{ 99 = 7; 100 = 7 }
    $script:cimByPid = @{
        99 = @{ CommandLine = 'EXCEL.EXE /x "C:\rss\Kioxia_MS2_RSS_Live_Signals.xlsx"'; ParentProcessId = 42 }
        100 = @{ CommandLine = 'EXCEL.EXE "C:\work\taxes.xlsx"'; ParentProcessId = 555 }
    }
}

Reset-OwnedExcelMock
Assert-True (Stop-VerifiedOwnedExcel 0 $book 42) 'zero pid is a no-op'
Assert-Equal ($script:stopped -join ',') '' 'zero pid stopped nothing'

Reset-OwnedExcelMock
$script:visiblePids = @(100)
Assert-True (Stop-VerifiedOwnedExcel 99 $book 42) 'already exited pid needs no kill'
Assert-Equal ($script:stopped -join ',') '' 'missing pid stopped nothing'

Reset-OwnedExcelMock
Assert-False (Stop-VerifiedOwnedExcel 100 $book 42) 'foreign workbook must not be stopped'
Assert-Equal ($script:stopped -join ',') '' 'foreign pid 100 was not stopped'

Reset-OwnedExcelMock
$script:cimByPid[99] = @{ CommandLine = 'EXCEL.EXE /x "C:\work\taxes.xlsx"'; ParentProcessId = 42 }
Assert-False (Stop-VerifiedOwnedExcel 99 $book 42) 'wrong command line blocks stop'
Assert-Equal ($script:stopped -join ',') '' 'wrong workbook pid was not stopped'

Reset-OwnedExcelMock
$script:cimByPid[99] = @{ CommandLine = 'EXCEL.EXE /x "C:\rss\Kioxia_MS2_RSS_Live_Signals.xlsx"'; ParentProcessId = 555 }
Assert-False (Stop-VerifiedOwnedExcel 99 $book 42) 'wrong parent blocks stop'
Assert-Equal ($script:stopped -join ',') '' 'unrelated parent was not stopped'

Reset-OwnedExcelMock
$script:sessionByPid[99] = 3
Assert-False (Stop-VerifiedOwnedExcel 99 $book 42) 'wrong session blocks stop'
Assert-Equal ($script:stopped -join ',') '' 'other session was not stopped'

Reset-OwnedExcelMock
$script:cimByPid[99] = $null
Assert-False (Stop-VerifiedOwnedExcel 99 $book 42) 'missing process command line blocks stop'
Assert-Equal ($script:stopped -join ',') '' 'unproven process was not stopped'

Reset-OwnedExcelMock
Assert-True (Stop-VerifiedOwnedExcel 99 $book 42) 'owned canonical excel stops'
Assert-Equal ($script:stopped -join ',') '99' 'only the proven launched pid was stopped'
Assert-False ($script:stopped -contains 100) 'foreign excel pid stayed untouched'
Write-Output 'PASS: Stop-VerifiedOwnedExcel stops only canonical workbook + controller child + same session'

function New-ProbeProcess([string]$FileName, [string]$Arguments) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FileName
    $psi.Arguments = $Arguments
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    return [System.Diagnostics.Process]::Start($psi)
}

$onWindows = ($env:OS -eq 'Windows_NT')
if ($onWindows) {
    $slow = New-ProbeProcess 'powershell.exe' '-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 30"'
    $fast = New-ProbeProcess 'powershell.exe' '-NoProfile -NonInteractive -Command "exit 0"'
} else {
    $slow = New-ProbeProcess '/bin/sleep' '30'
    $fast = New-ProbeProcess '/bin/true' ''
}

try {
    $fastClock = [Diagnostics.Stopwatch]::StartNew()
    $fastExited = Wait-BoundedHelperProcess $fast ([IntPtr]::Zero) 2000 1000
    $fastMs = $fastClock.ElapsedMilliseconds
    Assert-True $fastExited 'fast process should finish inside the timeout'
    Assert-True ($fastMs -lt 2000) "fast process took ${fastMs}ms"

    $slowClock = [Diagnostics.Stopwatch]::StartNew()
    $slowExited = Wait-BoundedHelperProcess $slow ([IntPtr]::Zero) 700 1500
    $slowMs = $slowClock.ElapsedMilliseconds
    Assert-False $slowExited 'hung helper must hit the external timeout'
    Assert-True ($slowMs -lt 4000) "bounded kill took ${slowMs}ms, expected under 4000"
    Assert-True $slow.HasExited 'timed-out helper must be terminated'
    Write-Output ("PASS: external timeout returned in {0}ms and the helper was terminated" -f $slowMs)
} finally {
    foreach ($proc in @($slow, $fast)) {
        try {
            if ($null -ne $proc -and -not $proc.HasExited) { $proc.Kill() }
        } catch {}
    }
}
