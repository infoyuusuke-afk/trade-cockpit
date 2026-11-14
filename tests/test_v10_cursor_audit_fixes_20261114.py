"""OWNER 2026-11-14 「Cursor監査の不具合7つを直す版」: ① the stop-loss guard no longer fails the account read, ⑦ no Enter wait in the Controller."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COL = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
CTL = (ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")


def code_lines(text):
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


class StopLossGuard(unittest.TestCase):
    def test_no_measure_object_on_ordered_rows(self):
        # 11/13: Measure-Object -Property pnl on [ordered] rows threw PSArgumentException 503 times (Windows PowerShell 5.1)
        self.assertNotIn("Measure-Object -Property pnl", COL)
        self.assertIn("$slTotal = Get-GuardPnlSum $slPlain", COL)
        i = COL.index("function Get-GuardPnlSum($Rows) {")
        fn = COL[i:COL.index("\n}\n", i)]
        self.assertIn('$v = $x["pnl"]', fn)
        self.assertNotIn("Measure-Object", fn)

    def test_guard_error_never_turns_a_read_into_a_failure(self):
        i = COL.index("Write-AtomicUtf8 $realPosFile ($rpView | ConvertTo-Json -Depth 5)")
        block = COL[i:COL.index("if ($rpFail) {", i)]
        # the success bookkeeping comes first, then the guard in its own try with its own catch
        self.assertLess(block.index("$realPosFailCount = 0"), block.index("                try {\n"))
        self.assertIn('Write-GuardVoiceLog $dayDir "見張りの計算エラー"', block)
        self.assertLess(block.index('Write-GuardVoiceLog $dayDir "見張りの計算エラー"'), block.index("            } catch {\n                $realPosSheet = $null"))

    def test_each_guard_voice_is_logged_with_time(self):
        for kind in ("損切り", "現物が読めていません", "口座が読めていません"):
            i = COL.index('Invoke-SerializedSpeak $speaker "%s"' % kind)
            self.assertIn('Write-GuardVoiceLog $dayDir "%s"' % kind, COL[i:i + 400])
        i = COL.index("function Write-GuardVoiceLog(")
        fn = COL[i:COL.index("\n}\n", i)]
        self.assertIn('"voice_guard.csv"', fn)
        self.assertIn('ToString("yyyy-MM-dd HH:mm:ss.fff")', fn)
        self.assertIn("catch { }", fn)   # never throws
        self.assertNotIn("pnl", fn)      # no amounts are written
        self.assertIn("$script:lastSpeakOk = [bool]$ok", COL)

    def test_one_bad_row_does_not_lose_the_list(self):
        i = COL.index("$rpBadRows = 0")
        block = COL[i:COL.index("$rpView = [ordered]@{", i)]
        self.assertEqual(block.count("catch { $rpBadRows++ }"), 3)
        self.assertIn("bad_rows = $rpBadRows", COL)

    def test_rules_of_the_voice_are_unchanged(self):
        self.assertIn("$slPlain.Count -gt 0 -and ($slOne -or $slTotal -le -10000)", COL)
        self.assertIn("$slInSession -and $null -ne $rpCash", COL)
        self.assertIn("real_submit_allowed = $false", COL)

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "PowerShell not installed")
    def test_sum_runs(self):
        i = COL.index("function Get-GuardPnlSum($Rows) {")
        fn = COL[i:COL.index("\n}\n", i) + 3]
        script = fn + '\n$r=@([ordered]@{code="1";pnl=-5000.0},[ordered]@{code="2";pnl=-7000.0},[ordered]@{code="3";pnl=$null})\n' \
                      '$ErrorActionPreference="Stop"\nWrite-Output ("SUM=" + (Get-GuardPnlSum $r) + " EMPTY=" + (Get-GuardPnlSum @()))\n'
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.ps1"
            p.write_text(script, encoding="utf-8-sig")
            exe = shutil.which("pwsh") or shutil.which("powershell")
            out = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(p)], capture_output=True, text=True, timeout=120)
        self.assertIn("SUM=-12000 EMPTY=0", out.stdout, out.stderr)


class NoEnterWait(unittest.TestCase):
    def test_controller_never_waits_for_enter(self):
        # RUN_AI_COCKPIT_V10.ps1 (the OWNER's own visible update window) is pinned unchanged by full-source-parity and keeps its Enter
        for name, text in (("controller", CTL),):
            self.assertFalse([ln for ln in code_lines(text) if re.search(r"\bRead-Host\b", ln)], name)
            self.assertIn("function Wait-CloseOrTimeout([int]$Seconds = 120) {", text)
            self.assertIn("} catch { }", text[text.index("function Wait-CloseOrTimeout"):])
        self.assertIn('Join-Path $LogDir "controller_stopped_on_error.log"', CTL)
        self.assertIn("Wait-CloseOrTimeout 120\n    [Environment]::Exit(1)", CTL.replace("\r\n", "\n"))

    def test_controller_stays_ascii(self):
        raw = (ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").read_bytes()
        self.assertTrue(all(b < 128 for b in raw))


if __name__ == "__main__":
    unittest.main()
