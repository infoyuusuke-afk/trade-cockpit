import unittest
from scripts import safety_event_adapters as adapters
from scripts import owner_command_center as command
from scripts import live_commentary
from scripts import commentary_scheduler
class SafetyEventFlowE2ETests(unittest.TestCase):
 def test_risk_block_reaches_command_center_and_commentary(self):
  event=adapters.risk_event({"generated_at":"2026-09-21T09:10:00+09:00","decision":"BLOCK","symbol":"TSE:285A","merge_hash":"merge-1","allowed_qty":0,"block_reasons":["STALE_DATA"]})
  snap=command.build_command_center([event],{"status":"BLOCK"})
  self.assertEqual(snap["system_status"],"ATTENTION")
  self.assertEqual(snap["critical_count"],1)
  self.assertEqual(snap["council_status"],"BLOCK")
  self.assertFalse(snap["real_submit_allowed"])
  spoken=live_commentary.select_commentary([event])
  self.assertEqual(len(spoken),1)
  self.assertEqual(spoken[0]["priority"],1)
  self.assertIn("BLOCK",spoken[0]["text"])
 def test_execution_unknown_is_visible_and_throttled(self):
  a=adapters.execution_event({"created_at":"2026-09-21T09:10:00+09:00","status":"UNKNOWN","symbol":"TSE:285A","intent_hash":"intent-1"})
  b=adapters.execution_event({"created_at":"2026-09-21T09:10:05+09:00","status":"UNKNOWN","symbol":"TSE:285A","intent_hash":"intent-2"})
  candidates=live_commentary.select_commentary([a,b],limit=2)
  scheduled=commentary_scheduler.schedule(candidates,cooldown_seconds=20,max_items=2)
  self.assertEqual(len(scheduled),1)
  self.assertEqual(scheduled[0]["priority"],1)
  self.assertFalse(a["real_submit_allowed"]); self.assertFalse(a["external_publish_allowed"])
