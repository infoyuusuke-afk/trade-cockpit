"""OWNER 2026-10-29 「寄りが遅れた銘柄は、寄ってから15分で高値・安値を作る」."""
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")


class Or15LateOpen(unittest.TestCase):
    def test_or15_window_starts_at_the_first_trade_for_a_late_open(self):
        b = SRC.split("# OWNER 2026-10-29 「寄りが遅れた銘柄は", 1)[1].split("$inPreopen=", 1)[0]
        self.assertIn('$tradedYet=(($null -ne $volume -and $volume -gt 0) -or ($null -ne $openPrice -and $openPrice -gt 0))', b)
        self.assertIn('elseif($orWaiting.ContainsKey($ticker) -and $clock -ge [TimeSpan]::Parse("09:01:00")){$orStart[$ticker]=$clock}', b)
        self.assertIn('else{$orStart[$ticker]=[TimeSpan]::Parse("09:00:00")}', b)
        self.assertIn("$inOr=($null -ne $orBegin -and $clock -ge $orBegin -and $clock -lt $orBegin.Add([TimeSpan]::FromMinutes(15)))", b)
        self.assertIn("$afterOr=($null -ne $orBegin -and $clock -ge $orBegin.Add([TimeSpan]::FromMinutes(15)));", SRC)
        self.assertNotIn('$afterOr=($clock -ge [TimeSpan]::Parse("09:15:00"));', SRC)

    def test_or_start_state_resets_every_day(self):
        self.assertIn("$orHigh=@{}; $orLow=@{}; $orStart=@{}; $orWaiting=@{};", SRC)

    def test_volume_and_open_are_read_before_the_window(self):
        self.assertLess(SRC.index("$volume=Get-SafeNumber (Get-TableValue $values $r 5)"), SRC.index("$tradedYet="))
        self.assertLess(SRC.index("$openPrice=Get-SafeNumber (Get-TableValue $values $r 31)"), SRC.index("$tradedYet="))


if __name__ == "__main__":
    unittest.main()
