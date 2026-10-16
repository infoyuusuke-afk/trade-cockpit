"""Exact V10 status-only /health is NOT a replacement for four receipts."""
from datetime import datetime, timedelta, timezone
import unittest
from scripts.ms2_v10_health_adapter import source_receipt, evaluate_v10_runtime

NOW = datetime(2026,10,16,9,0,tzinfo=timezone.utc)
def item():
    return {"state":"HEALTHY","updated_at":NOW.isoformat(),
            "last_data_at":(NOW-timedelta(seconds=2)).isoformat()}
def healthy_gateway():
    return {"runtime":{"fail_closed":False,"data_conflict":False,
                       "price_source_status":"OK",
                       "collector_status":"LIVE","watcher_status":"LIVE"}}

class AdapterTests(unittest.TestCase):
    def test_legacy_gateway_status_only_cannot_prove_independent_sources(self):
        r=evaluate_v10_runtime(healthy_gateway(),{},NOW.isoformat())
        self.assertEqual(r["status"],"BLOCKED")
        self.assertIn("INDEPENDENT_RECEIPT_MISSING_BRAIN",r["reasons"])
        self.assertFalse(r["source_authenticated"])

    def test_all_independent_health_only_observation_candidate(self):
        sources={x:item() for x in ("collector","watcher","gateway","brain")}
        r=evaluate_v10_runtime(healthy_gateway(),sources,NOW.isoformat())
        self.assertEqual(r["status"],"OBSERVATION_CANDIDATE_ONLY")
        self.assertFalse(r["real_submit_allowed"])
        self.assertFalse(r["cross_source_join_allowed"])

    def test_stale_duplicate_and_bad_timestamp_fail_closed(self):
        sources={x:item() for x in ("collector","watcher","gateway","brain")}
        sources["watcher"]["last_data_at"]=(NOW-timedelta(seconds=90)).isoformat()
        r=evaluate_v10_runtime(healthy_gateway(),sources,NOW.isoformat())
        self.assertEqual(r["status"],"BLOCKED")
        self.assertIsNone(source_receipt("brain",{"state":"HEALTHY","updated_at":"2026-10-16 09:00:00","last_data_at":"2026-10-16 08:59:58"}))

    def test_gateway_runtime_blocks_even_when_receipts_fresh(self):
        sources={x:item() for x in ("collector","watcher","gateway","brain")}
        h=healthy_gateway()
        h["runtime"]["fail_closed"]=True
        r=evaluate_v10_runtime(h,sources,NOW.isoformat())
        self.assertEqual(r["status"],"BLOCKED")
        self.assertIn("GATEWAY_FAIL_CLOSED",r["reasons"])

    def test_untrusted_identity_claim_rejected(self):
        r=item()
        r["authenticated"]=True
        self.assertIsNone(source_receipt("collector",r))

if __name__=="__main__":
    unittest.main()
