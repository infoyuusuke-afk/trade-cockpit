import unittest
from datetime import datetime
from scripts import source_health_event_bridge as b
from scripts import guarded_council as g
from scripts import council_cycle_projection as p
class SourceHealthBridgeE2E(unittest.TestCase):
 def snap(self,state,at="2026-09-21T09:10:00+09:00"):
  return {"source":"MS2_RSS","state":state,"observed_at":at,"last_data_at":"2026-09-21T09:09:59+09:00","symbol":"TSE:285A","consecutive_failures":3}
 def test_stopped_blocks_council_and_warns(self):
  e=b.source_health_event(self.snap("STOPPED"))
  self.assertEqual(e["severity"],"CRITICAL")
  r=g.guarded_orchestrate([e],now=datetime.fromisoformat("2026-09-21T09:10:05+09:00"))
  self.assertEqual(r["status"],"READY"); self.assertEqual(r["council"]["status"],"BLOCK")
  out=p.project_cycle([e],r); self.assertEqual(out["command_center"]["system_status"],"ATTENTION"); self.assertEqual(out["commentary"][0]["priority"],1)
 def test_unknown_is_fail_closed(self):
  e=b.source_health_event(self.snap("UNKNOWN")); r=g.guarded_orchestrate([e],now=datetime.fromisoformat("2026-09-21T09:10:05+09:00"))
  self.assertEqual(r["council"]["status"],"BLOCK"); self.assertFalse(r["real_submit_allowed"])
 def test_healthy_does_not_block(self):
  e=b.source_health_event(self.snap("HEALTHY")); r=g.guarded_orchestrate([e],now=datetime.fromisoformat("2026-09-21T09:10:05+09:00"))
  self.assertNotEqual(r["council"]["status"],"BLOCK")
 def test_stale_health_snapshot_blocked_before_council(self):
  e=b.source_health_event(self.snap("HEALTHY","2026-09-21T09:08:00+09:00")); r=g.guarded_orchestrate([e],now=datetime.fromisoformat("2026-09-21T09:10:05+09:00"),max_age_seconds=60)
  self.assertEqual(r["status"],"BLOCK"); self.assertIsNone(r["council"])
