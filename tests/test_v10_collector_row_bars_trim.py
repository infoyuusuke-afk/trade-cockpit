"""live_ms2.json must stay small enough for the 12-second LIVE screen contract.

2026-10-21 OWNER PC (72824b3, 11:05 JST): every row of all_targets carried the
whole day's 1-minute and 5-minute bars and the payload was written indented,
so live_ms2.json was ~15MB, the Collector cycle took ~25 s and every LIVE panel
(REALTIME 5 TOP5, watchlist, pre-open ranking) showed "データ取得待ち".

This test extracts the shipped Convert-LiveBars and Get-LastItems functions and the row-bars
block from the Collector and runs them in powershell.exe 5.1 with 300
synthetic minute bars: a normal row keeps the last 60 1-minute and 24 5-minute
bars, Kioxia (285A.T) keeps what it had before (Convert-LiveBars: last 180). It also pins the compressed write.
Synthetic values only.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"

HARNESS = r"""
param([string]$Collector)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Collector, [ref]$t, [ref]$e)
if ($e.Count) { throw 'PARSE_FAILED' }
foreach ($name in @('Convert-LiveBars', 'Get-LastItems')) {
    $fn = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true))
    if ($fn.Count -ne 1) { throw ('FUNCTION_COUNT ' + $name) }
    . ([scriptblock]::Create($fn[0].Extent.Text))
}
$src = [IO.File]::ReadAllText($Collector)
$start = $src.IndexOf('            $rowBars=@($minuteBars[[string]$result.ticker])')
$endMark = '$result|Add-Member -NotePropertyName bars_5m -NotePropertyValue $rowBars5m -Force'
$end = $src.IndexOf($endMark)
if ($start -lt 0 -or $end -lt $start) { throw 'ROW_BARS_BLOCK_MISSING' }
$block = [scriptblock]::Create($src.Substring($start, $end - $start + $endMark.Length))
$LiveRowBars1m = 60; $LiveRowBars5m = 24
$bars = [Collections.ArrayList]::new()
$t0 = [DateTime]::new(2026, 10, 21, 9, 0, 0)
for ($i = 0; $i -lt 300; $i++) {
    [void]$bars.Add([pscustomobject]@{ ts = $t0.AddMinutes($i).ToString('yyyy-MM-dd HH:mm:ss'); o = 100 + $i; h = 101 + $i; l = 99 + $i; c = 100.5 + $i; v = 10 })
}
$out = [ordered]@{}
foreach ($ticker in @('6501.T', '285A.T')) {
    $minuteBars = @{ $ticker = $bars }
    $result = [pscustomobject]@{ ticker = $ticker; vwap = 150.0 }
    & $block
    $out[$ticker] = [ordered]@{ n1 = @($result.bars_1m).Count; n5 = @($result.bars_5m).Count; last1 = $result.bars_1m[-1].t; first5 = $result.bars_5m[0].t; last5 = $result.bars_5m[-1].t; first5o = $result.bars_5m[0].o }
}
$out | ConvertTo-Json -Depth 4 -Compress
"""


@unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
class CollectorRowBarsTrim(unittest.TestCase):
    def run_harness(self):
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "harness.ps1"
            h.write_text(HARNESS, encoding="utf-8-sig")
            p = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Collector", str(COLLECTOR)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout.strip().splitlines()[-1])

    def test_normal_row_keeps_recent_bars_and_kioxia_is_unchanged(self):
        out = self.run_harness()
        row = out["6501.T"]
        self.assertEqual(row["n1"], 60)
        self.assertEqual(row["last1"], "13:59")
        self.assertEqual(row["n5"], 24)
        self.assertEqual(row["last5"], "13:55")
        self.assertEqual(row["first5"], "12:00")
        # first kept 5-minute bucket is complete: its open is the 12:00 bar's open
        self.assertEqual(row["first5o"], 100 + 180)
        kio = out["285A.T"]
        self.assertEqual(kio["n1"], 180)  # unchanged: Convert-LiveBars keeps the last 180
        self.assertEqual(kio["n5"], 60)
        self.assertEqual(kio["first5"], "09:00")

    def test_live_payload_is_written_compressed(self):
        src = COLLECTOR.read_text(encoding="utf-8-sig")
        self.assertIn("$jsonText=$payload|ConvertTo-Json -Depth 6 -Compress", src)
        self.assertNotIn("$jsonText=$payload|ConvertTo-Json -Depth 6\n", src.replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()
