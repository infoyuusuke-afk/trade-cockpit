"""OWNER 2026-11-07: when the cash list is not read, 両建て is not decided: the screen says so and the stop-loss voice stays silent.
Also the first read at start uses the short wait, and switching the config off clears the warning seconds and the flag."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AccountCashUnread(unittest.TestCase):
    def setUp(self):
        self.collector = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        self.page = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_voice_needs_the_cash_list(self):
        self.assertIn("if ($slInSession -and $null -ne $rpCash -and", self.collector)

    def test_first_read_uses_the_short_wait(self):
        self.assertIn("$realPosSheet = Initialize-RealPosSheet -Retries 8", self.collector)
        self.assertNotIn("$realPosSheet = Initialize-RealPosSheet\n", self.collector.replace("\r\n", "\n"))

    def test_switching_off_clears_the_warning(self):
        self.assertIn("if ($realPosSetupFailed -and $script:realPosLatched) { $realPosSetupFailed = $false }", self.collector)
        self.assertIn("$accountReadFailSeconds = $(if (($realPosReady -or $realPosSetupFailed) -and $null -ne (Get-RealPosConfig)) {", self.collector)

    def test_a_failed_naming_leaves_no_empty_sheet(self):
        self.assertIn("$sheet.Delete()", self.collector)
        self.assertIn("$xl.DisplayAlerts = $false", self.collector)   # no dialog can hold Excel

    def test_a_long_unread_cash_list_is_heard(self):
        self.assertIn('Invoke-SerializedSpeak $speaker "現物が読めていません"', self.collector)
        script = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("一覧の一部が読めていません", script)

    def test_a_loop_without_the_field_keeps_the_red_band(self):
        self.assertIn("if(Number.isFinite(diag.account_read_fail_seconds))window.cockpitAccountFailSeconds=", self.page)

    def test_screen_says_the_cash_list_is_not_read(self):
        script = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn('cashRead:acct.cash_state==="OK"', script)
        self.assertIn("両建て：現物が読めていない", self.page)
        self.assertIn('g.cashRead === false ? "<div class=\'ob-ng\'>両建て：現物が読めていない</div>"', self.page)   # the order card too
        self.assertIn("現物は読めていないので入っていません", script)
        self.assertIn("（現物が読めていない・声なし）", self.page)
        self.assertIn("g.cashRead===false?'読めません':yen(g.cash)", self.page)


if __name__ == "__main__":
    unittest.main()
