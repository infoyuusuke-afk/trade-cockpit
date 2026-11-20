"""The Collector logs one [TIMING] line per completed cycle (measurement only).

OWNER 2026-10-21: after the payload trim the in-session cycle was still
15-20 s against the 12-second LIVE screen contract. This build records the
milliseconds spent in each section of the loop so the slow part can be found
on the next trading day. It must not change any decision or output.
This test runs the shipped Add-LoopMark in powershell.exe 5.1 and checks
that every mark sits at the top level of the loop body. Synthetic only.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
MARKS = ["excel_read", "rows_read", "identity", "process_check", "kioxia", "pts_ir_signal",
         "aggregate", "rows_decide", "hold", "prepare", "json_write", "html_build", "voice_tail"]

HARNESS = r"""
param([string]$Collector)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Collector, [ref]$t, [ref]$e)
if ($e.Count) { throw 'PARSE_FAILED' }
$fn = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Add-LoopMark' }, $true))
if ($fn.Count -ne 1) { throw 'ADD_LOOP_MARK_COUNT' }
. ([scriptblock]::Create($fn[0].Extent.Text))
Add-LoopMark 'before_start'
$script:loopTimer = [Diagnostics.Stopwatch]::StartNew(); $script:loopLastMs = 0; $script:loopMarks = New-Object System.Collections.Generic.List[string]
Start-Sleep -Milliseconds 60
Add-LoopMark 'a'
Add-LoopMark 'b'
$script:loopMarks -join ' '
"""


class CollectorLoopTiming(unittest.TestCase):
    def test_marks_are_in_order_in_the_main_loop(self):
        src = COLLECTOR.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        loop = src[src.index("    while ($true) {\n        # RssMarket"):src.index("} finally {\n    if ($null -ne $bridgeJob)")]
        pos = [loop.index("        Add-LoopMark '" + m + "'\n") for m in MARKS]
        self.assertEqual(pos, sorted(pos))
        self.assertIn("Write-Host ('[TIMING] '", loop)
        self.assertLess(loop.index("$script:loopTimer = [Diagnostics.Stopwatch]::StartNew()"), pos[0])

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
    def test_add_loop_mark_records_section_milliseconds(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "harness.ps1"
            h.write_text(HARNESS, encoding="utf-8-sig")
            p = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Collector", str(COLLECTOR)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout.strip().splitlines()[-1].split()
        self.assertEqual([x.split("=")[0] for x in out], ["a", "b"])
        self.assertGreaterEqual(int(out[0].split("=")[1]), 50)


if __name__ == "__main__":
    unittest.main()
