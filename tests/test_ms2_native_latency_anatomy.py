"""No market data: validate correlated synthetic per-poll timing and privacy."""
import json
import unittest
from scripts.ms2_native_latency_anatomy import diagnose


def record(capture, packing, submit, full, **extras):
    return dict(state="ACCEPTED", capture_ms=capture, packing_ms=packing,
                submit_ms=submit, full_ms=full, **extras)


class AnatomyTests(unittest.TestCase):
    def test_slowest_sample_components_are_same_observation(self):
        rows = [record(80, 1, 1, 82), record(0.1, 2.1, 0.2, 2.6),
                record(0.2, 0.3, 52.0, 52.7),
                record(4.8, 0.1, 0.1, 5.2)]
        o = diagnose(rows)
        self.assertEqual(o["status"], "SYNTHETIC_SEGMENTS_REPORTED_ONLY")
        self.assertEqual(o["n"], 3)
        self.assertEqual(o["over_5ms_count"], 2)
        self.assertEqual(o["slowest_full_ms"], 52.7)
        self.assertEqual(o["slowest_components_ms"]["submit_ms"], 52)
        self.assertEqual(o["largest_measured_component_at_peak"], "submit_ms")
        self.assertFalse(o["os_root_cause_proven"])

    def test_aggregate_stage_max_does_not_override_full_peak(self):
        rows = [record(0, 0, 0, 0), record(15, 0, 0, 15.2),
                record(0, 2, 19, 21.1)]
        out = diagnose(rows)
        self.assertEqual(out["slowest_components_ms"]["capture_ms"], 0)
        self.assertEqual(out["slowest_full_ms"], 21.1)
        self.assertEqual(out["largest_measured_component_at_peak"], "submit_ms")

    def test_unattributed_time_is_not_proven_os_scheduling(self):
        rows = [record(0, 0, 0, 0), record(.2, .2, .3, 20)]
        out = diagnose(rows)
        self.assertEqual(out["largest_measured_component_at_peak"], "unattributed_ms")
        self.assertIn("UNMEASURED_SCHEDULING_AND_JITTER", out["reason_codes"])
        self.assertFalse(out["production_latency_bound_proven"])

    def test_first_submit_is_disjoint_from_steady(self):
        rows = [record(400, 0, 0, 400), record(.1, .1, .1, .4)]
        out = diagnose(rows)
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["over_5ms_count"], 0)

    def test_drop_is_excluded_without_claiming_lossless(self):
        rows = [record(0, 0, 0, 0), record(10, 1, 1, 12, state_override="dummy")]
        rows[1]["state"] = "DROPPED"
        out = diagnose(rows)
        self.assertEqual(out["status"], "EVIDENCE_INVALID")
        self.assertIn("NO_ACCEPTED_STEADY_SAMPLES", out["reason_codes"])

    def test_invalid_time_rejected(self):
        for value in (None, "1", float("nan"), float("inf"), -0.01):
            with self.subTest(value=repr(value)):
                rows = [record(0, 0, 0, 0), record(value, .1, .1, 1)]
                self.assertIn("TIMING_SAMPLE_INVALID", diagnose(rows)["reason_codes"])

    def test_component_exceeds_full_rejected(self):
        rows = [record(0, 0, 0, 0), record(6, 5, 4, 4)]
        self.assertIn("TIMING_COMPONENTS_EXCEED_FULL", diagnose(rows)["reason_codes"])

    def test_empty_or_nonlist_rejected(self):
        for obj in (None, [], {}, [record(1, 1, 1, 3)]):
            self.assertEqual(diagnose(obj)["status"], "EVIDENCE_INVALID")

    def test_synthetic_keys_never_leak(self):
        rows = [record(0, 0, 0, 0), record(1, 2, 3, 6.2,
                symbol="SYNTHETIC_SECRET", captured_at="2026-10-14T00:00:00")]
        out = json.dumps(diagnose(rows))
        self.assertNotIn("SYNTHETIC_SECRET", out)
        self.assertNotIn("2026-10-14", out)
        self.assertFalse(json.loads(out)["production_latency_bound_proven"])

    def test_determinism(self):
        a = [record(0, 0, 0, 0), record(1, 1, 1, 3.1)]
        self.assertEqual(diagnose(a), diagnose(a))


if __name__ == "__main__":
    unittest.main()
