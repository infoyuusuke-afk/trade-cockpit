import unittest
from scripts.owner_approval_queue import build_queue,decide
class OwnerApprovalImmutabilityTest(unittest.TestCase):
 def raw(self): return {"approval_id":"A1","approval_type":"MAIN_MERGE","created_at":"2026-09-21T15:00:00+09:00","summary":"x"}
 def test_build(self): self.assertEqual(build_queue([self.raw()])[0]["status"],"PENDING_OWNER")
 def test_duplicate_id_rejected(self): self.assertRaises(ValueError,build_queue,[self.raw(),self.raw()])
 def test_unknown_field_rejected(self): x=self.raw();x["extra"]=1;self.assertRaises(ValueError,build_queue,[x])
 def test_naive_created_rejected(self): x=self.raw();x["created_at"]="2026-09-21T15:00:00";self.assertRaises(ValueError,build_queue,[x])
 def test_decision_records_owner_and_time(self):
  x=decide(build_queue([self.raw()])[0],"APPROVE",decided_at="2026-09-21T15:01:00+09:00")
  self.assertEqual(x["decided_by"],"OWNER");self.assertFalse(x["auto_approve"])
 def test_redecision_rejected(self):
  x=decide(build_queue([self.raw()])[0],"APPROVE",decided_at="2026-09-21T15:01:00+09:00")
  self.assertRaises(ValueError,decide,x,"REJECT",decided_at="2026-09-21T15:02:00+09:00")
 def test_non_owner_rejected(self):
  x=build_queue([self.raw()])[0];self.assertRaises(ValueError,decide,x,"APPROVE",decided_at="2026-09-21T15:01:00+09:00",actor="AI")
