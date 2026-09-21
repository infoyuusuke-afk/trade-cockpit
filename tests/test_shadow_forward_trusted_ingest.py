import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import shadow_forward_trusted_ingest as ingest


class TrustedIngestTests(unittest.TestCase):
    def test_runner_clock_becomes_capture_time(self):
        receipt = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)
        observation = datetime(2026, 9, 22, 2, 59, tzinfo=timezone.utc)
        out = ingest.ingest([], event_type="CAPTURE_START",
                            observation_now=observation, payload={"symbol": "285A"},
                            clock=lambda: receipt)
        self.assertEqual(out["runner_received_at"], receipt)
        self.assertEqual(out["events"][0]["captured_at"], receipt)

    def test_caller_cannot_override_capture_time(self):
        receipt = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)
        observation = datetime(2026, 9, 22, 2, 59, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            ingest.ingest([], event_type="CAPTURE_START",
                          observation_now=observation,
                          payload={"capture_now": "2020-01-01T00:00:00+00:00"},
                          clock=lambda: receipt)

    def test_future_observation_rejected(self):
        receipt = datetime(2026, 9, 22, 3, 0, tzinfo=timezone.utc)
        future = datetime(2026, 9, 22, 3, 1, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            ingest.ingest([], event_type="CAPTURE_START",
                          observation_now=future, payload={}, clock=lambda: receipt)

    def test_naive_runner_clock_rejected(self):
        with self.assertRaises(ValueError):
            ingest.ingest([], event_type="CAPTURE_START",
                          observation_now=datetime(2026, 9, 22, 2, 0, tzinfo=timezone.utc),
                          payload={}, clock=lambda: datetime(2026, 9, 22, 3, 0))


if __name__ == "__main__":
    unittest.main()
