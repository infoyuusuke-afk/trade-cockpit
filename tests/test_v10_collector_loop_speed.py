"""OWNER 2026-10-24: the Collector loop grew from ~1.3 s to 10-19 s within a couple of hours (10-23 session
and overnight logs) because each cycle walked the whole day's 1-minute bars of 100 rows with
Select-Object pipelines and a full-day EMA. The replacements must give the same values and stay flat."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
WINDOWS = os.name == "nt" and shutil.which("powershell")


def _text():
    return COLLECTOR.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def _function(text, name):
    start = text.index("function " + name)
    return text[start:text.index("\n}\n", start) + 2]


class NoWholeDayPipelines(unittest.TestCase):
    def test_static(self):
        text = _text()
        self.assertNotIn("Select-Object -SkipLast", text)
        self.assertNotIn("|Select-Object -Last $LiveRowBars", text)
        self.assertIn("$priorBars=@(Get-LastItems $completedBars[0..($completedBars.Count-2)] 10)", text)
        self.assertIn("return @(Get-LastItems @($groups.Values) 180)", text)


@unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
class SameValuesFlatTime(unittest.TestCase):
    def test_same_values_as_before(self):
        text = _text()
        fns = _function(text, "Get-LastItems") + _function(text, "Get-EmaValue")
        script = fns + r'''
$bars = New-Object System.Collections.ArrayList
$p = 1000.0
for ($i = 0; $i -lt 390; $i++) { $p = $p + [Math]::Sin($i / 7.0) * 3 + (($i % 5) - 2); [void]$bars.Add([pscustomobject]@{ Close = $p; High = $p + 2; Low = $p - 2; Open = $p - 1; Volume = 100 + $i }) }
$c = @($bars)
# old forms
$oldPrior = @($c | Select-Object -SkipLast 1 | Select-Object -Last 10)
$oldRanges = @($c | Select-Object -Last 14 | ForEach-Object { [double]$_.High - [double]$_.Low })
$alpha = 2.0 / 21.0; $ema = [double]$c[0].Close; foreach ($b in $c) { $ema = ([double]$b.Close * $alpha) + ($ema * (1.0 - $alpha)) }
# new forms
$newPrior = @(Get-LastItems $c[0..($c.Count-2)] 10)
$newRanges = @(Get-LastItems $c 14 | ForEach-Object { [double]$_.High - [double]$_.Low })
$newEma = Get-EmaValue $c 20
$oldS = (@($oldPrior | ForEach-Object Close)) -join ","
$newS = (@($newPrior | ForEach-Object Close)) -join ","
Write-Output ("PRIOR=" + ($oldS -eq $newS))
Write-Output ("PRIORN=" + $newPrior.Count)
$oR = $oldRanges -join ","; $nR = $newRanges -join ","
Write-Output ("RANGES=" + ($oR -eq $nR))
Write-Output ("EMADIFF=" + [Math]::Round([Math]::Abs($ema - $newEma), 6))
$small = @(Get-LastItems @(1,2) 10)
Write-Output ("SMALL=" + ($small -join ","))
Write-Output ("EMPTY=" + @(Get-LastItems @() 5).Count)
$sw = [Diagnostics.Stopwatch]::StartNew(); for ($k = 0; $k -lt 100; $k++) { $null = @($c | Select-Object -SkipLast 1 | Select-Object -Last 10); $null = Get-EmaValue $c 9 }; $old = $sw.ElapsedMilliseconds
$sw.Restart(); for ($k = 0; $k -lt 100; $k++) { $null = @(Get-LastItems $c[0..($c.Count-2)] 10) }; $new = $sw.ElapsedMilliseconds
Write-Output ("FASTER=" + ($new -lt $old))
'''
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.ps1"
            p.write_text(script, encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)],
                                 capture_output=True, text=True, timeout=180).stdout.split()
        got = dict(x.split("=", 1) for x in out if "=" in x)
        self.assertTrue(got, out)
        self.assertEqual(got["PRIOR"], "True")
        self.assertEqual(got["PRIORN"], "10")
        self.assertEqual(got["RANGES"], "True")
        self.assertLess(float(got["EMADIFF"]), 0.01)       # well below one tick
        self.assertEqual(got["SMALL"], "1,2")
        self.assertEqual(got["EMPTY"], "0")
        self.assertEqual(got["FASTER"], "True")


if __name__ == "__main__":
    unittest.main()
