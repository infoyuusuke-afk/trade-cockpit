import unittest
from scripts import safety_event_adapters as a
class SafetyAdapterTests(unittest.TestCase):
 def test_risk_block_is_critical_and_non_executable(self):
  e=a.risk_event({"generated_at":"2026-09-21T21:00:00+09:00","decision":"BLOCK","symbol":"TSE:285A","merge_hash":"m","allowed_qty":0,"block_reasons":["STALE"]})
  self.assertEqual(e["domain"],"RISK"); self.assertEqual(e["severity"],"CRITICAL"); self.assertFalse(e["real_submit_allowed"])
 def test_shadow_only_is_important(self):
  e=a.risk_event({"generated_at":"2026-09-21T21:00:00+09:00","decision":"SHADOW_ONLY","symbol":"TSE:285A","merge_hash":"m","allowed_qty":0})
  self.assertEqual(e["severity"],"IMPORTANT")
 def test_execution_unknown_is_critical(self):
  e=a.execution_event({"created_at":"2026-09-21T21:00:00+09:00","status":"UNKNOWN","symbol":"TSE:285A","intent_hash":"i"})
  self.assertEqual(e["severity"],"CRITICAL"); self.assertFalse(e["real_submit_allowed"]); self.assertFalse(e["external_publish_allowed"])
