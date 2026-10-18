"""D-023 AST-extracted production guards; every OS/COM boundary is mocked.

No full runtime script is executed, and no real Excel is queried or operated.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "downloads/AI_COCKPIT_CONTROLLER_V10.ps1"
STOP = ROOT / "downloads/STOP_AI_COCKPIT_V10.ps1"

HARNESS = r'''
param([string]$Controller,[string]$Stop)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
function Read-Ast([string]$Path) {
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw "PARSE_FAILED: $errors" }
    return $ast
}
$ca=Read-Ast $Controller
$sa=Read-Ast $Stop
foreach ($pair in @(@($ca,'Get-CurrentSessionId'),@($ca,'Assert-NoOtherExcelAtStartup'),
    @($sa,'Test-StopExcelPreflight'),@($sa,'Invoke-V10StopReadOnlyInspection'))) {
    $name=$pair[1]
    $fn=@($pair[0].FindAll({param($n)
        $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name
    },$true))
    if ($fn.Count -ne 1) { throw "FUNCTION_NOT_UNIQUE" }
    . ([scriptblock]::Create($fn[0].Extent.Text))
}
$script:Others=@([pscustomobject]@{Id=222;SessionId=7;ProcessName='EXCEL'})
$script:InventoryFails=$false
function Get-Process {
    param([string]$Name,[int]$Id)
    if ($PSBoundParameters.ContainsKey('Id')) {
        if ($Id -eq $PID) { return [pscustomobject]@{SessionId=7} }
        if ($Id -eq 111) { return [pscustomobject]@{Handle=[IntPtr]::Zero;HasExited=$false;ProcessName='EXCEL'} }
        return $null
    }
    if ($script:InventoryFails) { throw 'MOCK_INVENTORY_DENIED' }
    return $script:Others
}
function Get-CimInstance { throw 'FORBIDDEN_CIM' }
function Start-Process { throw 'FORBIDDEN_START' }
function Stop-Process { throw 'FORBIDDEN_STOP' }
function Add-Type { throw 'FORBIDDEN_COM_NATIVE' }
function Get-NetTCPConnection { return @() }
function Get-V10TrackedPidEvidence { return 'ALIVE' }
function Test-OwnedPidIdentity { throw 'UNEXPECTED_WORKER_IDENTITY' }
$state=[pscustomobject]@{excel_pid=111;controller_pid=0;watcher_pid=0;heartbeat_pid=0;
    collector_pid=0;gateway_pid=0;brain_gateway_pid=0;voice_bridge_pid=0;sbv2_pid=0;
    shadow_supervisor_pid=0;brain_observer_pid=0}
'''


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell mocks")
class OtherExcelMock(unittest.TestCase):
    def run_case(self, code):
        with tempfile.TemporaryDirectory(prefix="v10-d023-mock-") as tmp:
            script = Path(tmp) / "mock.ps1"
            script.write_text(HARNESS + code, encoding="utf-8-sig")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(script), str(CONTROLLER), str(STOP)],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        return result

    def test_controller_refuses_same_session_before_any_operation(self):
        r = self.run_case(r'''
try { Assert-NoOtherExcelAtStartup; throw 'UNEXPECTED_ALLOW' }
catch {
    if ($_.Exception.Message -notmatch 'START_PREFLIGHT=BLOCKED_OTHER_EXCEL_OPEN.*PID=222') { throw }
}
$script:Others=@([pscustomobject]@{Id=333;SessionId=8;ProcessName='EXCEL'})
Assert-NoOtherExcelAtStartup
$script:Others=@()
Assert-NoOtherExcelAtStartup
$script:InventoryFails=$true
try { Assert-NoOtherExcelAtStartup; throw 'UNEXPECTED_ALLOW' }
catch { if ($_.Exception.Message -ne 'MOCK_INVENTORY_DENIED') { throw } }
''')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_stop_refuses_before_teardown_with_specific_reason(self):
        r = self.run_case(r'''
$guard=@($sa.FindAll({param($n)
    $n -is [Management.Automation.Language.IfStatementAst] -and
    $n.Extent.Text.StartsWith('if (-not (Test-StopExcelPreflight $state))')
},$true))
if ($guard.Count -ne 1) { throw 'GUARD_NOT_UNIQUE' }
. ([scriptblock]::Create($guard[0].Extent.Text))
throw 'TEARDOWN_REACHED'
''')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("SAFE_STOP_PREFLIGHT=BLOCKED_OTHER_EXCEL_OPEN", r.stdout)
        self.assertIn("PID=222", r.stdout)
        self.assertIn("ほかのExcelを閉じてから、もう一度STOPしてください", r.stdout)

    def test_inspection_reports_other_excel_without_mislabel_or_mutation(self):
        r = self.run_case(r'''
$before=$state | ConvertTo-Json -Compress
$result=Invoke-V10StopReadOnlyInspection $state
if ($result -ne 2) { throw 'INSPECTION_NOT_BLOCKED' }
if (($state | ConvertTo-Json -Compress) -ne $before) { throw 'STATE_MUTATED' }
''')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PID_excel_pid=ALIVE_BLOCKED_OTHER_EXCEL_OPEN", r.stdout)
        self.assertNotIn("ALIVE_FOREIGN_OR_UNVERIFIED", r.stdout)

    def test_reason_resets_and_absent_owned_excel_still_blocks(self):
        r = self.run_case(r'''
foreach ($value in @(111,0,999)) {
    $state.excel_pid=$value
    if (Test-StopExcelPreflight $state) { throw 'OTHER_EXCEL_ALLOWED' }
    if ($script:StopExcelPreflightReason -ne 'BLOCKED_OTHER_EXCEL_OPEN') { throw 'REASON_LOST' }
}
$script:Others=@()
$state.excel_pid=111
if (Test-StopExcelPreflight $state) { throw 'INVALID_IDENTITY_ALLOWED' }
if ($script:StopExcelPreflightReason -ne 'BLOCKED_EXCEL_IDENTITY_OR_WORKBOOKS') { throw 'STALE_REASON' }
$state.excel_pid=0
if (-not (Test-StopExcelPreflight $state)) { throw 'EMPTY_INVENTORY_BLOCKED' }
$script:InventoryFails=$true
if (Test-StopExcelPreflight $state) { throw 'UNKNOWN_INVENTORY_ALLOWED' }
''')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class OtherExcelOrdering(unittest.TestCase):
    def test_guard_precedes_workers_and_rechecks_before_excel_launch(self):
        s = CONTROLLER.read_text(encoding="utf-8-sig")
        guard = s.index("    Assert-NoOtherExcelAtStartup\n")
        self.assertLess(guard, s.index('Write-Status "Starting unified voice backend'))
        self.assertIn("Assert-NoOtherExcelAtStartup\n    $excelStart.FileName", s)
        self.assertNotIn("Foreign Excel may stay open", s)

    def test_stop_guard_precedes_controller_and_worker_teardown(self):
        s = STOP.read_text(encoding="utf-8-sig")
        guard = s.index("if (-not (Test-StopExcelPreflight $state))")
        self.assertLess(guard, s.index("$controllerProc.Kill()"))
        self.assertLess(guard, s.index("Stop-OwnedJobBridge 28580"))


if __name__ == "__main__":
    unittest.main()
