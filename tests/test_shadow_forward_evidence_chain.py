import importlib.util
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("sfec", ROOT / "scripts/shadow_forward_evidence_chain.py")
sfec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sfec)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 22, 9, 0, tzinfo=JST)


def chain():
    a = sfec.make_event(event_type="CAPTURE_START", captured_at=NOW - timedelta(seconds=3),
                        payload={"intent_hash": "i1"})
    b = sfec.make_event(event_type="LIFECYCLE_STEP", captured_at=NOW - timedelta(seconds=2),
                        payload={"step": "ORDER_FILL"}, previous_hash=a["event_hash"])
    c = sfec.make_event(event_type="FINALIZE", captured_at=NOW - timedelta(seconds=1),
                        payload={"status": "FILLED"}, previous_hash=b["event_hash"])
    return [a, b, c]


class ShadowForwardEvidenceChainTests(unittest.TestCase):
    def test_valid_finalized_chain(self):
        self.assertTrue(sfec.verify_chain(chain(), now=NOW)["valid"])

    def test_payload_tamper_fails(self):
        x = deepcopy(chain()); x[1]["payload"]["step"] = "ALTERED"
        self.assertFalse(sfec.verify_chain(x, now=NOW)["valid"])

    def test_event_deletion_fails(self):
        x = chain(); del x[1]
        self.assertFalse(sfec.verify_chain(x, now=NOW)["valid"])

    def test_event_reorder_fails(self):
        x = chain(); x[0], x[1] = x[1], x[0]
        self.assertFalse(sfec.verify_chain(x, now=NOW)["valid"])

    def test_unfinalized_chain_fails(self):
        self.assertFalse(sfec.verify_chain(chain()[:-1], now=NOW)["valid"])

    def test_future_event_fails(self):
        x = chain()
        x[1] = sfec.make_event(event_type="LIFECYCLE_STEP", captured_at=NOW + timedelta(seconds=1),
                               payload={"step": "ORDER_FILL"}, previous_hash=x[0]["event_hash"])
        x[2] = sfec.make_event(event_type="FINALIZE", captured_at=NOW + timedelta(seconds=2),
                               payload={"status": "FILLED"}, previous_hash=x[1]["event_hash"])
        self.assertFalse(sfec.verify_chain(x, now=NOW)["valid"])

    def test_non_monotonic_time_fails(self):
        x = chain()
        x[1] = sfec.make_event(event_type="LIFECYCLE_STEP", captured_at=NOW - timedelta(seconds=4),
                               payload={"step": "ORDER_FILL"}, previous_hash=x[0]["event_hash"])
        x[2] = sfec.make_event(event_type="FINALIZE", captured_at=NOW - timedelta(seconds=1),
                               payload={"status": "FILLED"}, previous_hash=x[1]["event_hash"])
        self.assertFalse(sfec.verify_chain(x, now=NOW)["valid"])

    def test_append_after_finalize_fails(self):
        x = chain()
        x.append(sfec.make_event(event_type="LIFECYCLE_STEP", captured_at=NOW,
                                 payload={"step": "LATE"}, previous_hash=x[-1]["event_hash"]))
        self.assertFalse(sfec.verify_chain(x, now=NOW)["valid"])

    def test_naive_capture_time_rejected(self):
        with self.assertRaises(ValueError):
            sfec.make_event(event_type="CAPTURE_START", captured_at=datetime(2026, 9, 22, 9),
                            payload={})

    def test_separately_retained_anchor_detects_full_chain_rewrite(self):
        original = chain()
        anchor = sfec.compute_chain_anchor(original)
        # Rebuild an internally self-consistent but different chain.
        a = sfec.make_event(event_type="CAPTURE_START", captured_at=NOW - timedelta(seconds=3),
                            payload={"intent_hash": "rewritten"})
        b = sfec.make_event(event_type="LIFECYCLE_STEP", captured_at=NOW - timedelta(seconds=2),
                            payload={"step": "ORDER_FILL"}, previous_hash=a["event_hash"])
        c = sfec.make_event(event_type="FINALIZE", captured_at=NOW - timedelta(seconds=1),
                            payload={"status": "FILLED"}, previous_hash=b["event_hash"])
        rewritten = [a, b, c]
        self.assertTrue(sfec.verify_chain(rewritten, now=NOW)["valid"])
        result = sfec.verify_chain(rewritten, now=NOW, expected_anchor=anchor)
        self.assertFalse(result["valid"])
        self.assertIn("CHAIN_ANCHOR_MISMATCH", result["reasons"])

    def test_matching_anchor_passes(self):
        x = chain()
        self.assertTrue(sfec.verify_chain(
            x, now=NOW, expected_anchor=sfec.compute_chain_anchor(x))["valid"])

    def test_source_tamper_fails(self):
        x = deepcopy(chain()); x[0]["source"] = "BACKTEST"
        self.assertFalse(sfec.verify_chain(x, now=NOW)["valid"])


if __name__ == "__main__":
    unittest.main()
