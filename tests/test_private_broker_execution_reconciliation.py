import unittest
from scripts.private_broker_execution_reconciliation import match_real_execution

def pair():
 local={"reconciliation_status":"未照合","execution_id":"EX-1","order_id":"ORD-1",
        "ticker":"285A.T","side":"BUY","price":"1500.0","quantity":100,"fee":55,
        "executed_at":"2026-10-13T09:10:00+09:00","decision_snapshot_id":"decision-1"}
 broker={**local,"observation_source":"BROKER_EXECUTION_EXPORT",
         "executed_at":"2026-10-13T00:10:00+00:00"}
 return local,broker

class PrivateBrokerReconcileTests(unittest.TestCase):
 def test_full_identity_is_only_candidate_never_approval(self):
  a,b=pair()
  out=match_real_execution(a,b,verified_source=True)
  self.assertEqual(out["status"],"MATCH_CANDIDATE_ONLY")
  self.assertFalse(out["automatic_reconciliation_allowed"])
  self.assertFalse(out["ev_training_allowed"])
  self.assertFalse(out["real_submit_allowed"])

 def test_unverified_source_is_blocked(self):
  a,b=pair()
  self.assertIn("INDEPENDENT_BROKER_SOURCE_UNVERIFIED",match_real_execution(a,b)["reasons"])
  b["observation_source"]="SHADOW_FILL_MODEL"
  self.assertIn("INDEPENDENT_BROKER_SOURCE_UNVERIFIED",match_real_execution(a,b,verified_source=True)["reasons"])

 def test_no_naive_timezone_imputation(self):
  a,b=pair();a["executed_at"]="2026-10-13 09:10:00"
  self.assertIn("EXECUTED_AT_UNVERIFIABLE_OR_MISMATCH",match_real_execution(a,b,verified_source=True)["reasons"])

 def test_one_yen_price_difference_fails(self):
  a,b=pair();b["price"]="1501"
  self.assertIn("MISMATCH_PRICE",match_real_execution(a,b,verified_source=True)["reasons"])

 def test_fee_mismatch_fails_not_zero_default(self):
  a,b=pair();b.pop("fee")
  self.assertIn("MISMATCH_FEE",match_real_execution(a,b,verified_source=True)["reasons"])

 def test_qty_and_order_mismatch(self):
  a,b=pair();b["quantity"]=99;b["order_id"]="WRONG"
  out=match_real_execution(a,b,verified_source=True)
  self.assertIn("MISMATCH_QUANTITY",out["reasons"])
  self.assertIn("MISMATCH_ORDER_ID",out["reasons"])

 def test_missing_strategy_snapshot_blocks_ev_join(self):
  a,b=pair();a.pop("decision_snapshot_id")
  self.assertIn("DECISION_PROVENANCE_MISSING",match_real_execution(a,b,verified_source=True)["reasons"])

 def test_nan_and_infinity_are_invalid(self):
  for value in (float("nan"),float("inf"),"NaN","Infinity"):
   a,b=pair();b["fee"]=value
   self.assertIn("MISMATCH_FEE",match_real_execution(a,b,verified_source=True)["reasons"])

 def test_already_reconciled_status_is_rejected(self):
  a,b=pair();a["reconciliation_status"]="照合済み"
  self.assertIn("LOCAL_ALREADY_RECONCILED_OR_INVALID",match_real_execution(a,b,verified_source=True)["reasons"])

 def test_provenance_data_not_returned(self):
  a,b=pair();a["account_id"]="private-not-for-output";b["raw_broker_file"]="secret"
  out=match_real_execution(a,b,verified_source=True)
  self.assertNotIn("private-not-for-output",str(out))
  self.assertNotIn("secret",str(out))

if __name__=="__main__":unittest.main()
