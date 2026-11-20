"""P0-V10-INTEGRATION-AND-LIVE-START-20261020 (P0-3): worker logs survive STOP/START.

The Controller used to delete each worker's stdout/stderr log before starting
it, so a restart erased the previous run. Save-PreviousWorkerLogs now moves an
existing log to Logs\\V10\\previous_runs under a unique name and deletes
nothing. Synthetic files only; approves no deployment.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"


class ControllerSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = CONTROLLER.read_text(encoding="utf-8-sig").replace("\r\n", "\n")

    def test_no_worker_log_is_deleted_before_start(self):
        self.assertNotRegex(self.src, r"Remove-Item -LiteralPath \$stdout")
        self.assertEqual(len(re.findall(r"^\s+Save-PreviousWorkerLogs @\(\$stdout, \$stderr\)$", self.src, re.M)), 4)

    def test_archive_function_moves_and_never_removes(self):
        match = re.search(r"^function Save-PreviousWorkerLogs\b.*?^}\n", self.src, re.M | re.S)
        self.assertIsNotNone(match)
        body = match.group(0)
        self.assertIn("Move-Item -LiteralPath $path", body)
        self.assertNotIn("Remove-Item", body)
        self.assertIn('Join-Path $LogDir "previous_runs"', body)


HARNESS = r"""
param([string]$Controller, [string]$LogDirectory, [string]$Locked)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Controller, [ref]$t, [ref]$e)
if ($e.Count) { throw "PARSE_FAILED" }
$defs = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Save-PreviousWorkerLogs' }, $true))
if ($defs.Count -ne 1) { throw "HELPER_MISSING" }
. ([scriptblock]::Create($defs[0].Extent.Text))
$LogDir = $LogDirectory
$out = Join-Path $LogDir 'collector_stdout.log'
$err = Join-Path $LogDir 'collector_stderr.log'
Save-PreviousWorkerLogs @($out, $err, (Join-Path $LogDir 'absent.log'), '')
Save-PreviousWorkerLogs @($out, $err)
$stream = [IO.File]::Open($Locked, 'Open', 'Read', 'None')
try { Save-PreviousWorkerLogs @($Locked) } finally { $stream.Dispose() }
$archived = @(Get-ChildItem -LiteralPath (Join-Path $LogDir 'previous_runs') -File | ForEach-Object { [ordered]@{ name = $_.Name; text = [IO.File]::ReadAllText($_.FullName) } })
[ordered]@{ ps_major = $PSVersionTable.PSVersion.Major; out_exists = (Test-Path -LiteralPath $out); err_exists = (Test-Path -LiteralPath $err); locked_exists = (Test-Path -LiteralPath $Locked); archived = $archived } | ConvertTo-Json -Depth 4 -Compress
"""


class SavePreviousWorkerLogsWindows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exe = shutil.which("powershell") if os.name == "nt" else None
        if exe is None:
            raise unittest.SkipTest("Windows PowerShell 5.1 not available; the Windows CI job runs this class")
        cls.tmp = Path(tempfile.mkdtemp(prefix="v10-logkeep-"))
        logs = cls.tmp / "Logs" / "V10"
        logs.mkdir(parents=True)
        (logs / "collector_stdout.log").write_text("previous run stdout", encoding="utf-8")
        (logs / "collector_stderr.log").write_text("previous run stderr", encoding="utf-8")
        locked = logs / "gateway_stdout.log"
        locked.write_text("locked log", encoding="utf-8")
        script = cls.tmp / "harness.ps1"
        script.write_text(HARNESS, encoding="utf-8-sig")
        proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                               "-Controller", str(CONTROLLER), "-LogDirectory", str(logs), "-Locked", str(locked)],
                              capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise AssertionError(proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace"))
        cls.result = json.loads(proc.stdout.decode("utf-8", "replace").strip().splitlines()[-1].lstrip("﻿"))

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_runs_on_windows_powershell_5(self):
        self.assertEqual(self.result["ps_major"], 5)

    def test_previous_logs_are_moved_with_content(self):
        self.assertIs(self.result["out_exists"], False)
        self.assertIs(self.result["err_exists"], False)
        texts = sorted(a["text"] for a in self.result["archived"])
        self.assertEqual(texts, ["previous run stderr", "previous run stdout"])
        for item in self.result["archived"]:
            self.assertRegex(item["name"], r"^collector_std(out|err)\.\d{8}-\d{6}-\d{3}\.[0-9a-f]{8}\.log$")

    def test_locked_log_is_left_in_place_not_deleted(self):
        self.assertIs(self.result["locked_exists"], True)
        self.assertNotIn("locked log", [a["text"] for a in self.result["archived"]])


if __name__ == "__main__":
    unittest.main()
