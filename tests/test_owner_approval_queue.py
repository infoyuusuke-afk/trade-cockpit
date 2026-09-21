import unittest
from scripts import owner_approval_queue as q
class OwnerApprovalQueueTests(unittest.TestCase):
 def test_never_auto_approves(self):
  x=q.build_queue([{"approval_id":"1","approval_type":"EXTERNAL_PUBLISH","created_at":"2026-09-21T21:00:00+09:00","summary":"video"}])[0]
  self.assertEqual(x["status"],"PENDING_OWNER"); self.assertFalse(x["auto_approve"])
 def test_explicit_decision_only(self):
  x=q.build_queue([{"approval_id":"1","approval_type":"MAIN_MERGE","created_at":"2026-09-21T21:00:00+09:00"}])[0]
  self.assertEqual(q.decide(x,"APPROVE")["status"],"OWNER_APPROVED"); self.assertEqual(q.decide(x,"REJECT")["status"],"OWNER_REJECTED")
