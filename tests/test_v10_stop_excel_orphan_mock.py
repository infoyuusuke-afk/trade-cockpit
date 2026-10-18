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
        self.assertIn("EXCEL_ORPHAN_MOCK_CASES_PASS=6", result.stdout)


if __name__ == "__main__":
    unittest.main()
