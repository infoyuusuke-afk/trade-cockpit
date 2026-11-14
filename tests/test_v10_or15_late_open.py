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


class Or15RestoreOnRestart(unittest.TestCase):
    """OWNER 2026-10-29 「場中に起動し直しても、その日の記録から9:00〜9:15の高値・安値を読み直して、OR15を作り直す」."""

    def test_restore_runs_once_a_day_after_0900_from_ticks_and_snapshots(self):
        b = SRC.split("if ($orRestoredDay -ne $activeDay) {", 1)[1].split("        }\n", 1)[0]
        self.assertIn('if ($now.TimeOfDay -ge [TimeSpan]::Parse("09:00:00")) {', b)
        self.assertIn("Restore-Or15FromTicks $tickCsv $orHigh $orLow $orStart $snapshotCsv", b)
        self.assertIn("restore failed - Collector continues", b)
        self.assertLess(SRC.index("$tickCsv = Join-Path $dayDir"), SRC.index("if ($orRestoredDay -ne $activeDay)"))

    def test_restore_uses_the_same_windows_as_the_live_loop(self):
        f = SRC.split("function Restore-Or15FromTicks", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('$st = if ($t -lt "09:01:00" -or -not $sawEarly) { "09:00:00" } else { $t }', f)
        self.assertIn('[TimeSpan]::FromMinutes(15)', f)
        self.assertIn('-ge "11:30") { break }', f)
        self.assertIn("[IO.FileShare]::ReadWrite", f)
        self.assertIn('.TotalSeconds -ge 5) { continue }', f)

    @unittest.skipUnless(__import__("shutil").which("pwsh") or __import__("shutil").which("powershell"), "no PowerShell")
    def test_restore_on_sample_records(self):
        import shutil, subprocess, tempfile
        fn = "function Restore-Or15FromTicks" + SRC.split("function Restore-Or15FromTicks", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ticks = ['captured_at,ticker,name,exchange_time,price,direction_estimate,bid,ask,note']
            # OWNER 2026-10-29 「記録した時刻より後の時刻の歩み値（前日の値段）は外して」「5秒以上後のものだけに」: the 999 and 90 prints are
            # stamped 5 s or more after their capture (dropped); the 95 print is 4 s after (today's, kept)
            rows = [("09:00:01", "1111.T", "15:24:59", 999), ("09:00:01", "3333.T", "15:29:00", 999),
                    ("09:00:04", "1111.T", "09:00:02", 100), ("09:00:05", "3333.T", "09:00:05", 300),
                    ("09:00:06", "4444.T", "15:28:00", 999), ("09:00:07", "4444.T", "09:00:07", 400),
                    ("09:00:08", "5555.T", "15:27:00", 999), ("09:03:00", "3333.T", "15:29:00", 999), ("09:05:00", "1111.T", "09:04:59", 104),
                    ("09:06:00", "1111.T", "09:06:04", 95), ("09:07:00", "1111.T", "09:07:05", 90),
                    ("09:07:00", "2222.T", "09:06:02", 500), ("09:14:00", "1111.T", "09:13:59", 97),
                    ("09:16:00", "1111.T", "09:15:30", 120), ("09:20:00", "2222.T", "09:20:00", 520),
                    ("09:22:00", "2222.T", "09:21:30", 480), ("11:31:00", "1111.T", "11:30:59", 50)]
            for c, k, t, p in rows:
                ticks.append('"2026-10-29 %s.000","%s","n","%s","%s","UNKNOWN","0","0","x"' % (c, k, t, p))
            (d / "ticks.csv").write_text("\n".join(ticks) + "\n", encoding="utf-8-sig")
            snap = ['captured_at,ticker,name,price,volume,vwap,bid,ask,bid_qty,ask_qty,market_sell,market_buy,over,under',
                    '"2026-10-29 09:10:00","1111.T","n","106","1","0","0","0","0","0","0","0","0","0"']
            (d / "snap.csv").write_text("\n".join(snap) + "\n", encoding="utf-8-sig")
            ps = d / "t.ps1"
            ps.write_text(fn + '$h=@{};$l=@{};$s=@{}\n$n=Restore-Or15FromTicks "%s" $h $l $s "%s"\n'
                          '"$n|$($h["1111.T"])|$($l["1111.T"])|$($s["1111.T"])|$($h["2222.T"])|$($l["2222.T"])|$($s["2222.T"])|$($h["3333.T"])|$($l["3333.T"])|$($s["3333.T"])|$($s["4444.T"])|$($h["4444.T"])|[$($s["5555.T"])]"\n'
                          % (d / "ticks.csv", d / "snap.csv"), encoding="utf-8-sig")
            exe = shutil.which("pwsh") or shutil.which("powershell")
            out = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)],
                                 capture_output=True, text=True, timeout=120).stdout.strip().splitlines()[-1]
        self.assertEqual(out, "4|106|95|09:00:00|520|500|09:06:02|300|300|09:00:00|09:00:00|400|[]")
