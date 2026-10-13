import unittest
from scripts.shadow_ev_evidence_projection import project
from scripts.export_ev_trades import review

def fixture():
    intent={"intent_hash":"intent-unique-1","strategy_id":"OR15_LONG","symbol":"285A.T","side":"BUY"}
    entry={"intent_hash":"intent-unique-1","strategy_id":"OR15_LONG","event_type":"ENTRY_FILL",
           "evidence_source":"INDEPENDENT_OBSERVED_FILL","fill_id":"entry-1","fill_price":100.0,
           "filled_qty":100,"observed_at":"2026-10-13T09:10:00+09:00"}
    exit_={"intent_hash":"intent-unique-1","strategy_id":"OR15_LONG","event_type":"EXIT_FILL",
           "evidence_source":"INDEPENDENT_OBSERVED_FILL","fill_id":"exit-1","fill_price":101.0,
           "filled_qty":100,"observed_at":"2026-10-13T09:30:00+09:00"}
    cost={"intent_hash":"intent-unique-1","cost_model_status":"VERIFIED","cost_pct":0.1}
    return intent,entry,exit_,cost

class ShadowEVProjectionTests(unittest.TestCase):
    def test_matched_evidence_generates_export_eligible_paper_row(self):
        row,reason=project(*fixture())
        self.assertIsNone(reason)
        export,invalid=review(row)
        self.assertIsNone(invalid)
        self.assertAlmostEqual(export["net_pnl_pct"],0.9)
        self.assertFalse(row["real_submit_allowed"])

    def test_shadow_fill_models_estimates_never_promoted(self):
        for confidence in ("PROBABLE","UNCERTAIN","UNOBSERVABLE"):
            vals=list(fixture())
            vals[1]["fill_confidence"]=confidence
            self.assertEqual(project(*vals)[1],"ESTIMATED_FILL_REJECTED")
        vals=list(fixture());vals[2]["slippage_model_status"]="NOT_MODELED_V0_1"
        self.assertEqual(project(*vals)[1],"ESTIMATED_FILL_REJECTED")

    def test_unknown_fee_and_zero_implicit_cost_blocked(self):
        vals=list(fixture());vals[3].pop("cost_pct")
        self.assertEqual(project(*vals)[1],"COST_VALUE_MISSING")
        vals=list(fixture());vals[3]["cost_model_status"]="UNKNOWN"
        self.assertEqual(project(*vals)[1],"COST_EVIDENCE_NOT_VERIFIED")

    def test_identity_mismatch_blocked(self):
        vals=list(fixture());vals[2]["strategy_id"]="OTHER"
        self.assertEqual(project(*vals)[1],"LINEAGE_MISMATCH")
        vals=list(fixture());vals[3]["intent_hash"]="other"
        self.assertEqual(project(*vals)[1],"COST_EVIDENCE_NOT_VERIFIED")

    def test_partial_or_nonmatching_quantity_rejected(self):
        vals=list(fixture());vals[2]["filled_qty"]=50
        self.assertEqual(project(*vals)[1],"UNMATCHED_FILLED_QTY")

    def test_time_order_and_naive_time_rejected(self):
        vals=list(fixture());vals[2]["observed_at"]="2026-10-13T09:00:00+09:00"
        self.assertEqual(project(*vals)[1],"FILL_TIME_INVALID")
        vals=list(fixture());vals[1]["observed_at"]="2026-10-13T09:10:00"
        self.assertEqual(project(*vals)[1],"FILL_TIME_INVALID")

    def test_fills_without_independent_evidence_blocked(self):
        vals=list(fixture());vals[1]["evidence_source"]="SHADOW_MODEL"
        self.assertEqual(project(*vals)[1],"INDEPENDENT_FILL_EVIDENCE_MISSING")
        vals=list(fixture());vals[1]["fill_id"]=vals[2]["fill_id"]
        self.assertEqual(project(*vals)[1],"FILL_ID_COLLISION")

    def test_private_fields_rejected_not_copied(self):
        vals=list(fixture());vals[0]["broker_account"]="secret"
        self.assertEqual(project(*vals)[1],"PRIVATE_FIELD_REJECTED")
        row,_=project(*fixture())
        self.assertNotIn("broker",str(row))
        self.assertNotIn("account",str(row))

    def test_short_return_and_safe_mode(self):
        vals=list(fixture());vals[0]["side"]="SELL";vals[2]["fill_price"]=98.
        row,reason=project(*vals)
        self.assertIsNone(reason)
        self.assertEqual(row["side"],"SHORT")
        self.assertAlmostEqual(review(row)[0]["net_pnl_pct"],1.9)
        self.assertFalse(row["real_submit_allowed"])

if __name__=="__main__":
    unittest.main()
