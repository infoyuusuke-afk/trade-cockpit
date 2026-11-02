"""OWNER 2026-11-02 「SCALP8の8銘柄で、下で大口が吸収している時に音声で知らせて。約定で確かめた時だけ、1銘柄5分に1回、
未検証と言って、鳴った時刻は記録して」."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
START = "# OWNER 2026-11-02 「SCALP8の8銘柄で、下で大口が吸収している時"
FUNCS = SRC[SRC.index(START):SRC.index("$scalp8Sheet = $null")]


class AbsorbVoice(unittest.TestCase):
    def test_voice_says_unverified_and_every_ring_is_logged(self):
        self.assertIn('"、下で大口が売りを吸収しています。約定で確認しました。未検証です。"', SRC)
        self.assertIn('$absorbCsv = Join-Path $dayDir "absorb_voice.csv"', SRC)
        self.assertIn("rang_at,ticker,name,sold_into_bid_60s,median_volume_per_minute,times,bid_at_start,last_price,voice", SRC)

    def test_judged_from_prints_only_and_reset_every_day(self):
        self.assertIn("if ($NowSec - $State.LastVoiceSec -lt 300) { return $null }", FUNCS)
        self.assertIn('if ($x.Side -eq "SELL") { $sold += $x.Vol }', FUNCS)
        self.assertNotIn("bid_qty", FUNCS)
        self.assertIn("$script:s8Absorb=@{};", SRC)
        self.assertIn("if ($tSec -ge 32400 -and $tSec -le $capSec + 4) {", SRC)

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "no PowerShell")
    def test_rings_once_per_five_minutes_only_when_the_selling_is_absorbed(self):
        script = FUNCS + r'''
$st = [pscustomobject]@{ Prints = [Collections.ArrayList]::new(); Minutes = @{}; LastVoiceSec = -100000; Seq = 0; UsedSeq = 0; Fresh = $false }
# 12 quiet minutes from 10:00 (100 shares a minute)
for ($m = 0; $m -lt 12; $m++) { Add-Scalp8AbsorbPrint $st (36000 + 60 * $m) 1000 100 "BUY" 999 }
$out = @()
# 10:12: 600 shares sold into the bid at 1000, the price stays at 1000 -> absorbed
Add-Scalp8AbsorbPrint $st 36725 1000 600 "SELL" 1000
$h = Get-Scalp8AbsorbHit $st 36726 4.0; $out += $(if ($h) { "hit:" + $h.X } else { "none" })
# again 1 minute later: inside the 5 minutes -> silent
Add-Scalp8AbsorbPrint $st 36785 1000 600 "SELL" 1000
$h = Get-Scalp8AbsorbHit $st 36786 4.0; $out += $(if ($h) { "hit" } else { "none" })
$st2 = [pscustomobject]@{ Prints = [Collections.ArrayList]::new(); Minutes = @{}; LastVoiceSec = -100000; Seq = 0; UsedSeq = 0; Fresh = $false }
for ($m = 0; $m -lt 12; $m++) { Add-Scalp8AbsorbPrint $st2 (36000 + 60 * $m) 1000 100 "BUY" 999 }
# the selling breaks the bid: 1000 -> 990 -> not absorbed
Add-Scalp8AbsorbPrint $st2 36725 1000 300 "SELL" 1000
Add-Scalp8AbsorbPrint $st2 36730 990 300 "SELL" 995
$h = Get-Scalp8AbsorbHit $st2 36731 4.0; $out += $(if ($h) { "hit" } else { "none" })
# lunch: no voice
$st3 = [pscustomobject]@{ Prints = [Collections.ArrayList]::new(); Minutes = @{}; LastVoiceSec = -100000; Seq = 0; UsedSeq = 0; Fresh = $false }
for ($m = 0; $m -lt 12; $m++) { Add-Scalp8AbsorbPrint $st3 (42000 + 60 * $m) 1000 100 "BUY" 999 }
Add-Scalp8AbsorbPrint $st3 42725 1000 600 "SELL" 1000
$h = Get-Scalp8AbsorbHit $st3 42726 4.0; $out += $(if ($h) { "hit" } else { "none" })
[IO.File]::WriteAllText($args[0], ($out -join ","))
'''
        with tempfile.TemporaryDirectory() as d:
            ps = Path(d) / "t.ps1"
            out = Path(d) / "o.txt"
            ps.write_text(script, encoding="utf-8-sig")
            exe = shutil.which("pwsh") or shutil.which("powershell")
            subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), str(out)], capture_output=True, timeout=120)
            got = out.read_text(encoding="utf-8")
        self.assertEqual(got, "hit:6,none,none,none")

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "no PowerShell")
    def test_only_new_prints_within_60s_and_the_same_prints_never_ring_twice(self):
        # OWNER 2026-11-02 「直近60秒に新しい約定がある時だけ判断して、同じ約定で2回鳴らさないように直して、テストも入れて」
        script = FUNCS + r'''
function New-St { [pscustomobject]@{ Prints = [Collections.ArrayList]::new(); Minutes = @{}; LastVoiceSec = -100000; Seq = 0; UsedSeq = 0; Fresh = $false } }
$out = @()
$st = New-St
for ($m = 0; $m -lt 12; $m++) { Add-Scalp8AbsorbPrint $st (36000 + 60 * $m) 1000 100 "BUY" 999 }
Add-Scalp8AbsorbPrint $st 36725 1000 600 "SELL" 1000
# a. no new print since the last check: the second check stays silent even after 5 minutes
$h = Get-Scalp8AbsorbHit $st 36726 4.0; $out += $(if ($h) { "hit" } else { "none" })
$st.LastVoiceSec = -100000
$h = Get-Scalp8AbsorbHit $st 37100 4.0; $out += $(if ($h) { "hit" } else { "none" })
# b. a small new print 6 minutes later inside 60 s of the old big selling? no: the big selling is older than 60 s
Add-Scalp8AbsorbPrint $st 37090 1000 10 "BUY" 1000
$h = Get-Scalp8AbsorbHit $st 37091 4.0; $out += $(if ($h) { "hit" } else { "none" })
# c. the same prints are never counted twice: a new print right after a voice (5 minutes passed) does not re-use them
$st2 = New-St
for ($m = 0; $m -lt 12; $m++) { Add-Scalp8AbsorbPrint $st2 (36000 + 60 * $m) 1000 100 "BUY" 999 }
Add-Scalp8AbsorbPrint $st2 36725 1000 600 "SELL" 1000
$h = Get-Scalp8AbsorbHit $st2 36726 4.0; $out += $(if ($h) { "hit" } else { "none" })
$st2.LastVoiceSec = -100000
Add-Scalp8AbsorbPrint $st2 36730 1000 10 "SELL" 1000
$h = Get-Scalp8AbsorbHit $st2 36731 4.0; $out += $(if ($h) { "hit" } else { "none" })
# d. the newest print is older than 60 s at the check: silent
$st3 = New-St
for ($m = 0; $m -lt 12; $m++) { Add-Scalp8AbsorbPrint $st3 (36000 + 60 * $m) 1000 100 "BUY" 999 }
Add-Scalp8AbsorbPrint $st3 36725 1000 600 "SELL" 1000
$h = Get-Scalp8AbsorbHit $st3 36800 4.0; $out += $(if ($h) { "hit" } else { "none" })
[IO.File]::WriteAllText($args[0], ($out -join ","))
'''
        with tempfile.TemporaryDirectory() as d:
            ps = Path(d) / "t.ps1"
            out = Path(d) / "o.txt"
            ps.write_text(script, encoding="utf-8-sig")
            exe = shutil.which("pwsh") or shutil.which("powershell")
            subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), str(out)], capture_output=True, timeout=120)
            got = out.read_text(encoding="utf-8")
        self.assertEqual(got, "hit,none,none,hit,none,none")


if __name__ == "__main__":
    unittest.main()
