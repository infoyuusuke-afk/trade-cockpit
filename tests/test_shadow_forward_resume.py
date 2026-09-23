import sys
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import shadow_forward_capture as capture
import shadow_forward_resume as resume

T0 = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)


def start():
    return capture.append_capture_event(
        [], event_type="CAPTURE_START", capture_now=T0,
        observation_now=T0, payload={"symbol": "285A"})["events"]


class ResumeTests(unittest.TestCase):
    def test_verified_nonfinal_prefix_resumes(self):
        events = start()
        self.assertEqual(resume.resume_status(events, restart_now=T0 + timedelta(seconds=1)),
                         "RESUME_PREFIX_VERIFIED")
        self.assertIs(resume.require_resumable_prefix(
            events, restart_now=T0 + timedelta(seconds=1)), events)

    def test_finalized_chain_cannot_reopen(self):
        events = start()
        events = capture.append_capture_event(
            events, event_type="FINALIZE", capture_now=T0 + timedelta(seconds=1),
            observation_now=T0, payload={})["events"]
        self.assertEqual(resume.resume_status(events, restart_now=T0 + timedelta(seconds=2)),
                         "BLOCK_FINALIZED_TERMINAL")

    def test_hash_corruption_blocks_without_repair(self):
        events = deepcopy(start())
        original = deepcopy(events)
        events[0]["payload"]["data"]["symbol"] = "FAKE"
        self.assertEqual(resume.resume_status(events, restart_now=T0 + timedelta(seconds=1)),
                         "BLOCK_PREFIX_CORRUPT")
        self.assertEqual(events[0]["event_hash"], original[0]["event_hash"])

    def test_future_prefix_blocks(self):
        events = start()
        self.assertEqual(resume.resume_status(events, restart_now=T0 - timedelta(seconds=1)),
                         "BLOCK_PREFIX_FUTURE")

    def test_empty_state_not_guessed_as_resume(self):
        self.assertEqual(resume.resume_status([], restart_now=T0),
                         "BLOCK_NO_RESUMABLE_PREFIX")


if __name__ == "__main__":
    unittest.main()
