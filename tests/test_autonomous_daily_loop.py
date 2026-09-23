import unittest
from scripts.autonomous_daily_loop import plan_day
class TestLoop(unittest.TestCase):
 def test_ready_day_full_loop(self):
  x=plan_day({"market_open":True,"data_ready":True})
  phases=[t["phase"] for t in x["tasks"]]
  for p in ("ACQUIRE","VALIDATE","ANALYZE","DECIDE","EVALUATE","REPORT","LEARN"): self.assertIn(p,phases)
  self.assertFalse(x["owner_action_required"])
 def test_missing_data_recovers_or_waits(self):
  x=plan_day({"market_open":True,"data_ready":False})
  self.assertEqual(x["status"],"WAIT_DATA")
  self.assertFalse(x["real_submit_allowed"])
 def test_closed_market_no_order_decision(self):
  x=plan_day({"market_open":False,"data_ready":True})
  self.assertIn("NO_MARKET_ORDER_DECISION",[t["action"] for t in x["tasks"]])
if __name__=="__main__": unittest.main()
