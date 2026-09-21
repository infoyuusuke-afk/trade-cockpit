import unittest
from scripts import owner_approval_queue as q


class OwnerApprovalQueueTests(unittest.TestCase):
    def item(self):
        return {
            "approval_id": "1",
            "approval_type": "MAIN_MERGE",
            "created_at": "2026-09-21T21:00:00+09:00",
            "summary": None,
        }

    def test_never_auto_approves(self):
        x = q.build_queue([self.item()])[0]
        self.assertEqual(x["status"], "PENDING_OWNER")
        self.assertFalse(x["auto_approve"])

    def test_explicit_owner_decision_is_audited(self):
        x = q.build_queue([self.item()])[0]
        y = q.decide(x, "APPROVE", decided_at="2026-09-21T21:01:00+09:00", decided_by="OWNER")
        self.assertEqual(y["status"], "OWNER_APPROVED")
        self.assertEqual(y["decided_at"], "2026-09-21T21:01:00+09:00")
        self.assertEqual(y["decided_by"], "OWNER")
        self.assertFalse(y["auto_approve"])

    def test_decision_is_terminal(self):
        x = q.build_queue([self.item()])[0]
        y = q.decide(x, "REJECT", decided_at="2026-09-21T21:01:00+09:00", decided_by="OWNER")
        with self.assertRaises(ValueError):
            q.decide(y, "APPROVE", decided_at="2026-09-21T21:02:00+09:00", decided_by="OWNER")

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            q.build_queue([self.item(), self.item()])

    def test_naive_created_at_rejected(self):
        x = self.item()
        x["created_at"] = "2026-09-21T21:00:00"
        with self.assertRaises(ValueError):
            q.build_queue([x])

    def test_naive_decided_at_rejected(self):
        x = q.build_queue([self.item()])[0]
        with self.assertRaises(ValueError):
            q.decide(x, "APPROVE", decided_at="2026-09-21T21:01:00", decided_by="OWNER")

    def test_non_owner_actor_rejected(self):
        x = q.build_queue([self.item()])[0]
        with self.assertRaises(ValueError):
            q.decide(x, "APPROVE", decided_at="2026-09-21T21:01:00+09:00", decided_by="SYSTEM")

    def test_decision_before_creation_rejected(self):
        x = q.build_queue([self.item()])[0]
        with self.assertRaises(ValueError):
            q.decide(x, "APPROVE", decided_at="2026-09-21T20:59:00+09:00", decided_by="OWNER")

    def test_unknown_fields_fail_closed(self):
        x = self.item()
        x["extra"] = True
        with self.assertRaises(ValueError):
            q.build_queue([x])
