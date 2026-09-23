import unittest
from scripts.self_healing_supervisor import recovery_plan,terminal_state
class TestSelfHealing(unittest.TestCase):
 def test_stale_data_self_handles(self):
  p=recovery_plan({"code":"STALE_DATA"});self.assertFalse(p["owner_action_required"]);self.assertIn("WAIT_DATA",p["steps"])
 def test_execution_anomaly_freezes(self):
  p=recovery_plan({"code":"EXECUTION_ANOMALY"});self.assertEqual(p["steps"][0],"FREEZE_NEW_ORDERS");self.assertFalse(p["real_submit_allowed"])
 def test_unknown_fails_safe(self):
  p=recovery_plan({"code":"NEW_UNKNOWN"});self.assertEqual(p["state"],"SAFE");self.assertFalse(p["owner_action_required"])
 def test_unrecovered_data_waits(self):
  self.assertEqual(terminal_state(recovery_plan({"code":"SOURCE_DISAGREEMENT"}),False),"WAIT_DATA")
if __name__=="__main__": unittest.main()
