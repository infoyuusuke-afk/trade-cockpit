import unittest
from scripts import event_bus as eb
from scripts import council_orchestrator as o
def event(domain,event_type,decision,severity,sec):
 return eb.build_event(timestamp=f"2026-09-21T09:10:{sec:02d}+09:00",domain=domain,event_type=event_type,source=domain.lower(),severity=severity,symbol="TSE:285A",payload={"summary":decision,"decision":decision})
class CouncilOrchestratorTests(unittest.TestCase):
 def test_risk_block_dominates(self):
  xs=[event("STRATEGY","SIGNAL","LONG","NOTICE",1),event("RISK","RISK_DECISION","BLOCK","CRITICAL",2)]
  r=o.orchestrate(xs)
  self.assertEqual(r["council"]["status"],"BLOCK"); self.assertEqual(r["command_center"]["system_status"],"ATTENTION"); self.assertFalse(r["real_submit_allowed"])
 def test_execution_unknown_blocks(self):
  r=o.orchestrate([event("EXECUTION","EXECUTION_STATE","UNKNOWN","CRITICAL",1)])
  self.assertEqual(r["council"]["status"],"BLOCK")
 def test_same_inputs_same_output(self):
  xs=[event("STRATEGY","SIGNAL","LONG","NOTICE",1)]
  self.assertEqual(o.orchestrate(xs),o.orchestrate(list(reversed(xs))))
 def test_never_publishes_or_executes(self):
  r=o.orchestrate([])
  self.assertFalse(r["real_submit_allowed"]); self.assertFalse(r["external_publish_allowed"]); self.assertTrue(r["owner_approval_required"])
