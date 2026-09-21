import unittest
from scripts import event_bus as e
class EventBusTests(unittest.TestCase):
 def base(self):
  return dict(timestamp="2026-09-21T21:00:00+09:00",domain="SYSTEM",event_type="DEVELOPMENT_MILESTONE",source="ChatGPT",payload={"summary":"x"})
 def test_deterministic_and_safe(self):
  a=e.build_event(**self.base()); b=e.build_event(**self.base())
  self.assertEqual(a["event_id"],b["event_id"]); self.assertFalse(a["real_submit_allowed"]); self.assertFalse(a["external_publish_allowed"]); self.assertTrue(e.validate_event(a))
 def test_naive_time_rejected(self):
  x=self.base(); x["timestamp"]="2026-09-21T21:00:00"
  with self.assertRaises(ValueError): e.build_event(**x)
 def test_tamper_rejected(self):
  a=e.build_event(**self.base()); a["payload"]["summary"]="tampered"; self.assertFalse(e.validate_event(a))
