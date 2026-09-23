import unittest
from scripts.autonomy_controller import control
class TestController(unittest.TestCase):
 def healthy(self): return {k:"OK" for k in ("data","strategy","execution","reporting","learning")}
 def test_healthy_runs_daily_loop(self):
  x=control({"health":self.healthy(),"market_open":True})
  self.assertEqual(x["mode"],"DAILY_LOOP");self.assertEqual(x["payload"]["status"],"PLANNED")
 def test_blocked_routes_recovery(self):
  h=self.healthy();h["execution"]="BLOCKED"
  x=control({"health":h,"incident_code":"EXECUTION_ANOMALY"})
  self.assertEqual(x["mode"],"RECOVERY");self.assertIn("FREEZE_NEW_ORDERS",x["payload"]["steps"])
 def test_degraded_does_not_continue_as_healthy(self):
  h=self.healthy();h["data"]="DEGRADED"
  x=control({"health":h,"incident_code":"STALE_DATA"})
  self.assertEqual(x["mode"],"RECOVERY")
 def test_authority_remains_locked(self):
  x=control({"health":self.healthy()})
  self.assertFalse(x["real_submit_allowed"]);self.assertFalse(x["external_publish_allowed"])
if __name__=="__main__": unittest.main()
