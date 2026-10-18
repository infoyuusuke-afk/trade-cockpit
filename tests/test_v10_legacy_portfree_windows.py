"""Production Controller legacy argv guard against port-free orphan runtimes.
Windows Actions-only pure mocks: no real process/Excel/port activity.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows"
    and shutil.which("powershell.exe"), "Windows synthetic-only",
)
class LegacyPortFree(unittest.TestCase):
    def test_refuse_dormant_legacy_processes_without_terminating(self):
        script = r'''
param([string]$Source)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'CONTROLLER_PARSE_FAILED'}
$defs=@($ast.FindAll({
    param($n)
    $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -eq 'Assert-NoUnmanagedLegacyRuntimeProcesses'
},$true))
if($defs.Count -ne 1){throw 'LEGACY_GUARD_NOT_UNIQUE'}
. ([scriptblock]::Create($defs[0].Extent.Text))
$script:Processes=@()
$script:Denied=$false
$script:Scanned=0
function Get-CimInstance {
    param([string]$ClassName)
    $script:Scanned++
    if($script:Denied){throw 'CIM_ACCESS_DENIED'}
    return $script:Processes
}
function Assert-Case([string]$Command,[bool]$ExpectedBlock,[string]$Name='powershell.exe') {
    $script:Processes=@([pscustomobject]@{
        Name=$Name
        ProcessId=45678
        CommandLine=$Command
    })
    $blocked=$false
    try { Assert-NoUnmanagedLegacyRuntimeProcesses }
    catch {
        $blocked=$true
        if($_.Exception.Message -notmatch 'UNMANAGED_LEGACY_RUNTIME_PROCESS'){
            throw ('WRONG_BLOCK_REASON_'+$_.Exception.Message)
        }
    }
    if($blocked -ne $ExpectedBlock){
        throw ('LEGACY_CASE_FAILED_'+$script:Scanned+'_'+$Command)
    }
}
Assert-Case 'powershell -File C:\legacy\RUN_AI_COCKPIT_V9.ps1' $true
Assert-Case 'powershell -File C:\legacy\AI_COCKPIT_CONTROLLER_V8.ps1' $true
Assert-Case 'powershell -File C:\legacy\AI_COCKPIT_GATEWAY_V9.ps1' $true
Assert-Case 'powershell -File C:\legacy\Kioxia_RSS_Live_Watcher.ps1' $true
Assert-Case 'powershell -File C:\legacy\MS2_RSS_100_Collector.ps1' $true
Assert-Case 'powershell -File C:\legacy\SPEAK_LIVE_EMOTION.ps1' $true
Assert-Case 'powershell -File C:\current\AI_COCKPIT_CONTROLLER_V10.ps1' $false
Assert-Case 'powershell -File C:\scripts\UNRELATED.ps1' $false
Assert-Case 'python -m pytest tests/test_RUN_AI_COCKPIT_V9.ps1' $false 'python.exe'
$script:Processes=@([pscustomobject]@{
    Name='powershell.exe'; ProcessId=45678; CommandLine=''
})
$blocked=$false
try { Assert-NoUnmanagedLegacyRuntimeProcesses } catch {
    $blocked=($_.Exception.Message -match 'UNMANAGED_RUNTIME_COMMANDLINE_UNAVAILABLE')
}
if(-not $blocked){throw 'UNREADABLE_POWERSHELL_ARGV_ALLOWED'}
Assert-Case '' $false 'notepad.exe'
$script:Denied=$true
$blocked=$false
try { Assert-NoUnmanagedLegacyRuntimeProcesses } catch {
    $blocked=($_.Exception.Message -match 'UNMANAGED_RUNTIME_INVENTORY_UNAVAILABLE')
}
if(-not $blocked){throw 'CIM_FAILURE_ALLOWED'}
Write-Output ('LEGACY_PORTFREE_CASES_PASS='+($script:Scanned))
'''
        with tempfile.TemporaryDirectory(prefix="v10-legacy-portfree-") as tmp:
            harness = Path(tmp) / "mock.ps1"
            harness.write_text(script, encoding="utf-8")
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(harness), str(SOURCE)],
                capture_output=True, text=True, errors="replace", timeout=40,
            )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("LEGACY_PORTFREE_CASES_PASS=12", r.stdout)


    def test_real_controller_readonly_audit_creates_no_state_or_workers(self):
        # Run the actual Controller entrypoint in its dedicated pre-start
        # inspection mode. Runner inventory may legitimately be CLEAR or
        # BLOCKED; both are fail-closed as regards startup side effects.
        with tempfile.TemporaryDirectory(prefix="v10-audit-only-", dir=os.environ["RUNNER_TEMP"]) as tmp:
            root = Path(tmp) / "nonexistent-state-root"
            self.assertFalse(root.exists())
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(SOURCE),
                 "-Root", str(root), "-LegacyRuntimeAuditOnly"],
                capture_output=True, text=True, errors="replace", timeout=40,
            )
            self.assertIn(result.returncode, (0, 2), result.stdout + result.stderr)
            self.assertIn("V10_LEGACY_RUNTIME_AUDIT=READONLY", result.stdout)
            self.assertIn("PROCESS_TERMINATED=0", result.stdout)
            self.assertIn("STATE_MUTATED=0", result.stdout)
            self.assertIn("EXCEL_STARTED=0", result.stdout)
            self.assertIn("CONTROLLER_STARTED=0", result.stdout)
            if result.returncode == 0:
                self.assertIn("V10_LEGACY_RUNTIME_AUDIT=CLEAR_OBSERVED_INTERPRETERS", result.stdout)
            else:
                self.assertIn("V10_LEGACY_RUNTIME_AUDIT=BLOCKED", result.stdout)
                self.assertIn("AUDIT_REASON=", result.stdout)
            self.assertFalse(root.exists(), "read-only audit created StateRoot")


if __name__ == "__main__":
    unittest.main()
