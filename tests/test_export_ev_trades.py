#!/usr/bin/env python3
import math
import unittest
from scripts.export_ev_trades import audit, rows, review

def evidenced(side="LONG", entry=100.0, exit_price=102.0, cost=0.2):
    return {
        "strategy_key":"OR15_LONG",
        "strategy_id":"OR15_LONG",
        "triggered":True,
        "execution_type":"PAPER_OBSERVED",
        "fill_evidence":{
            "entry_fill_id":"paper-entry-1",
            "exit_fill_id":"paper-exit-1",
            "entry_source":"OBSERVED",
            "exit_source":"OBSERVED",
        },
        "entry_fill_price":entry,
        "exit_fill_price":exit_price,
        "entry_ts":"2026-10-13T09:02:00+09:00",
        "exit_ts":"2026-10-13T09:30:00+09:00",
        "cost_pct":cost,
        "cost_model_status":"VERIFIED",
        "side":side,
        "ticker":"285A.T",
    }

class ExportEVTradesTests(unittest.TestCase):
    def test_unlabelled_history_is_excluded(self):
        self.assertEqual(rows([{"triggered":True,"entry":100,"close":110,"side":"LONG","score":100}]),[])

    def test_old_labelled_close_mark_is_not_a_fill(self):
        self.assertEqual(rows([{"strategy_key":"OR15_LONG","triggered":True,"entry":100,"close":102,"side":"LONG"}]),[])

    def test_evidenced_long_net_after_cost(self):
        row=rows([evidenced()])[0]
        self.assertEqual(row["strategy_key"],"OR15_LONG")
        self.assertAlmostEqual(row["gross_pnl_pct"],2.0)
        self.assertAlmostEqual(row["net_pnl_pct"],1.8)
        self.assertEqual(row["symbol"],"285A")

    def test_evidenced_short_direction_inverted(self):
        row=rows([evidenced(side="SHORT",exit_price=98)])[0]
        self.assertAlmostEqual(row["net_pnl_pct"],1.8)

    def test_missing_or_zero_filled_cost_is_rejected(self):
        for cost in (None,-1,float("nan"),float("inf")):
            r=evidenced(cost=cost)
            self.assertEqual(review(r)[1],"EXPLICIT_COST_MISSING")
        r=evidenced(cost=0.0)
        r.pop("cost_model_status")
        self.assertEqual(review(r)[1],"COST_UNVERIFIED")

    def test_strategy_conflict_rejected(self):
        r=evidenced()
        r["strategy_id"]="DIFFERENT_STRATEGY"
        self.assertEqual(review(r)[1],"STRATEGY_ID_DISAGREEMENT")

    def test_missing_observation_and_bad_price_rejected(self):
        r=evidenced()
        r["fill_evidence"]["entry_source"]="ESTIMATED"
        self.assertEqual(review(r)[1],"FILL_NOT_OBSERVED")
        r=evidenced(entry=float("nan"))
        self.assertEqual(review(r)[1],"EXECUTED_PRICE_MISSING")

    def test_missing_or_naive_timestamps_rejected(self):
        r=evidenced()
        r["entry_ts"]="2026-10-13"
        self.assertEqual(review(r)[1],"EXECUTION_TIME_INVALID")
        r=evidenced()
        r["exit_ts"]="2026-10-13T09:00:00+09:00"
        self.assertEqual(review(r)[1],"EXECUTION_TIME_INVALID")

    def test_same_fill_id_rejected(self):
        r=evidenced()
        r["fill_evidence"]["exit_fill_id"]="paper-entry-1"
        self.assertEqual(review(r)[1],"FILL_ID_COLLISION")

    def test_audit_counts_only_and_never_outputs_quotes(self):
        data,summary=audit([evidenced(),{"triggered":True,"strategy_id":"s","price":999999}])
        self.assertEqual(len(data),1)
        self.assertEqual(summary["records_examined"],2)
        self.assertEqual(summary["excluded_records"],1)
        self.assertEqual(summary["exclusions"]["STRATEGY_KEY_MISSING"],1)
        self.assertFalse(summary["real_submit_allowed"])
        self.assertNotIn("999999",str(summary))

if __name__=="__main__":
    unittest.main()
