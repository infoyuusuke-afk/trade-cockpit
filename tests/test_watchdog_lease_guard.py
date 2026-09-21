import unittest
from datetime import datetime
from scripts.watchdog_lease_guard import evaluate_watchdog_lease
class WatchdogLeaseGuardTests(unittest.TestCase):
 def now(self): return datetime.fromisoformat("2026-09-21T09:10:15+09:00")
 def snap(self,state="HEALTHY",ts="2026-09-21T09:10:05+09:00"):
  return {"schema_version":"local-source-health-1.0","source":"EXTERNAL_HEALTH_WATCHDOG","state":state,"observed_at":ts,"last_data_at":"2026-09-21T09:10:00+09:00","symbol":"TSE:285A","correlation_id":None,"consecutive_failures":0,"reasons":[]}
 def test_fresh_healthy_ready(self): self.assertEqual(evaluate_watchdog_lease(self.snap(),now=self.now())["status"],"READY")
 def test_missing_blocks(self): self.assertEqual(evaluate_watchdog_lease(None,now=self.now())["status"],"BLOCK")
 def test_invalid_blocks(self):
  x=self.snap(); x["order_id"]="x"; self.assertEqual(evaluate_watchdog_lease(x,now=self.now())["status"],"BLOCK")
 def test_future_blocks(self): self.assertEqual(evaluate_watchdog_lease(self.snap(ts="2026-09-21T09:10:16+09:00"),now=self.now())["reason"],"FUTURE_WATCHDOG")
 def test_exact_threshold_ready(self): self.assertEqual(evaluate_watchdog_lease(self.snap(ts="2026-09-21T09:10:00+09:00"),now=self.now(),lease_seconds=15)["status"],"READY")
 def test_stale_blocks(self): self.assertEqual(evaluate_watchdog_lease(self.snap(ts="2026-09-21T09:09:59+09:00"),now=self.now(),lease_seconds=15)["reason"],"STALE_WATCHDOG")
 def test_stopped_unknown_block(self):
  for s in ("STOPPED","UNKNOWN"): self.assertEqual(evaluate_watchdog_lease(self.snap(state=s),now=self.now())["status"],"BLOCK")
 def test_degraded_reviews(self): self.assertEqual(evaluate_watchdog_lease(self.snap(state="DEGRADED"),now=self.now())["status"],"REVIEW")
 def test_never_promotes_or_submits(self):
  r=evaluate_watchdog_lease(self.snap(),now=self.now()); self.assertFalse(r["promotion_eligible"]); self.assertFalse(r["real_submit_allowed"])
