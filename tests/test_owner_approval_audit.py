import unittest
from scripts import owner_approval_queue as q
class OwnerApprovalAuditTests(unittest.TestCase):
 def pending(self):
  return q.build_queue([{"approval_id":"a1","approval_type":"MAIN_MERGE","created_at":"2026-09-21T15:00:00+09:00"}])[0]
 def test_decision_records_actor_and_time(self):
  x=q.decide(self.pending(),"APPROVE",decided_at="2026-09-21T15:01:00+09:00",decided_by="OWNER")
  self.assertEqual(x["status"],"OWNER_APPROVED");self.assertEqual(x["decided_by"],"OWNER");self.assertFalse(x["auto_approve"])
 def test_terminal_cannot_be_decided_again(self):
  x=q.decide(self.pending(),"REJECT",decided_at="2026-09-21T15:01:00+09:00",decided_by="OWNER")
  with self.assertRaises(ValueError): q.decide(x,"APPROVE",decided_at="2026-09-21T15:02:00+09:00",decided_by="OWNER")
 def test_naive_decision_time_rejected(self):
  with self.assertRaises(ValueError): q.decide(self.pending(),"APPROVE",decided_at="2026-09-21T15:01:00",decided_by="OWNER")
 def test_unknown_input_field_rejected(self):
  with self.assertRaises(ValueError): q.build_queue([{"approval_id":"a1","approval_type":"MAIN_MERGE","created_at":"2026-09-21T15:00:00+09:00","auto_approve":True}])
 def test_duplicate_id_rejected(self):
  x={"approval_id":"a1","approval_type":"MAIN_MERGE","created_at":"2026-09-21T15:00:00+09:00"}
  with self.assertRaises(ValueError): q.build_queue([x,x])
