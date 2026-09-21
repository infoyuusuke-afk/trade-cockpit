import unittest
from datetime import datetime
from scripts import event_bus as eb
from scripts import event_intake_guard as g
def e(sec=0):
 return eb.build_event(timestamp=f"2026-09-21T09:10:{sec:02d}+09:00",domain="SYSTEM",event_type="X",source="test",payload={"summary":"x"})
class EventIntakeGuardTests(unittest.TestCase):
 def test_ready(self):
  r=g.intake([e(10)],now=datetime.fromisoformat("2026-09-21T09:10:20+09:00")); self.assertEqual(r["status"],"READY"); self.assertEqual(len(r["accepted"]),1)
 def test_duplicate_rejected(self):
  x=e(10); r=g.intake([x,x],now=datetime.fromisoformat("2026-09-21T09:10:20+09:00")); self.assertEqual(r["status"],"PARTIAL"); self.assertEqual(r["rejected"][0]["reason"],"DUPLICATE_EVENT")
 def test_stale_blocks(self):
  r=g.intake([e(0)],now=datetime.fromisoformat("2026-09-21T09:12:00+09:00"),max_age_seconds=60); self.assertEqual(r["status"],"BLOCK"); self.assertEqual(r["rejected"][0]["reason"],"STALE_EVENT")
 def test_future_blocks(self):
  r=g.intake([e(30)],now=datetime.fromisoformat("2026-09-21T09:10:20+09:00")); self.assertEqual(r["status"],"BLOCK"); self.assertEqual(r["rejected"][0]["reason"],"FUTURE_EVENT")
 def test_tamper_blocks(self):
  x=e(10); x["payload"]["summary"]="tamper"; r=g.intake([x],now=datetime.fromisoformat("2026-09-21T09:10:20+09:00")); self.assertEqual(r["status"],"BLOCK"); self.assertEqual(r["rejected"][0]["reason"],"INVALID_EVENT")
