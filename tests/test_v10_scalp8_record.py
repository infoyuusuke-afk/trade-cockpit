"""SCALP-8 Phase 2 (OWNER 2026-10-23 「Phase 2」): the Collector records up to 8 focus issues'
RssTickList prints (with the volume of each print) and 10-level boards to records/<day>/scalp8_*.csv.
Record only: no signal, gate, Brain input, voice, screen or order uses them. Off without the local
config. Synthetic checks only."""
import json
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


def _cycle(text):
    start = text.index("# OWNER 2026-10-23 Phase 2: SCALP8 prints")
    # the SCALP8 block ends where the real-holdings reader (OWNER 2026-10-23 夜) starts
    return text[start:text.index("# OWNER 2026-10-23 夜: the OWNER's real holdings", start)]


def _ps(body):
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "t.ps1"
        script.write_text(body, encoding="utf-8-sig")
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                              capture_output=True, text=True, timeout=60).stdout.replace("\r\n", "\n")


class Scalp8Static(unittest.TestCase):
    def test_off_by_default_with_local_switch(self):
        text = _text()
        self.assertIn('$scalp8ConfigPath = Join-Path $PSScriptRoot "scalp8_config.json"', text)
        self.assertIn('[string]$cfg.schema -cne "100b-scalp8-config-v1"', text)
        self.assertIn('Write-Host "[SCALP8] OFF (no local scalp8 config or switched off)"', text)
        self.assertIn('if ($cfg.enabled -ne $true) { $script:scalp8Latched = $true; return $null }', text)
        self.assertIn("$scalp8MaxIssues = 8", text)
        self.assertFalse((ROOT / "ms2_live" / "scalp8_config.json").exists())

    def test_formulas_and_one_read_per_cycle(self):
        text = _text()
        self.assertIn("$s8TickFormula = '=RssTickList(,\"' + $s8Sym + '\",' + [string]$scalp8TickRows + ')'", text)
        self.assertIn("$scalp8TickRows = 300", text)
        for item in ("最良売気配値", "最良売気配数量", "最良買気配値", "最良買気配数量"):
            self.assertIn('("%s" + $lv)' % item, text)
        cycle = _cycle(text)
        self.assertEqual(cycle.count("Invoke-ExcelCom"), 1)
        self.assertEqual(cycle.count(".Value2"), 1)
        # no writes to the workbook inside the cycle
        self.assertNotIn("Formula", cycle)
        self.assertNotIn(".Value2 =", cycle)

    def test_record_only(self):
        text = _text()
        cycle = _cycle(text)
        for name in ("scalp8_ticks.csv", "scalp8_board.csv", "scalp8_diag.csv"):
            self.assertIn('Join-Path $dayDir "%s"' % name, cycle)
        # the recorded variables are used nowhere outside the SCALP8 blocks
        setup = text[text.index('# OWNER 2026-10-23 「Phase 2」'):text.index("# 決算・IR開示があった銘柄")]
        rest = text.replace(setup, "").replace(cycle, "")
        for var in ("$scalp8PrevKeys", "$scalp8PrevBoard", "$s8Data", "$scalp8Codes", "$scalp8Sheet", "scalp8_"):
            self.assertNotIn(var, rest)
        for gate in ("speak", "Speak", "signal", "brain", "jsonPath"):
            self.assertNotIn(gate, cycle)

    def test_failure_suspends_only_this_recorder(self):
        cycle = _cycle(_text())
        self.assertIn('Write-Host "[SCALP8] WARN / READ FAILED - recorder suspended, Collector continues"', cycle)
        self.assertNotIn("throw", cycle)

    def test_failure_is_logged_with_its_reason_and_retried(self):
        # OWNER 2026-10-27 「SCALP8の直し」: one READ FAILED used to stop it for the whole run, with no reason kept
        text = _text()
        cycle = _cycle(text)
        self.assertIn("$scalp8FailCount = 0\n$scalp8RetryAt = [datetime]::MinValue", text.replace("\r\n", "\n"))
        self.assertIn("-and (Get-Date) -ge $scalp8RetryAt) {", cycle)
        self.assertIn('$s8ErrCsv = Join-Path $dayDir "scalp8_errors.csv"', cycle)
        self.assertIn("$s8Wait = [Math]::Min(300, 10 * [Math]::Pow(2, [Math]::Min(5, $scalp8FailCount - 1)))", cycle)
        # OWNER 2026-10-27: the setup itself failed at the 18:36 start with no reason; it is retried from the cycle
        self.assertIn("function Initialize-Scalp8 {", text)
        self.assertIn("$scalp8SetupTries -lt 30 -and (Get-Date) -ge $scalp8SetupRetryAt", cycle)
        self.assertIn('",setup" + [string]$scalp8SetupTries + ",60," + $scalp8SetupError', cycle)
        self.assertIn("$script:scalp8SetupRetryAt = (Get-Date).AddSeconds(60)", text)
        catch = cycle[cycle.index("$scalp8FailCount++"):]
        self.assertNotIn("$scalp8Ready = $false", catch)
        self.assertNotIn("$scalp8Sheet = $null", catch)


@unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
class Scalp8Functions(unittest.TestCase):
    def test_new_ticks(self):
        fn = _function(_text(), "Get-Scalp8NewTicks")
        out = _ps(fn + r'''
function Show($r) { Write-Output ("N=" + (@($r.New) -join ";") + " G=" + $r.Gap) }
Show (Get-Scalp8NewTicks $null @("a","b","c"))
Show (Get-Scalp8NewTicks @("a","b","c") @("a","b","c"))
Show (Get-Scalp8NewTicks @("a","b","c") @("x","y","a","b","c"))
Show (Get-Scalp8NewTicks @("a","b","c") @("a","a","b","c"))
Show (Get-Scalp8NewTicks @("a","b","c") @("x","y","z"))
Show (Get-Scalp8NewTicks @("a","b","c") @())
Show (Get-Scalp8NewTicks @("p","q","r","s") @("n","p","q","r"))
''')
        self.assertEqual(out.split("\n")[:7], [
            "N=a;b;c G=False",   # first read: everything, no gap
            "N= G=False",        # nothing new
            "N=x;y G=False",     # two new prints on top
            "N=a G=False",       # a repeated identical print is kept
            "N=x;y;z G=True",    # previous window gone: all, gap suspected
            "N= G=False",
            "N=n G=False",       # oldest print dropped off the bottom
        ])

    def test_side_and_code(self):
        text = _text()
        out = _ps(_function(text, "Get-Scalp8Side") + _function(text, "Test-Scalp8Code") + r'''
Write-Output (Get-Scalp8Side 101 ([double]100) ([double]101))
Write-Output (Get-Scalp8Side 100 ([double]100) ([double]101))
Write-Output (Get-Scalp8Side 100.5 ([double]100) ([double]101))
Write-Output (Get-Scalp8Side 100 "" "")
foreach ($c in "285A","6857","464A","285a","28A","285A.T","A285") { Write-Output ($c + "=" + (Test-Scalp8Code $c)) }
''')
        self.assertEqual(out.split("\n")[:11], ["BUY", "SELL", "MID", "MID", "285A=True", "6857=True", "464A=True",
                                                "285a=False", "28A=False", "285A.T=False", "A285=False"])

    def test_config(self):
        text = _text()
        fn = _function(text, "Test-Scalp8Code") + _function(text, "Get-Scalp8Config")
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "scalp8_config.json"
            cases = [
                None,
                {"schema": "100b-scalp8-config-v1", "enabled": True, "codes": ["285a", "6857", "6857", "bad"]},
                {"schema": "100b-scalp8-config-v1", "enabled": True, "codes": [str(1000 + i) for i in range(9)]},
                {"schema": "other", "enabled": True, "codes": ["285A"]},
                {"schema": "100b-scalp8-config-v1", "enabled": False, "codes": ["285A"]},
                {"schema": "100b-scalp8-config-v1", "enabled": True, "codes": ["285A"]},   # after the off switch: latched
            ]
            outs = []
            for case in cases:
                if case is None:
                    if cfg.exists():
                        cfg.unlink()
                else:
                    cfg.write_text(json.dumps(case), encoding="utf-8")
                outs.append(case)
            body = fn.replace("function Get-Scalp8Config", "function Get-Scalp8Config") + "\n"
            body = ("$scalp8ConfigPath = '%s'\n$scalp8Latched = $false\n$scalp8MaxIssues = 8\n" % cfg) + body
            steps = []
            for case in cases:
                if case is None:
                    steps.append("Remove-Item -LiteralPath $scalp8ConfigPath -ErrorAction SilentlyContinue")
                else:
                    steps.append("[IO.File]::WriteAllText($scalp8ConfigPath, '%s')" % json.dumps(case, ensure_ascii=False))
                steps.append("$r = Get-Scalp8Config; if ($null -eq $r) { Write-Output 'OFF' } else { Write-Output ('ON ' + ($r.Codes -join ',')) }")
            out = _ps(body + "\n".join(steps) + "\n")
        self.assertEqual(out.split("\n")[:6], ["OFF", "ON 285A,6857", "OFF", "OFF", "OFF", "OFF"])


if __name__ == "__main__":
    unittest.main()
