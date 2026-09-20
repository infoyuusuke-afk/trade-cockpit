#!/usr/bin/env python3
import unittest
from scripts.build_mobile_approvals import build

class MobileApprovalTests(unittest.TestCase):
    def test_missing_ev_fails_closed(self):
        p=build({"prepared":[{"code":"285A","action":"LONG","score":100}]},{"groups":{}})
        r=p["requests"][0]
        self.assertEqual(r["action"],"WAIT"); self.assertEqual(r["risk_gate"],"BLOCK")
        self.assertEqual(r["risk_reason"],"STRATEGY_KEY_MISSING")

    def test_passed_empirical_ev_allows_proposal(self):
        sig={"prepared":[{"code":"285A","action":"LONG","strategy_key":"OR15_LONG","data_freshness_sec":10}]}
        ev={"groups":{"OR15_LONG":{"ev_score":78,"sample_size":120,"profit_factor":1.4,"avg_pl_pct":0.25,"max_dd_pct":-2.0,"risk_gate":"PASS","risk_reason":"OK"}}}
        r=build(sig,ev)["requests"][0]
        self.assertEqual(r["action"],"LONG");self.assertEqual(r["risk_gate"],"PASS");self.assertEqual(r["ev_score"],78)

if __name__=="__main__": unittest.main()
