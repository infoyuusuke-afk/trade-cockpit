"""Fail-closed STOP PID inventory: distinguish absent from inaccessible.

Windows GitHub Actions only. Extracts production STOP functions via AST;
substitutes deterministic CIM/process mocks. Never launches or kills MS2,
Excel, BRAIN, or any real OS process.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

STOP = Path(__file__).resolve().parents[1] / "downloads" / "STOP_AI_COCKPIT_V10.ps1"


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows"
    and shutil.which("powershell.exe"),
    "Windows hosted synthetic-only PowerShell tests",
)
class StopPidEvidence(unittest.TestCase):
    def test_absent_alive_unknown_and_corrupt_inventory(self):
        script = r'''
param([string]$Source)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count -gt 0){throw 'STOP_SOURCE_PARSE_FAILED'}
foreach($name in @('Get-V10TrackedPidEvidence','Test-V10RecordedPidInventory')){
    $defs=@($ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    },$true))
    if($defs.Count -ne 1){throw ('DUPLICATE_OR_MISSING_'+$name)}
    . ([scriptblock]::Create($defs[0].Extent.Text))
}
$script:Mode='absent'
$script:Seen=0
$script:RecordedTime=(Get-Date).ToUniversalTime().AddSeconds(-15)
$script:Fake=[pscustomobject]@{
    Id=4321; Handle=[IntPtr]1; HasExited=$false; StartTime=$script:RecordedTime
}
function Get-CimInstance {
    param([string]$ClassName,[string]$Filter)
    if($script:Mode -eq 'denied_cim'){throw 'ACCESS_DENIED'}
    if($script:Mode -eq 'absent'){return $null}
    $id=if($script:Mode -eq 'wrong_pid'){9999}else{4321}
    $start=$script:RecordedTime
    if($script:Mode -eq 'stale_creation'){$start=$start.AddMinutes(-10)}
    return [pscustomobject]@{ProcessId=$id;CreationDate=$start}
}
function Get-Process {
    param([int]$Id)
    if($script:Mode -eq 'denied_process'){throw 'PROCESS_ACCESS_DENIED'}
    if($script:Mode -eq 'missing_handle'){
        return [pscustomobject]@{Id=4321;Handle=[IntPtr]0;HasExited=$false;StartTime=$script:RecordedTime}
    }
    if($script:Mode -eq 'exited'){
        return [pscustomobject]@{Id=4321;Handle=[IntPtr]1;HasExited=$true;StartTime=$script:RecordedTime}
    }
    return $script:Fake
}
function Assert-Case([string]$Mode,[string]$Expected) {
    $script:Mode=$Mode
    $actual=Get-V10TrackedPidEvidence 4321
    if($actual -cne $Expected){throw ('PID_EVIDENCE_CASE_FAILED_'+$Mode+'_'+$actual)}
    $script:Seen++
}
Assert-Case 'absent' 'ABSENT'
Assert-Case 'alive' 'ALIVE'
Assert-Case 'denied_cim' 'UNKNOWN'
Assert-Case 'denied_process' 'UNKNOWN'
Assert-Case 'wrong_pid' 'UNKNOWN'
Assert-Case 'stale_creation' 'UNKNOWN'
Assert-Case 'missing_handle' 'UNKNOWN'
Assert-Case 'exited' 'UNKNOWN'
if((Get-V10TrackedPidEvidence 0) -cne 'INVALID'){throw 'PID_ZERO_MISCLASSIFIED'}
$script:Seen++
$state=[pscustomobject]@{
    controller_pid=4321;excel_pid=0;watcher_pid=0;heartbeat_pid=0;
    collector_pid=0;gateway_pid=0;brain_gateway_pid=0;voice_bridge_pid=0;
    sbv2_pid=0;shadow_supervisor_pid=0;brain_observer_pid=0
}
$script:Mode='alive'
if(-not (Test-V10RecordedPidInventory $state)){throw 'KNOWN_ALIVE_REJECTED'}
$script:Seen++
$script:Mode='absent'
if(-not (Test-V10RecordedPidInventory $state)){throw 'KNOWN_ABSENT_REJECTED'}
$script:Seen++
$script:Mode='denied_cim'
if(Test-V10RecordedPidInventory $state){throw 'DENIED_CIM_ALLOWED'}
$script:Seen++
$state.excel_pid='malformed'
$script:Mode='absent'
if(Test-V10RecordedPidInventory $state){throw 'MALFORMED_PID_ALLOWED'}
$script:Seen++
Write-Output ('V10_PID_EVIDENCE_CASES_PASS='+$script:Seen)
'''
        with tempfile.TemporaryDirectory(prefix="v10-pid-evidence-") as tmp:
            harness = Path(tmp) / "evidence.ps1"
            harness.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(harness), str(STOP)],
                capture_output=True, text=True, errors="replace", timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("V10_PID_EVIDENCE_CASES_PASS=13", result.stdout)


if __name__ == "__main__":
    unittest.main()
