"""OWNER 2026-11-10 「OR15とサインにきのうの値の繰り返しを使わない」: on 11/10 MS2 stopped from 06:03 to about 09:30; the sheet kept
yesterday's last price and trades, they became today's OR15, and the 34 signals after 09:31 were priced from them (none filled).
Synthetic checks only: no MS2, no orders."""
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


def _function():
    t = _text()
    start = t.index("function Test-QuoteFromToday(")
    return t[start:t.index("\n}\n", start) + 3]


class StaleToday(unittest.TestCase):
    def test_rule(self):
        f = _function()
        self.assertIn('if ([string]::IsNullOrWhiteSpace($TimeText)) { return $false }', f)
        self.assertIn('if ($q -lt [TimeSpan]::Parse("08:00:00")) { return $false }', f)
        self.assertIn("if ($q -gt $Clock.Add([TimeSpan]::FromMinutes(2))) { return $false }", f)

    def test_gates(self):
        t = _text()
        self.assertIn('$staleToday=($clock -ge [TimeSpan]::Parse("09:00:00") -and -not (Test-QuoteFromToday (Get-TimeText (Get-TableValue $values $r 2)) $clock))', t)
        for gate in ("if ($inOr -and -not $staleToday) {", "if ($inOr5 -and -not $staleToday) {",
                     'if ($clock -ge [TimeSpan]::Parse("09:00:00") -and $clock -le [TimeSpan]::Parse("15:30:00") -and -not $staleToday) {',
                     "if (-not $staleToday) {[void]$history[$ticker].Add(",
                     'elseif ($inSession -and $staleToday) {$signal="値が今日のものでない";$strategy="きのうの値の繰り返し・サインなし"}',
                     "if (-not (Test-QuoteFromToday $tickTime $clock)) {continue}"):
            self.assertIn(gate, t)
        # audit 32e1ad2: a row that is not today's has not opened yet, so OR15 starts at its first price of today (like a late open)
        self.assertIn("$tradedYet=(($null -ne $volume -and $volume -gt 0) -or ($null -ne $openPrice -and $openPrice -gt 0)) -and (Test-QuoteFromToday (Get-TimeText (Get-TableValue $values $r 2)) $clock)", t)
        # the stale gate comes before every signal branch of the session
        self.assertLess(t.index('elseif ($inSession -and $staleToday)'), t.index('elseif ($inSession -and $whipsaw)'))
        # the minute bar is not touched by a stale price
        bar = t[t.index('$building=$currentMinuteBars[$ticker]'):t.index('$crosses=0; $buyFlow=0')]
        self.assertTrue(bar.split("\n")[1].strip().startswith("if (-not $staleToday) {"))
        self.assertIn("$building.Volume=[double]$building.Volume+[double]$volumeDelta\n            }", bar)

    @unittest.skipUnless(WINDOWS, "PowerShell only")
    def test_function_behaviour(self):
        cases = [("15:30:00", "09:05:00", False),   # yesterday's close seen at 09:05 (the 11/10 morning)
                 ("15:24:59", "09:31:00", False),   # yesterday's trade in the 歩み値 window
                 ("09:31:27", "09:31:30", True),
                 ("09:32:30", "09:31:30", True),    # two minutes of clock slack
                 ("09:34:00", "09:31:30", False),
                 ("07:59:59", "09:10:00", False),
                 ("", "10:00:00", False),
                 ("abc", "10:00:00", False),
                 ("11:29:58", "12:10:00", True),    # lunch: the morning's last trade is today's
                 ("15:30:00", "15:35:00", True)]
        lines = [_function()]
        for q, c, _ in cases:
            lines.append("[Console]::WriteLine((Test-QuoteFromToday '%s' ([TimeSpan]::Parse('%s'))))" % (q, c))
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "h.ps1"
            h.write_text("\n".join(lines), encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h)],
                                 capture_output=True, text=True, timeout=60).stdout.split()
        self.assertEqual(out, [str(x[2]) for x in cases])


if __name__ == "__main__":
    unittest.main()
