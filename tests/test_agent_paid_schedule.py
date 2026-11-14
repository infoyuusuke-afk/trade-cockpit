"""OWNER 2026-10-22 (audit 6339629207 item 6): weekday 08:30 / 12:15 specialist GPT runs under
a standing approval tied to one exact code version. No API call, no registration, no real
approval file in these tests."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "downloads" / "AGENT_PAID_SCHEDULED_RUN.ps1"
REGISTER = ROOT / "downloads" / "REGISTER_AGENT_PAID_SCHEDULE.ps1"


def _text(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


class ScheduledRun(unittest.TestCase):
    def test_ascii_without_bom(self):
        for path in (RUNNER, REGISTER):
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            self.assertTrue(all(b < 128 for b in raw), path.name)

    def test_gates_come_before_any_setting_or_call(self):
        text = _text(RUNNER)
        first_call = text.index("agent_sdk_evidence_bundle.py")
        for gate in ('Stop-Run "SCHEDULE_NOT_APPROVED"', 'Stop-Run "CODE_IS_NOT_THE_APPROVED_SHA"',
                     'Stop-Run "WEEKEND"', 'Stop-Run "OUTSIDE_SLOT_WINDOW"', 'Stop-Run "NO_ACTIVE_PAID_LEDGER"'):
            self.assertLess(text.index(gate), text.index('Set-Item -Path ("Env:" + $n)'), gate)
            self.assertLess(text.index(gate), first_call, gate)
        self.assertIn('@($approval.slots) -cnotcontains $Slot', text)
        self.assertIn('[ValidateSet("0830", "1215")]', text)
        self.assertIn('$runId = "sched_" + $jst.ToString("yyyyMMdd") + "_" + $Slot', text)
        self.assertIn('$env:AGENT_PAID_RUN_APPROVED_RUN_ID = $runId', text)
        self.assertIn('Remove-Item Env:AGENT_PAID_LEDGER_REGISTRY', text)

    def test_runner_never_registers_or_writes_the_approval(self):
        text = _text(RUNNER)
        for word in ("Register-ScheduledTask", "WriteAllText", "Set-Content", "Out-File"):
            self.assertNotIn(word, text)
        self.assertNotIn("--retry", text)

    def test_register_needs_this_exact_sha_and_owner_words(self):
        text = _text(REGISTER)
        self.assertIn('throw "APPROVED_SHA_IS_NOT_THIS_CHECKOUT"', text)
        self.assertIn('throw "OWNER_APPROVAL_WORDS_REQUIRED"', text)
        self.assertLess(text.index('throw "OWNER_APPROVAL_WORDS_REQUIRED"'), text.index("Register-ScheduledTask"))
        self.assertIn("-DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday", text)
        self.assertIn("-MultipleInstances IgnoreNew", text)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell 5.1 only")
    def test_without_the_standing_approval_nothing_runs(self):
        approval = Path(os.environ.get("LOCALAPPDATA", "")) / "100B_AGENT" / "paid_schedule_approval.json"
        if approval.exists():
            self.skipTest("a real standing approval exists on this machine")
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
                              "-Slot", "0830", "-RepoRoot", str(ROOT)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertIn("SCHEDULED_RUN=BLOCKED SCHEDULE_NOT_APPROVED", out.stdout)
        self.assertIn("PAID_CALL_MADE=0", out.stdout)


if __name__ == "__main__":
    unittest.main()
