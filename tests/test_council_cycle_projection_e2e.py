import unittest
from scripts import safety_event_adapters as a
from scripts import council_orchestrator as o
from scripts import council_cycle_projection as p
class CouncilCycleProjectionE2E(unittest.TestCase):
 def test_risk_block_fans_out_without_side_effects(self):
  e=a.risk_event({"generated_at":"2026-09-21T09:10:00+09:00","decision":"BLOCK","symbol":"TSE:285A","merge_hash":"m","allowed_qty":0,"block_reasons":["STALE_DATA"]})
  orchestration=o.orchestrate([e]); r=p.project_cycle([e],orchestration)
  self.assertEqual(r["council_status"],"BLOCK"); self.assertEqual(r["command_center"]["system_status"],"ATTENTION")
  self.assertEqual(len(r["commentary"]),1); self.assertEqual(r["commentary"][0]["priority"],1)
  self.assertEqual(len(r["journal"]),1); self.assertEqual(r["journal"][0]["category"],"RISK")
  self.assertFalse(r["real_submit_allowed"]); self.assertFalse(r["external_publish_allowed"]); self.assertTrue(r["owner_approval_required"])
 def test_same_cycle_is_deterministic(self):
  e=a.execution_event({"created_at":"2026-09-21T09:10:00+09:00","status":"UNKNOWN","symbol":"TSE:285A","intent_hash":"i"})
  x=o.orchestrate([e]); self.assertEqual(p.project_cycle([e],x),p.project_cycle([e],x))
