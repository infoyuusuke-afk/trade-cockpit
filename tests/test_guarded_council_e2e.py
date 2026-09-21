import unittest
from datetime import datetime
from scripts import event_bus as eb
from scripts import guarded_council as g
def e(ts):
 return eb.build_event(timestamp=ts,domain="RISK",event_type="RISK_DECISION",source="risk_gate",severity="NOTICE",symbol="TSE:285A",payload={"summary":"PASS","decision":"PASS"})
class GuardedCouncilE2E(unittest.TestCase):
 def test_fresh_event_reaches_council(self):
  r=g.guarded_orchestrate([e("2026-09-21T09:10:00+09:00")],now=datetime.fromisoformat("2026-09-21T09:10:10+09:00"))
  self.assertEqual(r["status"],"READY"); self.assertIsNotNone(r["council"]); self.assertFalse(r["real_submit_allowed"])
 def test_stale_never_reaches_council(self):
  r=g.guarded_orchestrate([e("2026-09-21T09:10:00+09:00")],now=datetime.fromisoformat("2026-09-21T09:12:00+09:00"))
  self.assertEqual(r["status"],"BLOCK"); self.assertIsNone(r["council"]); self.assertEqual(r["gate"]["rejected"][0]["reason"],"STALE_EVENT")
 def test_future_never_reaches_council(self):
  r=g.guarded_orchestrate([e("2026-09-21T09:11:00+09:00")],now=datetime.fromisoformat("2026-09-21T09:10:00+09:00"))
  self.assertEqual(r["status"],"BLOCK"); self.assertIsNone(r["command_center"]); self.assertEqual(r["gate"]["rejected"][0]["reason"],"FUTURE_EVENT")
 def test_partial_batch_fails_closed(self):
  fresh=e("2026-09-21T09:10:00+09:00"); stale=e("2026-09-21T09:08:00+09:00")
  r=g.guarded_orchestrate([fresh,stale],now=datetime.fromisoformat("2026-09-21T09:10:10+09:00"))
  self.assertEqual(r["gate"]["status"],"PARTIAL"); self.assertEqual(r["status"],"BLOCK"); self.assertIsNone(r["council"])
