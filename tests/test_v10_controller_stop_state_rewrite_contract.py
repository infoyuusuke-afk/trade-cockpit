"""Source-only V10 Controller teardown state-retention contract.
Never starts Controller, Excel, MS2, workers or broker paths.
"""
from pathlib import Path
import re
import unittest

CONTROLLER = Path(__file__).resolve().parents[1] / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"


def assert_teardown_freezes_state(source: str) -> None:
    start = source.index("if ($foreignExcelNow.Count -gt 0)")
    end = source.index("# Voice backend is presentation-only", start)
    block = source[start:end]
    marker = "Stop-ManagedWorkersOnWorkbookClose $state"
    assert block.count(marker) == 2, "unexpected worker-stop path count"
    first = block.index(marker)
    assert re.search(r"(?m)^\s*Save-State \$state\s*$", block[:first]), "missing pre-teardown evidence"
    assert not re.search(r"(?m)^\s*Save-State \$state\s*$", block[first:]), "stale state rewrite after worker stop"
    assert "Test-V10WorkbookCloseTeardownComplete $state" in block
    assert "Remove-V10VerifiedShutdownState $state" in block
    assert "SAFE_STOP_VERIFY=STATE_REMOVAL_UNVERIFIED" in block


class TestControllerTeardownState(unittest.TestCase):
    def test_production_source(self):
        assert_teardown_freezes_state(CONTROLLER.read_text(encoding="utf-8-sig"))

    def test_negative_injected_post_stop_rewrite(self):
        source = CONTROLLER.read_text(encoding="utf-8-sig")
        needle = "Stop-ManagedWorkersOnWorkbookClose $state"
        bad = source.replace(needle, needle + "\n            Save-State $state", 1)
        with self.assertRaisesRegex(AssertionError, "stale state rewrite"):
            assert_teardown_freezes_state(bad)


if __name__ == "__main__":
    unittest.main()
