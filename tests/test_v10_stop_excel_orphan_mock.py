"""Isolated PowerShell mocks for V10 STOP hidden Excel orphan ownership.

Extract only the identity function from its AST. No real Excel/process launches
or terminations; Windows GitHub Actions is the sole execution environment.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

STOP = Path(__file__).resolve().parents[1] / "downloads" / "STOP_AI_COCKPIT_V10.ps1"
CONTROLLER = STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1"


@unittest.skipUnless(
    os.name == "nt"
    and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows"
    and shutil.which("powershell.exe"),
    "Windows GitHub Actions only: isolated PowerShell ownership mocks",
)
class HiddenExcelOrphanMock(unittest.TestCase):
    def test_real_powershell_function_verifies_full_identity_before_kill(self):
        script = r'''
param([string]$Source)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count -gt 0) { throw "STOP_PARSE_FAILED" }
$definitions = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Stop-VerifiedHiddenManagedExcelOrphan"
},$true))
if ($definitions.Count -ne 1) { throw "ORPHAN_FUNCTION_NOT_UNIQUE" }
. ([scriptblock]::Create($definitions[0].Extent.Text))

$script:SessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
$script:CimStart = (Get-Date).AddSeconds(-5)
$script:ExpectedParent = 4321
$script:ProcessPid = 12345
$script:Workbook = 'C:\synthetic\canonical.xlsx'
$script:Cmd = 'C:\synthetic\EXCEL.EXE /x "C:\synthetic\canonical.xlsx"'
$script:ExtraExcel = $false
$script:Fake = [pscustomobject]@{
    Id = $script:ProcessPid
    Handle = [IntPtr]1
    HasExited = $false
    ProcessName = "EXCEL"
    SessionId = $script:SessionId
    MainWindowHandle = [IntPtr]::Zero
    StartTime = $script:CimStart
    KillCalled = $false
}
$script:Fake | Add-Member -MemberType ScriptMethod -Name Kill -Value {
    $this.KillCalled = $true
    $this.HasExited = $true
}
$script:Fake | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
    param([int]$milliseconds)
    return [bool]$this.HasExited
}

function Get-Process {
    param([string]$Name,[int]$Id)
    if ($PSBoundParameters.ContainsKey("Id")) {
        if ($Id -eq $script:ProcessPid) { return $script:Fake }
        if ($Id -eq $PID) { return [pscustomobject]@{SessionId=$script:SessionId} }
        return $null
    }
    if ($Name -ieq "EXCEL") {
        if ($script:ExtraExcel) {
            return @($script:Fake, [pscustomobject]@{Id=23456;SessionId=$script:SessionId})
        }
        return $script:Fake
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName,[string]$Filter)
    return [pscustomobject]@{
        ProcessId = $script:ProcessPid
        Name = "EXCEL.EXE"
        ParentProcessId = $script:ExpectedParent
        CreationDate = $script:CimStart
        CommandLine = $script:Cmd
    }
}
# Substitute the COM/ROT side-effect-free evidence check. False simulates
# either a foreign workbook inside this SAME Excel PID or inaccessible ROT.
$script:RotExclusive = $true
function Test-NoExcelWorkbooksForPid {
    param([int]$ExcelPid)
    return ($ExcelPid -eq $script:ProcessPid -and [bool]$script:RotExclusive)
}
$script:Checks = 0
function Invoke-Case([bool]$ShouldSucceed,[int]$Parent,[datetime]$Started) {
    $script:Fake.HasExited = $false
    $script:Fake.KillCalled = $false
    $actual = Stop-VerifiedHiddenManagedExcelOrphan $script:ProcessPid $script:Workbook $Started $Parent
    if ([bool]$actual -ne $ShouldSucceed) {
        throw ("ORPHAN_RETURN_MISMATCH_" + $script:Checks)
    }
    if ([bool]$script:Fake.KillCalled -ne $ShouldSucceed) {
        throw ("ORPHAN_FOREIGN_KILL_" + $script:Checks)
    }
    $script:Checks++
}

$oldSession = (Get-Date).ToUniversalTime().AddMinutes(-2)
Invoke-Case $false 9876 $oldSession                    # wrong Controller parent
Invoke-Case $false 4321 ((Get-Date).AddMinutes(5))    # recorded session newer than Excel
$script:CimStart = (Get-Date).AddMinutes(-8)
Invoke-Case $false 4321 $oldSession                   # CIM creation differs from handle
$script:CimStart = $script:Fake.StartTime
$script:ExtraExcel = $true
Invoke-Case $false 4321 $oldSession                   # unrelated Excel still exists
$script:ExtraExcel = $false
$script:Cmd = 'C:\synthetic\EXCEL.EXE /x "C:\foreign\other.xlsx"'
Invoke-Case $false 4321 $oldSession                   # wrong canonical workbook
$script:Cmd = 'C:\synthetic\EXCEL.EXE /x "C:\synthetic\canonical.xlsx"'
$script:RotExclusive = $false
Invoke-Case $false 4321 $oldSession                   # foreign workbook in SAME PID / ROT UNKNOWN
$script:RotExclusive = $true
Invoke-Case $true 4321 $oldSession                    # exact synthetic ownership only
Write-Output ("EXCEL_ORPHAN_MOCK_CASES_PASS=" + $script:Checks)
'''
        with tempfile.TemporaryDirectory(prefix="v10-excel-orphan-mock-") as tmp:
            harness = Path(tmp) / "harness.ps1"
            harness.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(harness), str(STOP)],
                capture_output=True, text=True, errors="replace", timeout=45,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("EXCEL_ORPHAN_MOCK_CASES_PASS=7", result.stdout)


    def test_canonical_workbook_exclusivity_pure_powershell(self):
        # Extract ONLY the pure workbook guard: no ROT/Excel invocation.
        script = r'''
param([string]$Source)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'PARSE_FAILED'}
$fn=@($ast.FindAll({
    param($n)
    $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -eq 'Test-OnlyCanonicalExcelWorkbookOpen'
},$true))
if($fn.Count -ne 1){throw 'FUNCTION_NOT_UNIQUE'}
. ([scriptblock]::Create($fn[0].Extent.Text))
$target='C:\synthetic\canonical.xlsx'
$canonical=[pscustomobject]@{FullName=$target}
$foreign=[pscustomobject]@{FullName='C:\company\unsaved-budget.xlsx'}
$cases=@(
    @([pscustomobject]@{Workbooks=@($canonical)},$true),
    @([pscustomobject]@{Workbooks=@($canonical,$foreign)},$false),
    @([pscustomobject]@{Workbooks=@($foreign)},$false),
    @([pscustomobject]@{Workbooks=@()},$false),
    @([pscustomobject]@{Workbooks=@([pscustomobject]@{FullName=''})},$false)
)
$count=0
foreach($case in $cases){
    $actual=Test-OnlyCanonicalExcelWorkbookOpen $case[0] $target
    if([bool]$actual -ne [bool]$case[1]){throw ('EXCLUSIVE_BOOK_CASE_FAILED_'+$count)}
    $count++
}
Write-Output ('EXCLUSIVE_WORKBOOK_CASES_PASS='+$count)
'''
        with tempfile.TemporaryDirectory(prefix="v10-excel-workbooks-pure-") as tmp:
            harness = Path(tmp) / "harness.ps1"
            harness.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(harness), str(STOP)],
                capture_output=True, text=True, errors="replace", timeout=45,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("EXCLUSIVE_WORKBOOK_CASES_PASS=5", result.stdout)


    def test_controller_excel_stop_requires_exclusivity_before_each_kill(self):
        # No real Excel or Windows process is created. AST-extract only the
        # production Controller's Excel stop function and substitute mocks.
        script = r'''
param([string]$Source)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'CONTROLLER_PARSE_FAILED'}
$fn=@($ast.FindAll({
    param($n)
    $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -eq 'Stop-VerifiedOwnedExcel'
},$true))
if($fn.Count -ne 1){throw 'CONTROLLER_EXCEL_STOP_NOT_UNIQUE'}
. ([scriptblock]::Create($fn[0].Extent.Text))
$script:ProcessPid=12345
$script:Parent=4321
$script:Workbook='C:\synthetic\canonical.xlsx'
$script:RecordedStart=(Get-Date).AddSeconds(-5)
$script:CimStart=$script:RecordedStart
$script:OtherExcel=$false
$script:Ownership=$true
$script:Checks=0
$script:GateIndex=0
$script:Gate=@()
$script:Fake=[pscustomobject]@{
    Id=$script:ProcessPid
    Handle=[IntPtr]1
    HasExited=$false
    ProcessName='EXCEL'
    StartTime=$script:RecordedStart
    KillCalled=$false
}
$script:Fake | Add-Member -MemberType ScriptMethod -Name Kill -Value {
    $this.KillCalled=$true
    $this.HasExited=$true
}
$script:Fake | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
    param([int]$milliseconds)
    return [bool]$this.HasExited
}
function Get-Process {
    param([int]$Id)
    if($Id -eq $script:ProcessPid){return $script:Fake}
    return $null
}
function Get-CimInstance {
    param([string]$ClassName,[string]$Filter)
    return [pscustomobject]@{ProcessId=$script:ProcessPid;CreationDate=$script:CimStart}
}
function Test-LaunchedExcelOwnership {
    param([int]$ExcelPid,[string]$WorkbookPath,[int]$ControllerPid)
    return $script:Ownership
}
function Test-OtherExcelInSession {
    param([int]$ExceptPid)
    return $script:OtherExcel
}
function Test-ManagedExcelWorkbooksExclusive {
    param([int]$ExcelPid,[string]$WorkbookPath)
    if($script:GateIndex -ge $script:Gate.Count){throw 'UNEXPECTED_EXCLUSIVITY_GATE'}
    $result=[bool]$script:Gate[$script:GateIndex]
    $script:GateIndex++
    return $result
}
function Invoke-Case([bool[]]$Sequence,[bool]$Expected) {
    $script:Fake.KillCalled=$false
    $script:Fake.HasExited=$false
    $script:Gate=@($Sequence)
    $script:GateIndex=0
    $actual=Stop-VerifiedOwnedExcel $script:ProcessPid $script:Workbook $script:Parent
    if([bool]$actual -ne $Expected){throw ('CONTROLLER_RESULT_MISMATCH_'+$script:Checks)}
    if([bool]$script:Fake.KillCalled -ne $Expected){throw ('CONTROLLER_FOREIGN_KILL_'+$script:Checks)}
    $script:Checks++
}
Invoke-Case @($false) $false
Invoke-Case @($true,$false) $false
Invoke-Case @($true,$true) $true
$script:CimStart=(Get-Date).AddMinutes(-10)
Invoke-Case @($true,$true) $false
$script:CimStart=$script:RecordedStart
$script:OtherExcel=$true
Invoke-Case @($true,$true) $false
$script:OtherExcel=$false
$script:Ownership=$false
Invoke-Case @($true,$true) $false
Write-Output ('CONTROLLER_EXCEL_GATE_CASES_PASS='+$script:Checks)
'''
        with tempfile.TemporaryDirectory(prefix="v10-controller-excel-guard-") as tmp:
            harness = Path(tmp) / "guard.ps1"
            harness.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(harness), str(CONTROLLER)],
                capture_output=True, text=True, errors="replace", timeout=45,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CONTROLLER_EXCEL_GATE_CASES_PASS=6", result.stdout)


if __name__ == "__main__":
    unittest.main()
