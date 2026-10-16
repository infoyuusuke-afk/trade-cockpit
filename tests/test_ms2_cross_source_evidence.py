"""Four-source health evidence must never become a trading authorization."""
from datetime import datetime, timedelta, timezone
import unittest

from scripts.ms2_cross_source_evidence import evaluate_source_evidence

NOW = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)

def receipt(source, **updates):
    record = dict(schema_version="local-source-health-1.0", source=source,
                  state="HEALTHY", observed_at=NOW.isoformat(),
                  last_data_at=(NOW-timedelta(seconds=2)).isoformat(),
                  consecutive_failures=0, reasons=[])
    record.update(updates)
    return record

class CrossSource(unittest.TestCase):
    def all_sources(self):
        return [receipt(x) for x in ("collector", "watcher", "gateway", "brain")]

    def test_healthy_only_observation_never_authenticated(self):
        r=evaluate_source_evidence(self.all_sources(),NOW.isoformat())
        self.assertEqual(r["status"],"OBSERVATION_CANDIDATE_ONLY")
        self.assertFalse(r["source_authenticated"])
        self.assertFalse(r["cross_source_join_allowed"])
        self.assertFalse(r["real_submit_allowed"])
        self.assertFalse(r["promotion_eligible"])

    def test_missing_brain_and_unknown_timestamp_are_blocked(self):
        self.assertEqual(evaluate_source_evidence(self.all_sources()[:3],NOW.isoformat())["status"],"BLOCKED")
        bad=self.all_sources()
        bad[0]["last_data_at"]=None
        self.assertEqual(evaluate_source_evidence(bad,NOW.isoformat())["status"],"BLOCKED")

    def test_stale_future_and_unsafe_states(self):
        for patch in (
            {"observed_at":(NOW-timedelta(seconds=70)).isoformat()},
            {"last_data_at":(NOW+timedelta(seconds=1)).isoformat()},
            {"state":"DEGRADED"},
            {"consecutive_failures":1},
        ):
            rr=self.all_sources()
            rr[0].update(patch)
            self.assertEqual(evaluate_source_evidence(rr,NOW.isoformat())["status"],"BLOCKED")

    def test_cross_source_clock_disagreement_blocks(self):
        rr=self.all_sources()
        rr[2]["last_data_at"]=(NOW-timedelta(seconds=25)).isoformat()
        a=evaluate_source_evidence(rr,NOW.isoformat())
        self.assertIn("CROSS_SOURCE_TIME_DISAGREEMENT",a["reasons"])

    def test_duplicate_and_naive_receipts_block(self):
        rr=self.all_sources()+[receipt("collector")]
        self.assertEqual(evaluate_source_evidence(rr,NOW.isoformat())["status"],"BLOCKED")
        with self.assertRaises(ValueError):
            evaluate_source_evidence(self.all_sources(),"2026-10-16T10:00:00")

if __name__=="__main__":
    unittest.main()
