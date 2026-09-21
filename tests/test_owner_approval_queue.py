import unittest
from scripts import owner_approval_queue as q
class OwnerApprovalQueueTests(unittest.TestCase):
 def item(self,t="MAIN_MERGE"):
  return {"approval_id":"1","approval_type":t,"created_at":"2026-09-21T21:00:00+09:00","summary":"video"}
 def test_never_auto_approves(self):
  x=q.build_queue([self.item("EXTERNAL_PUBLISH")])[0]
  self.assertEqual(x["status"],"PENDING_OWNER"); self.assertFalse(x["auto_approve"])
 def test_explicit_decision_only(self):
  x=q.build_queue([self.item()])[0]
  self.assertEqual(q.decide(x,"APPROVE",decided_at="2026-09-21T21:01:00+09:00",decided_by="OWNER")["status"],"OWNER_APPROVED")
  self.assertEqual(q.decide(x,"REJECT",decided_at="2026-09-21T21:01:00+09:00",decided_by="OWNER")["status"],"OWNER_REJECTED")
