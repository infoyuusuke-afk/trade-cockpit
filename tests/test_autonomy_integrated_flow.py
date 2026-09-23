import unittest
from scripts.autonomy_controller import control

class TestIntegratedAutonomyFlow(unittest.TestCase):
    def healthy(self):
        return {k:"OK" for k in ("data","strategy","execution","reporting","learning")}

    def test_market_day_runs_full_planning_chain_without_owner(self):
        x=control({"health":self.healthy(),"market_open":True})
        self.assertEqual(x["mode"],"DAILY_LOOP")
        phases=[t["phase"] for t in x["payload"]["tasks"]]
        self.assertEqual(phases,["ACQUIRE","VALIDATE","ANALYZE","DECIDE","EVALUATE","REPORT","LEARN"])
        self.assertFalse(x["owner_action_required"])

    def test_data_degradation_diverts_before_analysis(self):
        h=self.healthy();h["data"]="DEGRADED"
        x=control({"health":h,"market_open":True,"incident_code":"STALE_DATA"})
        self.assertEqual(x["mode"],"RECOVERY")
        self.assertNotIn("RUN_STRATEGY_LAB",x["payload"]["steps"])
        self.assertFalse(x["real_submit_allowed"])

    def test_execution_block_freezes_instead_of_continuing(self):
        h=self.healthy();h["execution"]="BLOCKED"
        x=control({"health":h,"market_open":True,"incident_code":"EXECUTION_ANOMALY"})
        self.assertEqual(x["payload"]["steps"][0],"FREEZE_NEW_ORDERS")

    def test_closed_market_stays_autonomous_without_order_decision(self):
        x=control({"health":self.healthy(),"market_open":False})
        actions=[t["action"] for t in x["payload"]["tasks"]]
        self.assertIn("NO_MARKET_ORDER_DECISION",actions)

if __name__=="__main__": unittest.main()
