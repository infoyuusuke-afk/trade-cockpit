"""Windows-only, process-safe mock of Controller workbook-close final acceptance.

AST-extracts production PowerShell functions, mocks CIM and TCP inventories,
and uses a temporary JSON state. Does not start/stop Excel, MS2 or workers.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parents[1] / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"


@unittest.skipUnless(
    os.name == "nt"
    and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows"
    and shutil.which("powershell.exe"),
    "Disposable Windows GitHub Actions only",
)
class WorkbookCloseTeardownMock(unittest.TestCase):
    def test_no_false_success_and_no_state_loss(self):
        harness_script = r'''
param([string]$Source,[string]$StateFileArg)
$ErrorActionPreference='Stop'
$script:StateFile=$StateFileArg
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count -gt 0){throw 'CONTROLLER_PARSE_FAILED'}
foreach($name in @("Test-V10WorkbookCloseTeardownComplete","Remove-V10VerifiedShutdownState")){
    $found=@($ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $name
    },$true))
    if($found.Count -ne 1){throw ("MISSING_OR_DUPLICATE_"+$name)}
    . ([scriptblock]::Create($found[0].Extent.Text))
}
$script:WorkerAlive=$false
$script:PortAlive=$false
$script:CimUnavailable=$false
$script:PortsUnavailable=$false
function Get-CimInstance {
    param([string]$ClassName,[string]$Filter)
    if($script:CimUnavailable){throw 'CIM_ACCESS_DENIED'}
    if($script:WorkerAlive){return [pscustomobject]@{ProcessId=4321}}
    return $null
}
function Get-NetTCPConnection {
    param([string]$State)
    if($script:PortsUnavailable){throw 'PORT_AUDIT_DENIED'}
    if($script:PortAlive){return [pscustomobject]@{LocalPort=28582}}
    return @()
}
$script:State=[pscustomobject]@{
    controller_pid=$PID
    excel_pid=99999
    started_at='2026-10-18T09:00:00.0000000+09:00'
    session_id='synthetic-only'
    watcher_pid=4321
    heartbeat_pid=0
    collector_pid=0
    gateway_pid=0
    brain_gateway_pid=0
    voice_bridge_pid=0
    sbv2_pid=0
    shadow_supervisor_pid=0
    brain_observer_pid=0
}
$script:Checks=0
function Assert-Teardown([bool]$Expected) {
    $actual=Test-V10WorkbookCloseTeardownComplete $script:State
    if([bool]$actual -ne $Expected){throw ("TEARDOWN_RESULT_MISMATCH_"+$script:Checks)}
    $script:Checks++
}
function Write-SyntheticState {
    [IO.File]::WriteAllText($script:StateFile,
        ($script:State | ConvertTo-Json -Depth 5),
        [Text.UTF8Encoding]::new($false))
}
function Assert-RetainsState {
    Write-SyntheticState
    if(Remove-V10VerifiedShutdownState $script:State){
        throw ("UNSAFE_STATE_DELETED_"+$script:Checks)
    }
    if(-not (Test-Path -LiteralPath $script:StateFile)){
        throw ("STATE_NOT_RETAINED_"+$script:Checks)
    }
    $script:Checks++
}
# Clean, worker living, bound loopback service, absent inventories,
# invalid PID and controller identity mismatch.
Assert-Teardown $true
$script:WorkerAlive=$true; Assert-Teardown $false
$script:WorkerAlive=$false; $script:PortAlive=$true; Assert-Teardown $false
$script:PortAlive=$false; $script:CimUnavailable=$true; Assert-Teardown $false
$script:CimUnavailable=$false; $script:PortsUnavailable=$true; Assert-Teardown $false
$script:PortsUnavailable=$false
$script:State.watcher_pid='bogus'; Assert-Teardown $false
$script:State.watcher_pid=4321
$script:State.controller_pid=12345; Assert-Teardown $false
$script:State.controller_pid=$PID

# Do not delete when a worker survives, or when a port still listens.
$script:WorkerAlive=$true; Assert-RetainsState
$script:WorkerAlive=$false
$script:PortAlive=$true; Assert-RetainsState
$script:PortAlive=$false

# The JSON on disk must still exactly identify the current Controller.
Write-SyntheticState
$disk=Get-Content -LiteralPath $script:StateFile -Raw | ConvertFrom-Json
$disk.started_at='2026-10-18T09:01:00.0000000+09:00'
[IO.File]::WriteAllText($script:StateFile,($disk | ConvertTo-Json -Depth 5))
if(Remove-V10VerifiedShutdownState $script:State){throw 'DIFFERENT_SESSION_STATE_REMOVED'}
if(-not (Test-Path -LiteralPath $script:StateFile)){throw 'DIFFERENT_SESSION_STATE_LOST'}
$script:Checks++

[IO.File]::WriteAllText($script:StateFile,'{not-json')
if(Remove-V10VerifiedShutdownState $script:State){throw 'CORRUPT_STATE_REMOVED'}
if(-not (Test-Path -LiteralPath $script:StateFile)){throw 'CORRUPT_STATE_LOST'}
$script:Checks++

Write-SyntheticState
if(-not (Remove-V10VerifiedShutdownState $script:State)){
    throw 'CLEAN_STATE_NOT_REMOVED'
}
if(Test-Path -LiteralPath $script:StateFile){throw 'CLEAN_STATE_STILL_EXISTS'}
$script:Checks++
Write-Output ("V10_WORKBOOK_TEARDOWN_CASES_PASS="+$script:Checks)
'''
        with tempfile.TemporaryDirectory(prefix="v10-workbook-teardown-mock-") as tmp:
            harness = Path(tmp) / "teardown.ps1"
            state = Path(tmp) / "V10_CONTROLLER_STATE.json"
            harness.write_text(harness_script, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(harness),
                 str(CONTROLLER), str(state)],
                capture_output=True, text=True, errors="replace", timeout=50,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("V10_WORKBOOK_TEARDOWN_CASES_PASS=12", result.stdout)


if __name__ == "__main__":
    unittest.main()
