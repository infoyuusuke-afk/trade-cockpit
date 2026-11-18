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

PROBE = (ROOT / "downloads" / "EXCEL_IDENTITY_PROBE_V10.ps1").read_text(encoding="ascii")


class ExcelWindowWait(unittest.TestCase):
    def test_probe_is_ascii(self):
        (ROOT / "downloads" / "EXCEL_IDENTITY_PROBE_V10.ps1").read_bytes().decode("ascii")

    def test_hwnd_not_ready_waits_a_bounded_time_then_fails_closed(self):
        self.assertIn("$hwndNotReadyGraceSeconds = 15", PROBE)
        i = PROBE.index('$last.last_error = "HWND_PROCESS_NOT_READY"')
        block = PROBE[i:i + 1400]
        self.assertIn('$disposition = "next"', block)                     # waits and checks again
        self.assertIn('$disposition = "fail"', block)                     # after the grace: the same stop as before
        self.assertIn('$last.code = "EXCEL_WORKBOOK_OPEN_BLOCKED"', block)
        self.assertIn("-lt $hwndNotReadyGraceSeconds", block)
        self.assertIn("Nothing was adopted", block)
        # the window still has to pass every check: PID, session, command line, parent, same file
        for check in ('"PID_MISMATCH"', '"SESSION_MISMATCH"', '"COMMAND_LINE_MISMATCH"', '"PARENT_MISMATCH"', '"FULL_NAME_DIFFERENT_FILE"'):
            self.assertIn(check, PROBE)
        self.assertIn("$ownerPid -ne $ExpectedExcelPid", PROBE)

    def test_budget_end_while_waiting_keeps_the_old_stop_code(self):
        tail = PROBE[PROBE.index('$last.code = "EXCEL_IDENTITY_PROBE_FAILED"\r\nif'):] if "\r\n" in PROBE else PROBE[PROBE.index('$last.code = "EXCEL_IDENTITY_PROBE_FAILED"\nif'):]
        self.assertIn('[string]$last.last_error -eq "HWND_PROCESS_NOT_READY"', tail)
        j = tail.index('"HWND_PROCESS_NOT_READY"')
        self.assertIn('$last.code = "EXCEL_WORKBOOK_OPEN_BLOCKED"', tail[j:j + 300])

    def test_other_dialog_and_mismatch_stops_are_unchanged(self):
        self.assertIn("Excel was busy in a dialog. Identity retries stopped.", PROBE)
        self.assertIn("Workbook moniker belongs to a different Excel PID. It was not adopted. Identity retries stopped.", PROBE)
        ctl = (ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('"HWND_PROCESS_NOT_READY"', ctl)                   # the controller still treats it as an open failure


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
