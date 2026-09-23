import unittest
from scripts.autonomy_gate import evaluate
class TestAutonomyGate(unittest.TestCase):
 def good(self): return {"sample_size":100,"max_drawdown_pct":8.0,"evidence_integrity":True,"deterministic":True,"kill_switch_tested":True,"shadow_completed":True}
 def test_good_only_becomes_eligible(self):
  x=evaluate(self.good());self.assertEqual(x["level"],"CONTROLLED_LIVE_ELIGIBLE");self.assertFalse(x["real_submit_allowed"])
 def test_small_sample_blocked(self):
  x=self.good();x["sample_size"]=10
  self.assertFalse(evaluate(x)["promotion"])
 def test_shadow_required(self):
  x=self.good();x["shadow_completed"]=False
  self.assertEqual(evaluate(x)["level"],"SHADOW")
 def test_kill_switch_required(self):
  x=self.good();x["kill_switch_tested"]=False
  self.assertIn("KILL_SWITCH_UNTESTED",evaluate(x)["failures"])
if __name__=="__main__": unittest.main()
