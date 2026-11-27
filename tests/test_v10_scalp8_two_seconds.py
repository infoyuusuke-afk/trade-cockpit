"""OWNER 2026-11-08 「歩み値と板の直しを、1周の内訳の記録・SCALP8を2秒おき・出来高での突き合わせの3つで1つの版にして、
テストとCIの後に監査に回して」. Synthetic checks only: no workbook, no record, no account file."""
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


def _ps(body):
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "t.ps1"
        script.write_text(body, encoding="utf-8-sig")
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                              capture_output=True, text=True, timeout=60).stdout.replace("\r\n", "\n")


class LoopTimingFile(unittest.TestCase):
    def test_the_timing_line_is_also_written_to_a_file(self):
        text = _text()
        self.assertIn('$timingCsv = Join-Path $dayDir "collector_timing.csv"', text)
        self.assertIn('Ensure-Csv $timingCsv "captured_at,busy_ms,wait_ms,wait_reads_s8,marks"', text)
        # writing the timing never stops the loop
        tail = text[text.index('$timingCsv = Join-Path $dayDir'):]
        self.assertIn("} catch { }", tail[:600])


class TwoSecondRead(unittest.TestCase):
    def test_the_read_is_one_block_run_in_place_and_from_the_wait(self):
        text = _text()
        self.assertEqual(text.count("$scalp8ReadBlock = {"), 1)
        self.assertEqual(text.count(". $scalp8ReadBlock"), 2)
        self.assertIn("$Scalp8ReadEveryMs = 2000", text)
        wait = text[text.index("$waitUntil = $waitStarted.AddSeconds($IntervalSeconds)"):text.index("} finally {\n    if ($null -ne $bridgeJob)")]
        self.assertIn("((Get-Date) - $scalp8LastReadAt).TotalMilliseconds -ge $Scalp8ReadEveryMs", wait)
        self.assertIn("Start-Sleep -Milliseconds ([int][Math]::Min(250, [Math]::Ceiling($waitLeft)))", wait)
        # the loop still waits the same 2 s in total; nothing else is read or written there
        self.assertNotIn("Invoke-ExcelCom", wait)
        self.assertNotIn("Speak", wait)

    def test_a_busy_excel_holds_the_scalp8_read_at_most_about_2_s(self):
        self.assertIn('Invoke-ExcelCom -Retries 8 -Label "SCALP8値取得"', _text())


class VolumeCheck(unittest.TestCase):
    def test_the_volume_cell_and_its_record(self):
        text = _text()
        self.assertIn("$s8VolFormula = '=RssMarket(\"' + $s8Sym + '\",\"出来高\")'", text)
        self.assertIn("$sheet.Cells.Item(2, $s8Col).FormulaLocal = [string]$s8VolFormula", text)
        self.assertIn('$s8VolCsv = Join-Path $dayDir "scalp8_volume_check.csv"', text)
        self.assertIn('"captured_at,read_seq,ticker,volume,delta,new_shares,missing_shares,candidates,gap"', text)
        self.assertIn("$diff = Get-Scalp8NewTicksByVolume $scalp8PrevKeys[$code] $keys $s8Vols $s8Delta", text)

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_the_volume_decides_where_the_window_sits(self):
        text = _text()
        fn = _function(text, "Get-Scalp8NewTicks") + _function(text, "Get-Scalp8NewTicksByVolume")
        out = _ps(fn + r'''
function Show($r) { Write-Output ("N=" + @($r.New).Count + " G=" + $r.Gap + " M=" + $r.Missing + " C=" + $r.Candidates) }
# 4 identical prints of 100 shares; 2 more identical ones came. The 10-print probe matches at the top (0 new);
# the volume (+200) says 2 are new.
$prev = @("t|1|100","t|1|100","t|1|100","t|1|100")
$cur = @("t|1|100","t|1|100","t|1|100","t|1|100","t|1|100","t|1|100")
Show (Get-Scalp8NewTicks $prev $cur)
Show (Get-Scalp8NewTicksByVolume $prev $cur @(100,100,100,100,100,100) 200)
# the ordinary case: 2 new prints on top, the volume agrees
Show (Get-Scalp8NewTicksByVolume @("a|1|100","b|1|200") @("x|1|300","y|1|400","a|1|100","b|1|200") @(300,400,100,200) 700)
# the previous window is gone: all new, and 500 shares were lost in between
Show (Get-Scalp8NewTicksByVolume @("a|1|100","b|1|100") @("x|1|300","y|1|200") @(300,200) 1000)
# no volume (first read or the cell is empty): exactly the old matching
Show (Get-Scalp8NewTicksByVolume @("a|1|100","b|1|100") @("x|1|300","a|1|100","b|1|100") @(300,100,100) $null)
# the volume went down (a new day or a bad cell): the old matching
Show (Get-Scalp8NewTicksByVolume @("a|1|100","b|1|100") @("x|1|300","a|1|100","b|1|100") @(300,100,100) (-50))
# a one-item previous window still matches (a single string is not taken apart into letters)
Show (Get-Scalp8NewTicksByVolume @("a|1|100") @("x|1|300","a|1|100") @(300,100) 300)
''')
        self.assertEqual(out.split("\n")[:7], [
            "N=0 G=False M= C=",          # the old probe: two new prints dropped
            "N=2 G=False M=0 C=3",        # by volume: both kept
            "N=2 G=False M=0 C=1",
            "N=2 G=True M=500 C=0",
            "N=1 G=False M= C=0",
            "N=1 G=False M= C=0",
            "N=1 G=False M=0 C=1",
        ])


if __name__ == "__main__":
    unittest.main()
