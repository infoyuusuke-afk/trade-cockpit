import unittest
import scripts.execution_contract as ec
class ExecutionContractBoundaryTest(unittest.TestCase):
 def test_signal_known_at_accepts_offset(self): self.assertIsNotNone(ec.parse_signal_known_at("2026-09-21T15:00:00+09:00"))
 def test_signal_known_at_rejects_naive(self): self.assertIsNone(ec.parse_signal_known_at("2026-09-21T15:00:00"))
 def test_duplicate_candidate_must_be_dict(self): self.assertRaises(ValueError,ec.is_duplicate_intent,None,[])
 def test_duplicate_existing_must_be_list(self): self.assertRaises(ValueError,ec.is_duplicate_intent,{},None)
 def test_duplicate_existing_entries_must_be_dict(self): self.assertRaises(ValueError,ec.is_duplicate_intent,{},[None])
 def test_hash_field_set_unchanged(self):
  self.assertEqual(ec._HASH_FIELDS,("symbol","side","quantity","order_type","limit_price","planned_entry","planned_stop","strategy_id","strategy_version","decision_snapshot_id","execution_policy_version"))
 def test_unknown_is_terminal(self): self.assertEqual(ec.ALLOWED_TRANSITIONS["UNKNOWN"],frozenset())
