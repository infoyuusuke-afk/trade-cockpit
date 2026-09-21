import unittest
from datetime import datetime
from scripts.external_health_watchdog import evaluate
class ExternalHealthWatchdogTests(unittest.TestCase):
 def snap(self,at="2026-09-21T09:10:00+09:00",state="HEALTHY"):
  return {"schema_version":"local-source-health-1.0","source":"KIOXIA_SAFETY_HEARTBEAT","state":state,"observed_at":at,"last_data_at":None,"symbol":"TSE:285A","correlation_id":None,"consecutive_failures":0,"reasons":[]}
 def now(self,s="2026-09-21T09:10:05+09:00"): return datetime.fromisoformat(s)
 def test_fresh_health_preserved(self): self.assertEqual(evaluate(self.snap(),now=self.now())["state"],"HEALTHY")
 def test_stale_health_is_stopped(self):
  r=evaluate(self.snap("2026-09-21T09:09:40+09:00"),now=self.now(),stale_after_seconds=15); self.assertEqual((r["state"],r["reason"]),("STOPPED","HEARTBEAT_STALE"))
 def test_future_is_unknown(self): self.assertEqual(evaluate(self.snap("2026-09-21T09:10:06+09:00"),now=self.now())["state"],"UNKNOWN")
 def test_invalid_is_unknown(self):
  x=self.snap(); x["position_qty"]=100; self.assertEqual(evaluate(x,now=self.now())["state"],"UNKNOWN")
 def test_existing_stopped_remains_stopped(self): self.assertEqual(evaluate(self.snap(state="STOPPED"),now=self.now())["state"],"STOPPED")
 def test_real_submit_never_enabled(self): self.assertFalse(evaluate(self.snap(),now=self.now())["real_submit_allowed"])

 def test_exact_threshold_is_fresh(self):
  r=evaluate(self.snap("2026-09-21T09:09:50+09:00"),now=self.now(),stale_after_seconds=15); self.assertEqual(r["reason"],"FRESH")
 def test_timezone_offset_equivalence(self):
  r=evaluate(self.snap("2026-09-21T00:10:00+00:00"),now=self.now()); self.assertEqual((r["age_seconds"],r["state"]),(5.0,"HEALTHY"))
 def test_naive_now_rejected(self):
  with self.assertRaises(ValueError): evaluate(self.snap(),now=datetime.fromisoformat("2026-09-21T09:10:05"))
