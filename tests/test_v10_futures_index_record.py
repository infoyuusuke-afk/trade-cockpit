"""D-045 R2 (OWNER 2026-10-22 「先物を追加」「グロースも追加」「限月202612、止めるスイッチ付き」):
the Collector records 7 futures/index series to records/<day>/futures_index.csv. Record only:
no signal, gate, Brain input or voice uses them. Local config switch and OWNER months; no
floating near-month code is trusted without its returned month. Synthetic checks only."""
import json
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


def _function(text, name):
    start = text.index("function " + name)
    return text[start:text.index("\n}\n", start) + 2]


def _ps(script_body):
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "t.ps1"
        script.write_text(script_body, encoding="utf-8-sig")
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                              capture_output=True, text=True, timeout=60).stdout.replace("\r\n", "\n")


WINDOWS = os.name == "nt" and shutil.which("powershell")


class SevenSeries(unittest.TestCase):
    def test_exact_series_and_no_floating_month(self):
        text = _text()
        defs = text[text.index("$futIndexDefs = @("):text.index("$futItems = @(")]
        self.assertEqual(defs.count("Key = "), 7)
        for key, code, resolve, fn in (("N225MF", "N225MF", "RssFOPCode", "RssFOPMarket"),
                                       ("TOPIX", "05", "JPX9", "RssFOPMarket"),
                                       ("MOTF", "MOTF", "RssFOPCode", "RssFOPMarket"),
                                       ("N225", "N225", "", "RssIndexMarket"), ("TOPX", "TOPX", "", "RssIndexMarket"),
                                       ("MTHR", "MTHR", "", "RssIndexMarket"), ("TSGM", "TSGM", "", "RssIndexMarket")):
            self.assertRegex(defs, r'Key = "%s";\s+Code = "%s";\s+Resolve = "%s";\s+Name = "[^"]+";\s+Fn = "%s"'
                             % (re.escape(key), re.escape(code), resolve, fn))
        for gone in ("N225.FUT01.OS", "N225.FUT01.C", "N225M.FUT01.OS", "MOT.FUT01.OS", "Get-CentralQuarterMonth"):
            self.assertNotIn(gone, text)
        self.assertIn('"建玉","限月")', text)
        # OWNER 2026-10-23: TOPX.FUT01.OS is an RssIndexMarket code; TOPIX futures use the 9-digit code
        self.assertNotIn('Code = "TOPX.FUT01.OS"', text)
        self.assertIn('$fiJpxCode = ConvertTo-JpxFutureCode $fiMonth ([string]$fiDef.Code)', text)
        # every futures row is kept only when its returned 限月 equals the configured month
        self.assertIn('elseif ($fiSeen -ne $fiMonth) { $fiStatus = "MONTH_NOT_CONFIRMED" }', text)

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_topix_nine_digit_code_from_the_configured_month(self):
        text = _text()
        start = text.index("function ConvertTo-JpxFutureCode")
        fn = text[start:text.index("\n}\n", start) + 2]
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "t.ps1"
            script.write_text(fn + "\n" + "\n".join("Write-Output ('R=' + [string](ConvertTo-JpxFutureCode '%s' '%s'))" % m
                                                      for m in (("202612", "05"), ("202612", "19"), ("202703", "05"),
                                                                ("202612", "11"), ("2026xx", "05"))), encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                 capture_output=True, text=True, timeout=60).stdout.split()
        # 161120019 and 161120011 are the codes RSS itself resolved for 日経225ミニ / グロース250 202612 (2026-10-23)
        self.assertEqual(out, ["R=161120005", "R=161120019", "R=162030005", "R=161120011", "R="])

    def test_off_by_default_and_record_only(self):
        text = _text()
        self.assertIn('$d045ConfigPath = Join-Path $PSScriptRoot "d045_futures_index_config.json"', text)
        self.assertIn('Write-Host "[FUT_INDEX] OFF (no local D-045 config or switched off)"', text)
        block_start = text.index("# OWNER 2026-10-22 「先物を追加」")
        block_end = text.index("# 決算・IR開示があった銘柄")
        cycle_start = text.index("# OWNER 2026-10-22: futures and index quotes, record only")
        cycle_end = text.index("$script:preopenIdentitySpare = $null", cycle_start)
        for m in re.finditer(r"\$fi[A-Z]\w*|\$futIndex\w*|\$d045\w*", text):   # used only in the two blocks
            self.assertTrue(block_start <= m.start() < block_end or cycle_start <= m.start() < cycle_end,
                            text[m.start():m.start() + 40])
        self.assertIn("recorder suspended, Collector continues", text[cycle_start:cycle_end])
        self.assertIn("captured_at,key,code,configured_month,contract_code,contract_month_seen,status,name,price,"
                      "source_clock,source_precision,lag_seconds,lag_min_seconds,lag_max_seconds", text)
        self.assertFalse((ROOT / "ms2_live" / "d045_futures_index_config.json").exists())   # never in GitHub


@unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
class Helpers(unittest.TestCase):
    def test_owner_month_valid_until_its_sq(self):
        func = _function(_text(), "Test-D045Month")
        cases = (("202612", "2026-10-22", "True"), ("202612", "2026-12-10", "True"), ("202612", "2026-12-11", "False"),
                 ("202611", "2026-10-22", "False"), ("2026-12", "2026-10-22", "False"), ("", "2026-10-22", "False"))
        out = _ps(func + "\n" + "\n".join('Write-Output ("%s|%s=" + (Test-D045Month "%s" ([datetime]"%s")))'
                                          % (m, d, m, d) for m, d, _ in cases) + "\n")
        for m, d, want in cases:
            self.assertIn("%s|%s=%s" % (m, d, want), out)

    def test_returned_month_forms(self):
        func = _function(_text(), "ConvertTo-D045Month")
        out = _ps(func + "\n" + "\n".join('Write-Output ("%s=" + [string](ConvertTo-D045Month "%s"))' % (v, v)
                                          for v in ("202612", "2026/12", "26/12", "x", "")) + "\n")
        for v, want in (("202612", "202612"), ("2026/12", "202612"), ("26/12", "202612"), ("x", ""), ("", "")):
            self.assertIn("%s=%s\n" % (v, want), out)

    def test_clock_precision_is_never_padded(self):
        func = _function(_text(), "ConvertTo-FutIndexClock")
        out = _ps(func + "\n" + "\n".join([
            'Write-Output ("A=" + (ConvertTo-FutIndexClock "9:05:07" "second"))',
            'Write-Output ("B=" + [string](ConvertTo-FutIndexClock "15:44" "second"))',   # no seconds: no clock
            'Write-Output ("C=" + (ConvertTo-FutIndexClock "15:44" "minute"))',
            'Write-Output ("D=" + (ConvertTo-FutIndexClock ([double]0.5) "second"))',
            'Write-Output ("E=" + (ConvertTo-FutIndexClock "15:44:30" "minute"))',
            'Write-Output ("F=" + [string](ConvertTo-FutIndexClock "-" "minute"))',
        ]) + "\n")
        for want in ("A=09:05:07\n", "B=\n", "C=15:44\n", "D=12:00:00\n", "E=15:44\n", "F=\n"):
            self.assertIn(want, out)

    def test_lag_exact_range_and_future(self):
        func = _function(_text(), "Get-FutIndexLag")
        out = _ps(func + "\n" + "\n".join([
            '$n = [datetime]"2026-10-23 10:00:30"',
            '$a = Get-FutIndexLag $n "10:00:10" "second"; Write-Output ("A=" + $a.Exact + "|" + $a.Min + "|" + $a.Max)',
            '$b = Get-FutIndexLag $n "09:59" "minute"; Write-Output ("B=" + $b.Exact + "|" + $b.Min + "|" + $b.Max)',
            '$c = Get-FutIndexLag $n "10:01:00" "second"; Write-Output ("C=" + $c.Exact + "|" + $c.Min + "|" + $c.Max)',
            '$d = Get-FutIndexLag $n "10:01" "minute"; Write-Output ("D=" + $d.Exact + "|" + $d.Min + "|" + $d.Max)',
            '$e = Get-FutIndexLag ([datetime]"2026-10-23 00:00:20") "23:59:50" "second"; Write-Output ("E=" + $e.Exact)',
        ]) + "\n")
        for want in ("A=20|20|20\n", "B=|31|90\n", "C=||\n", "D=||\n", "E=\n"):
            self.assertIn(want, out)

    def test_switch_off_is_latched(self):
        text = _text()
        func = _function(text, "Get-D045Config")
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.json"
            on = json.dumps({"schema": "100b-d045-config-v1", "enabled": True,
                             "contract_month": {"N225MF": "202612", "TOPIX": "202612", "MOTF": "202612"}})
            off = on.replace("true", "false")
            out = _ps("$d045ConfigPath = '%s'\n$d045Latched = $false\n" % cfg + func + "\n" + "\n".join([
                'Write-Output ("missing=" + [string]($null -eq (Get-D045Config)))',
                "[IO.File]::WriteAllText($d045ConfigPath, '%s')" % on,
                'Write-Output ("on=" + (Get-D045Config).contract_month.N225MF)',
                "[IO.File]::WriteAllText($d045ConfigPath, '%s')" % off,
                'Write-Output ("off=" + [string]($null -eq (Get-D045Config)))',
                "[IO.File]::WriteAllText($d045ConfigPath, '%s')" % on,
                'Write-Output ("still_off=" + [string]($null -eq (Get-D045Config)))',
            ]) + "\n")
        for want in ("missing=True\n", "on=202612\n", "off=True\n", "still_off=True\n"):
            self.assertIn(want, out)


if __name__ == "__main__":
    unittest.main()
