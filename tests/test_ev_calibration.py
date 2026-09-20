#!/usr/bin/env python3
import unittest
from scripts.calibrate_ev import stats

class EVCalibrationTests(unittest.TestCase):
    def test_small_sample_is_blocked(self):
        r=stats([0.4]*20)
        self.assertEqual(r["risk_gate"],"BLOCK")
        self.assertEqual(r["risk_reason"],"INSUFFICIENT_SAMPLE")

    def test_non_positive_edge_is_blocked(self):
        r=stats(([0.1,-0.2])*20)
        self.assertEqual(r["risk_gate"],"BLOCK")

    def test_sufficient_positive_edge_can_pass(self):
        r=stats(([0.4,-0.1,0.3])*20)
        self.assertGreaterEqual(r["sample_size"],30)
        self.assertGreaterEqual(r["profit_factor"],1.10)
        self.assertGreater(r["avg_pl_pct"],0)
        self.assertEqual(r["risk_gate"],"PASS")

    def test_score_is_bounded(self):
        for vals in ([1.0]*40,[-1.0]*40,([0.3,-0.1])*30):
            r=stats(list(vals))
            self.assertGreaterEqual(r["ev_score"],0)
            self.assertLessEqual(r["ev_score"],100)

if __name__=="__main__": unittest.main()
