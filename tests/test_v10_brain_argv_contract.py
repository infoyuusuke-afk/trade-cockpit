"""Exercise only the parsed identity function; never execute the STOP entry."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows argv parser")
class BrainArgvContract(unittest.TestCase):
    def test_exact_controller_contract_and_decoys(self):
        # AST extraction cannot run top-level stop logic or inspect real processes.
        source = ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1"
        script = r'''
param([string]$Source)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'PARSE_FAILED'}
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-BrainCommandLine'},$true))
if($fn.Count -ne 1){throw 'FUNCTION_NOT_UNIQUE'}
. ([scriptblock]::Create($fn[0].Extent.Text))
$repo='C:\synthetic repo'; $runtime='C:\synthetic runtime'
$tail='-u "C:\synthetic repo\scripts\ai_brain_observer.py" --live "C:\synthetic runtime\live_ms2.json" --status "C:\synthetic runtime\ai_brain_observer_status_v1.json" --interval 5'
$valid='"C:\Python\python.exe" '+$tail
$cases=@(
    @($valid,$true),
    @(('"C:\Python\pythonw.exe" '+$tail),$true),
    @(('"C:\Python\py.exe" -3 '+$tail),$true),
    @(('"C:\Python\python.exe" -c "import time; time.sleep(120)" '+$tail),$false),
    @(('"C:\Python\python.exe" -m foreign '+$tail),$false),
    @($valid.Replace('ai_brain_observer.py','ai_brain_observer.py.foreign.py'),$false),
    @($valid.Replace('live_ms2.json','live_ms2.json.backup'),$false),
    @(($valid+' --status C:\foreign.json'),$false),
    @($valid.Replace('--live','--LIVE'),$false),
    @($valid.Replace('--interval 5','--interval 10'),$false),
    @($valid.Replace('python.exe','cmd.exe'),$false),
    @('',$false)
)
$count=0
foreach($case in $cases){
    $actual=Test-BrainCommandLine $case[0] $repo $runtime
    if($actual -ne $case[1]){throw ('CASE_FAILED_'+$count)}
    $count++
}
Write-Output "ARGV_CASES_PASS=$count"
'''
        with tempfile.TemporaryDirectory(prefix="brain-argv-pure-") as tmp:
            harness = Path(tmp) / "contract.ps1"
            harness.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness), str(source)],
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ARGV_CASES_PASS=12", result.stdout)


if __name__ == "__main__":
    unittest.main()
