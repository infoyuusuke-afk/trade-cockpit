"""OWNER 2026-11-18 「起動の確認（Excelの窓の準備を待ってからもう一度確かめる）と、ブレインの状態ファイルの書き込み
（書けない時は少し待ってもう一度）を直す版を作って。安全の確認はゆるめない。画面は変えない。注文しない」."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ai_brain_observer as obs  # noqa: E402

CTL = (ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="ascii")
PROBE = (ROOT / "downloads" / "EXCEL_IDENTITY_PROBE_V10.ps1").read_text(encoding="ascii")


class ExcelWindowWait(unittest.TestCase):
    """The wait is in the controller: the probe helper is unchanged (its exact blob stays the CI-pinned one)."""

    def _loop(self):
        i = CTL.index("$windowWaitTries = 0")
        j = CTL.index("if (-not $probe.ok) {", i)
        return CTL[i:j]

    def test_controller_is_ascii(self):
        (ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").read_bytes().decode("ascii")

    def test_only_hwnd_not_ready_is_checked_again_a_bounded_number_of_times(self):
        loop = self._loop()
        self.assertIn('[string]$probe.last_error -eq "HWND_PROCESS_NOT_READY"', loop)
        self.assertIn("-not $probe.ok", loop)
        self.assertIn("-not [bool]$probe.process_exited", loop)
        self.assertIn("$windowWaitTries -lt 2", loop)
        self.assertIn("Start-Sleep -Seconds 5", loop)
        self.assertIn("if ($launchedExcelProc.HasExited) { break }", loop)
        self.assertIn("Nothing was adopted", loop)
        # each try is the full probe for the same launched Excel PID
        self.assertIn("Invoke-ExcelIdentityProbe", loop)
        self.assertIn("-ExpectedExcelPid ([int]$launchedExcelProc.Id)", loop)
        self.assertIn("Complete-ExcelProbeResult", loop)
        for word in ("excel_pid = ", "workbook_identity_verified = $true", "Stop-Process", "Kill("):
            self.assertNotIn(word, loop)

    def test_the_stop_after_the_wait_is_unchanged(self):
        i = CTL.index("$windowWaitTries = 0")
        after = CTL[i:i + 4000]
        self.assertIn('"HWND_PROCESS_NOT_READY", "EXCEL_BUSY", "PREVIOUS_SERIOUS_ERROR_DIALOG"', after)
        self.assertIn("AI Cockpit startup failed closed", after)
        self.assertIn("Excel workbook open failed closed: ", after)

    def test_probe_helper_still_stops_on_each_mismatch(self):
        self.assertIn("Workbook moniker was found but its HWND was not the launched Excel. Identity retries stopped.", PROBE)
        self.assertIn("Workbook moniker belongs to a different Excel PID. It was not adopted. Identity retries stopped.", PROBE)
        self.assertIn("$ownerPid -ne $ExpectedExcelPid", PROBE)


class StatusWriteRetry(unittest.TestCase):
    def test_retries_permission_error_then_succeeds(self):
        calls, waits = [], []

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(5, "Access is denied")
            return None

        with mock.patch.object(obs.os, "replace", flaky):
            self.assertEqual(obs._replace_with_retry("a", "b", sleep=waits.append), 3)
        self.assertEqual(len(waits), 2)
        self.assertLessEqual(sum(waits), 1.0)

    def test_gives_up_after_the_last_try_and_raises_as_before(self):
        waits = []
        with mock.patch.object(obs.os, "replace", side_effect=PermissionError(5, "Access is denied")) as rep:
            with self.assertRaises(PermissionError):
                obs._replace_with_retry("a", "b", sleep=waits.append)
        self.assertEqual(rep.call_count, obs.STATUS_REPLACE_TRIES)
        self.assertEqual(len(waits), obs.STATUS_REPLACE_TRIES - 1)
        self.assertLessEqual(obs.STATUS_REPLACE_TRIES * obs.STATUS_REPLACE_WAIT_SECONDS * obs.STATUS_REPLACE_TRIES, 5.0)

    def test_other_errors_are_not_retried(self):
        with mock.patch.object(obs.os, "replace", side_effect=FileNotFoundError("x")) as rep:
            with self.assertRaises(FileNotFoundError):
                obs._replace_with_retry("a", "b", sleep=lambda s: None)
        self.assertEqual(rep.call_count, 1)

    def test_write_status_uses_the_retry_and_keeps_its_checks(self):
        src = (ROOT / "scripts" / "ai_brain_observer.py").read_text(encoding="utf-8")
        body = src[src.index("def write_status("):src.index("def write_status(") + 1500]
        self.assertIn("_replace_with_retry(temp, path)", body)
        self.assertNotIn("os.replace(temp, path)", body)
        for check in ("UNTRUSTED_STATUS_DESTINATION", "STATUS_PATH_NOT_CANONICAL", "STATUS_TOO_LARGE", "TEMP_STATUS_FILE_EXISTS"):
            self.assertIn(check, body)


if __name__ == "__main__":
    unittest.main()
