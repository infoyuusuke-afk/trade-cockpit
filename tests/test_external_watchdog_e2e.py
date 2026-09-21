import unittest
from datetime import datetime
from scripts.external_health_watchdog import evaluate
from scripts.watchdog_health_projection import project
from scripts.local_source_health_contract import validate
from scripts.source_health_event_bridge import source_health_event
from scripts.guarded_council import guarded_orchestrate
class ExternalWatchdogE2E(unittest.TestCase):
 def test_stale_healthy_becomes_council_block(self):
  s={"schema_version":"local-source-health-1.0","source":"KIOXIA_SAFETY_HEARTBEAT","state":"HEALTHY","observed_at":"2026-09-21T09:09:40+09:00","last_data_at":None,"symbol":"TSE:285A","correlation_id":None,"consecutive_failures":0,"reasons":[]}
  now=datetime.fromisoformat("2026-09-21T09:10:00+09:00")
  d=evaluate(s,now=now,stale_after_seconds=15); out=project(s,d,observed_at=now.isoformat())
  self.assertTrue(validate(out)); e=source_health_event(out); r=guarded_orchestrate([e],now=now)
  self.assertEqual(r["council"]["status"],"BLOCK"); self.assertFalse(r["real_submit_allowed"])
