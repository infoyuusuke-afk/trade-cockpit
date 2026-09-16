import importlib.util
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / 'scripts/order_guard.py'
spec = importlib.util.spec_from_file_location('og', SCRIPT_PATH)
og = importlib.util.module_from_spec(spec)
spec.loader.exec_module(og)


class IsDuplicateSubmissionTests(unittest.TestCase):
    def test_no_known_intents_is_not_duplicate(self):
        blocked, reasons = og.is_duplicate_submission("h" * 64, [])
        self.assertFalse(blocked)
        self.assertEqual(reasons, [])

    def test_different_hash_is_not_duplicate(self):
        known = [{"intent_hash": "a" * 64, "status": "FILLED"}]
        blocked, reasons = og.is_duplicate_submission("b" * 64, known)
        self.assertFalse(blocked)

    def test_same_hash_ticket_ready_blocks(self):
        known = [{"intent_hash": "a" * 64, "status": "TICKET_READY"}]
        blocked, reasons = og.is_duplicate_submission("a" * 64, known)
        self.assertTrue(blocked)
        self.assertIn("BLOCK_DUPLICATE_INTENT_HASH", reasons)

    def test_same_hash_authorized_or_submitting_blocks(self):
        for status in ("AUTHORIZED", "SUBMITTING", "ACKNOWLEDGED", "PARTIAL", "FILLED"):
            known = [{"intent_hash": "a" * 64, "status": status}]
            blocked, reasons = og.is_duplicate_submission("a" * 64, known)
            self.assertTrue(blocked, msg=f"status={status}")
            self.assertIn("BLOCK_DUPLICATE_INTENT_HASH", reasons)

    def test_same_hash_unknown_status_blocks_with_distinct_reason(self):
        """C-055第6節: ACK不明(UNKNOWN)を失敗と決めつけて自動再送しない。"""
        known = [{"intent_hash": "a" * 64, "status": "UNKNOWN"}]
        blocked, reasons = og.is_duplicate_submission("a" * 64, known)
        self.assertTrue(blocked)
        self.assertIn("BLOCK_DUPLICATE_PENDING_UNKNOWN", reasons)

    def test_same_hash_rejected_or_cancelled_does_not_block(self):
        for status in ("REJECTED", "CANCELLED"):
            known = [{"intent_hash": "a" * 64, "status": status}]
            blocked, reasons = og.is_duplicate_submission("a" * 64, known)
            self.assertFalse(blocked, msg=f"status={status}")

    def test_malformed_status_in_ledger_blocks(self):
        known = [{"intent_hash": "a" * 64, "status": "MADE_UP_STATUS"}]
        blocked, reasons = og.is_duplicate_submission("a" * 64, known)
        self.assertTrue(blocked)
        self.assertIn("BLOCK_DUPLICATE_MALFORMED_LEDGER_ENTRY", reasons)


class CheckPendingDuplicateTests(unittest.TestCase):
    def test_no_pending_orders_is_fine(self):
        blocked, _ = og.check_pending_duplicate("285A.T", "BUY", [])
        self.assertFalse(blocked)

    def test_same_symbol_same_side_pending_blocks(self):
        pending = [{"symbol": "285A.T", "side": "BUY", "qty": 100}]
        blocked, reasons = og.check_pending_duplicate("285A.T", "BUY", pending)
        self.assertTrue(blocked)
        self.assertIn("BLOCK_DUPLICATE_PENDING", reasons)

    def test_different_symbol_does_not_block(self):
        pending = [{"symbol": "8035.T", "side": "BUY", "qty": 100}]
        blocked, _ = og.check_pending_duplicate("285A.T", "BUY", pending)
        self.assertFalse(blocked)

    def test_opposite_side_same_symbol_does_not_trigger_this_specific_guard(self):
        """opposite-side競合自体はConflict Resolver/Permission Gate側の別ゲートの
        責務。ここはあくまで同一symbol・同方向のpendingだけを見る。"""
        pending = [{"symbol": "285A.T", "side": "SELL", "qty": 100}]
        blocked, _ = og.check_pending_duplicate("285A.T", "BUY", pending)
        self.assertFalse(blocked)


class CheckPositionReconciliationTests(unittest.TestCase):
    def test_matching_quantities_pass(self):
        blocked, _ = og.check_position_reconciliation(0, 0)
        self.assertFalse(blocked)
        blocked, _ = og.check_position_reconciliation(100, 100)
        self.assertFalse(blocked)

    def test_mismatched_quantities_block(self):
        blocked, reasons = og.check_position_reconciliation(0, 100)
        self.assertTrue(blocked)
        self.assertIn("BLOCK_POSITION_RECONCILIATION", reasons)
        blocked, _ = og.check_position_reconciliation(100, 0)
        self.assertTrue(blocked)

    def test_unknown_or_nan_quantities_block(self):
        for expected, broker in ((None, 0), (0, None), (float("nan"), 0), (0, float("inf"))):
            blocked, reasons = og.check_position_reconciliation(expected, broker)
            self.assertTrue(blocked, msg=f"expected={expected}, broker={broker}")
            self.assertIn("BLOCK_POSITION_RECONCILIATION_UNKNOWN", reasons)


class NoBrokerReferenceTests(unittest.TestCase):
    def test_source_has_no_broker_rss_or_network_references(self):
        import ast
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        forbidden_names = {"RssOrder", "win32com", "pywin32", "xlwings", "openpyxl"}
        forbidden_modules = {"win32com", "requests", "urllib", "socket", "http", "xlwings", "openpyxl"}
        found = set()
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                found.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                found.add(node.attr)
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(found, set())
        self.assertEqual(imported & forbidden_modules, set())


if __name__ == "__main__":
    unittest.main()
