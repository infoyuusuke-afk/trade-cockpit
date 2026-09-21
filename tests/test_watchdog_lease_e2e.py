import unittest
from datetime import datetime
from scripts.watchdog_lease_guard import evaluate_watchdog_lease
from scripts.watchdog_lease_event_bridge import lease_event
from scripts.guarded_council import guarded_orchestrate
class WatchdogLeaseE2E(unittest.TestCase):
 def test_stale_watchdog_blocks_council(self):
  now=datetime.fromisoformat("2026-09-21T09:10:15+09:00")
  s={"schema_version":"local-source-health-1.0","source":"EXTERNAL_HEALTH_WATCHDOG","state":"HEALTHY","observed_at":"2026-09-21T09:09:59+09:00","last_data_at":None,"symbol":"TSE:285A","correlation_id":None,"consecutive_failures":0,"reasons":[]}
  d=evaluate_watchdog_lease(s,now=now,lease_seconds=15); e=lease_event(d,timestamp=now.isoformat()); r=guarded_orchestrate([e],now=now)
  self.assertEqual(d["status"],"BLOCK"); self.assertEqual(r["council"]["status"],"BLOCK"); self.assertEqual(r["command_center"]["status"],"ATTENTION"); self.assertFalse(r["real_submit_allowed"])
 def test_recovery_requires_new_fresh_record(self):
  now=datetime.fromisoformat("2026-09-21T09:10:15+09:00")
  def s(ts): return {"schema_version":"local-source-health-1.0","source":"EXTERNAL_HEALTH_WATCHDOG","state":"HEALTHY","observed_at":ts,"last_data_at":None,"symbol":"TSE:285A","correlation_id":None,"consecutive_failures":0,"reasons":[]}
  self.assertEqual(evaluate_watchdog_lease(s("2026-09-21T09:09:59+09:00"),now=now)["status"],"BLOCK")
  self.assertEqual(evaluate_watchdog_lease(s("2026-09-21T09:10:14+09:00"),now=now)["status"],"READY")
