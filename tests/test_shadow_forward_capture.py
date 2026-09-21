import importlib.util
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import shadow_forward_capture as cap
import shadow_forward_evidence_chain as chain

JST = timezone(timedelta(hours=9))
T0 = datetime(2026, 9, 22, 9, 0, tzinfo=JST)


class CaptureStateTests(unittest.TestCase):
    def start(self):
        return cap.append_capture_event([], event_type="CAPTURE_START",
            capture_now=T0, observation_now=T0, payload={"intent_hash": "i1"})

    def test_happy_path_and_finalized_chain(self):
        a = self.start()
        b = cap.append_capture_event(a["events"], event_type="LIFECYCLE_STEP",
            capture_now=T0 + timedelta(seconds=1), observation_now=T0 + timedelta(seconds=1),
            payload={"step": "ORDER_FILL"})
        c = cap.append_capture_event(b["events"], event_type="FINALIZE",
            capture_now=T0 + timedelta(seconds=2), observation_now=T0 + timedelta(seconds=2),
            payload={"status": "FILLED"})
        self.assertEqual(c["state"], cap.FINALIZED)
        self.assertTrue(chain.verify_chain(c["events"], now=T0 + timedelta(seconds=2))["valid"])

    def test_missing_start_rejected(self):
        with self.assertRaises(ValueError):
            cap.append_capture_event([], event_type="LIFECYCLE_STEP",
                capture_now=T0, observation_now=T0, payload={})

    def test_naive_capture_rejected(self):
        with self.assertRaises(ValueError):
            cap.append_capture_event([], event_type="CAPTURE_START",
                capture_now=datetime(2026,9,22,9), observation_now=T0, payload={})

    def test_future_observation_rejected(self):
        with self.assertRaises(ValueError):
            cap.append_capture_event([], event_type="CAPTURE_START",
                capture_now=T0, observation_now=T0 + timedelta(seconds=1), payload={})

    def test_observation_before_start_rejected(self):
        a = self.start()
        with self.assertRaises(ValueError):
            cap.append_capture_event(a["events"], event_type="LIFECYCLE_STEP",
                capture_now=T0 + timedelta(seconds=1), observation_now=T0 - timedelta(seconds=1), payload={})

    def test_corrupt_prior_chain_rejected(self):
        a = self.start(); x = deepcopy(a["events"]); x[0]["payload"]["data"]["intent_hash"] = "tampered"
        with self.assertRaises(ValueError):
            cap.append_capture_event(x, event_type="LIFECYCLE_STEP",
                capture_now=T0 + timedelta(seconds=1), observation_now=T0, payload={})

    def test_unknown_prior_event_type_rejected_even_with_rehashed_event(self):
        a = self.start()
        x = deepcopy(a["events"])
        x[0]["event_type"] = "UNKNOWN_EVENT"
        x[0]["event_hash"] = chain.compute_event_hash(x[0])
        with self.assertRaises(ValueError):
            cap.append_capture_event(x, event_type="LIFECYCLE_STEP",
                capture_now=T0 + timedelta(seconds=1), observation_now=T0, payload={})

    def test_finalize_twice_rejected(self):
        a = self.start()
        b = cap.append_capture_event(a["events"], event_type="FINALIZE",
            capture_now=T0 + timedelta(seconds=1), observation_now=T0, payload={})
        with self.assertRaises(ValueError):
            cap.append_capture_event(b["events"], event_type="FINALIZE",
                capture_now=T0 + timedelta(seconds=2), observation_now=T0, payload={})

    def test_step_after_finalize_rejected(self):
        a = self.start()
        b = cap.append_capture_event(a["events"], event_type="FINALIZE",
            capture_now=T0 + timedelta(seconds=1), observation_now=T0, payload={})
        with self.assertRaises(ValueError):
            cap.append_capture_event(b["events"], event_type="LIFECYCLE_STEP",
                capture_now=T0 + timedelta(seconds=2), observation_now=T0, payload={})

    def test_reordered_prior_chain_rejected(self):
        a = self.start()
        b = cap.append_capture_event(a["events"], event_type="LIFECYCLE_STEP",
            capture_now=T0 + timedelta(seconds=1), observation_now=T0, payload={})
        x = list(reversed(b["events"]))
        with self.assertRaises(ValueError):
            cap.append_capture_event(x, event_type="FINALIZE",
                capture_now=T0 + timedelta(seconds=2), observation_now=T0, payload={})

    def test_same_input_deterministic(self):
        one = self.start(); two = self.start()
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
