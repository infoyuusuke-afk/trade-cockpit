"""OWNER 2026-10-22 「先物を追加」「グロースも追加」: the Collector records futures (RssFOPMarket)
and indexes (RssIndexMarket) to records/<day>/futures_index.csv. Record only: no signal,
gate, Brain input or voice uses them. Synthetic checks; no Excel, no market data."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"


def _text():
    return COLLECTOR.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


class FuturesIndexRecord(unittest.TestCase):
    def test_codes_and_functions(self):
        # D-045 rev: 7 series; the large 225 and CME contracts are not recorded.
        text = _text()
        for code, month, fn in (("N225MF", "$futCentralMonth", "RssFOPMarket"), ("TOPX.FUT01.OS", '""', "RssFOPMarket"),
                                ("MOTF", "$futCentralMonth", "RssFOPMarket"), ("N225", '""', "RssIndexMarket"),
                                ("TOPX", '""', "RssIndexMarket"), ("MTHR", '""', "RssIndexMarket"),
                                ("TSGM", '""', "RssIndexMarket")):
            self.assertRegex(text, r'Code = "%s";\s+Month = %s;\s+Name = "[^"]+";\s+Fn = "%s"'
                             % (re.escape(code), re.escape(month), fn))
        defs = text[text.index("$futIndexDefs = @("):text.index("$futItems = @(")]
        self.assertEqual(defs.count("Code = "), 7)
        for gone in ("N225.FUT01.OS", "N225.FUT01.C", "N225M.FUT01.OS", "MOT.FUT01.OS"):
            self.assertNotIn(gone, text)
        self.assertIn("""'=RssFOPCode("' + [string]$fiDef.Code + '","' + [string]$fiDef.Month + '")'""", text)
        self.assertIn("""'=' + $fiDef.Fn + '(A' + [string]$fiRow + ',"' + [string]$fiItems[$j] + '")'""", text)
        self.assertIn('$futItems = @("現在値","現在値詳細時刻","前日比率","出来高","出来高加重平均","最良売気配値1","最良買気配値1","建玉")', text)
        self.assertIn('$indexItems = @("現在値","更新時刻","前日比率","出来高"', text)

    def test_record_only_and_never_fatal(self):
        text = _text()
        self.assertIn("captured_at,code,month,contract,name,price,quote_time,lag_seconds,change_pct,volume,vwap,ask,bid,open_interest", text)
        uses = [m.start() for m in re.finditer(r"\$fi[A-Z]\w*|\$futIndex\w*", text)]
        block_start = text.index("# OWNER 2026-10-22 「先物を追加」")
        block_end = text.index("# 決算・IR開示があった銘柄")
        cycle_start = text.index("# OWNER 2026-10-22: futures and index quotes, record only")
        cycle_end = text.index("$script:preopenIdentitySpare = $null", cycle_start)
        for at in uses:   # nothing outside the two blocks reads these values
            self.assertTrue(block_start <= at < block_end or cycle_start <= at < cycle_end, text[at:at + 40])
        self.assertIn('[FUT_INDEX] WARN / READ FAILED - Collector continues', text[cycle_start:cycle_end])
        self.assertIn('[FUT_INDEX] WARN / UNAVAILABLE - Collector continues', text[block_start:block_end])

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell 5.1 only")
    def test_central_quarter_month(self):
        text = _text()
        start = text.index("function Get-CentralQuarterMonth")
        func = text[start:text.index("\n}\n", start) + 2]
        cases = (("2026-10-22", "202612"), ("2026-12-10", "202612"), ("2026-12-11", "202703"),
                 ("2026-12-31", "202703"), ("2027-03-11", "202703"), ("2027-03-12", "202706"))
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "m.ps1"
            script.write_text(func + "\n" + "\n".join(
                'Write-Output ("%s=" + (Get-CentralQuarterMonth ([datetime]"%s")))' % (day, day) for day, _ in cases) + "\n",
                encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                 capture_output=True, text=True, timeout=60).stdout
            for day, month in cases:
                self.assertIn("%s=%s" % (day, month), out)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell 5.1 only")
    def test_quote_clock_from_text_or_day_fraction(self):
        text = _text()
        start = text.index("function ConvertTo-FutIndexClock")
        func = text[start:text.index("\n}\n", start) + 2]
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "t.ps1"
            script.write_text(func + "\n" + "\n".join([
                'Write-Output ("A=" + (ConvertTo-FutIndexClock "9:05:07"))',
                'Write-Output ("B=" + (ConvertTo-FutIndexClock "2026/10/22 15:44"))',
                'Write-Output ("C=" + (ConvertTo-FutIndexClock ([double]0.5)))',
                'Write-Output ("D=" + [string](ConvertTo-FutIndexClock "-"))',
            ]) + "\n", encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                 capture_output=True, text=True, timeout=60).stdout
            self.assertIn("A=09:05:07", out)
            self.assertIn("B=15:44:00", out)
            self.assertIn("C=12:00:00", out)
            self.assertIn("D=\n", out.replace("\r\n", "\n"))


if __name__ == "__main__":
    unittest.main()
