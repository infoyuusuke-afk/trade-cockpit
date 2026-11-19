"""OWNER 2026-11-20 「約定の時刻も毎日残して」: the collector keeps the time of each of today's executions (real_positions_v1.json
executions_today[].time) and the names of the execution list's columns (executions_columns). Read only; no order."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
WINDOWS = os.name == "nt"


def _collector():
    return COLLECTOR.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


class ExecTimeText(unittest.TestCase):
    def test_row_keeps_time(self):
        t = _collector()
        self.assertIn('price = Get-RealPosNumber $p."約定単価"; time = Get-RealPosExecTime $p }', t)
        self.assertIn("executions_columns = $rpExecColumns", t)
        self.assertIn("function Get-RealPosTime($Value) {", t)
        self.assertIn("function Get-RealPosExecTime($Row) {", t)

    def test_no_order_words(self):
        t = _collector()
        a = t.index("function Get-RealPosTime($Value) {")
        b = t.index("function Get-AccountRetrySeconds", a)
        for w in ("RssStockOrder", "RssMarginOpenOrder", "RssMarginCloseOrder", "Invoke-WebRequest"):
            self.assertNotIn(w, t[a:b])


@unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
class ExecTimeRun(unittest.TestCase):
    def test_times(self):
        text = _collector()
        fns = ""
        for name in ("Get-RealPosTime", "Get-RealPosExecTime"):
            s = text.index("function " + name)
            fns += text[s:text.index("\n}\n", s) + 2]
        script = fns + r'''
$a = [pscustomobject]@{ "約定日" = ([DateTime]::new(2026,11,20,9,1,5)).ToOADate() }
$b = [pscustomobject]@{ "約定日" = ([DateTime]::new(2026,11,20)).ToOADate() }
$c = [pscustomobject]@{ "約定日" = "2026/11/20 9:01" }
$d = [pscustomobject]@{ "約定日" = "2026/11/20"; "約定時刻" = "10:15:30" }
$e = [pscustomobject]@{ "約定日" = "2026/11/20" }
$f = [pscustomobject]@{ "約定日" = "2026/11/20"; "約定時刻" = "--------" }
Write-Output ("T=" + (Get-RealPosExecTime $a) + "|" + (Get-RealPosExecTime $b) + "|" + (Get-RealPosExecTime $c) + "|" + (Get-RealPosExecTime $d) + "|" + (Get-RealPosExecTime $e) + "|" + (Get-RealPosExecTime $f) + "|")
'''
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.ps1"
            p.write_text(script, encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout.split()
        self.assertEqual(out[-1], "T=09:01:05||09:01:00|10:15:30|||")


if __name__ == "__main__":
    unittest.main()
