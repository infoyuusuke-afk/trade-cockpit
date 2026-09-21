import unittest
from scripts.order_guard import is_duplicate_submission,check_pending_duplicate
class OrderGuardBoundaryTest(unittest.TestCase):
 def test_known_intents_must_be_list(self): self.assertEqual(is_duplicate_submission("h",None),(True,["BLOCK_DUPLICATE_MALFORMED_LEDGER_ENTRY"]))
 def test_non_dict_known_entry_blocks(self): self.assertEqual(is_duplicate_submission("h",[None]),(True,["BLOCK_DUPLICATE_MALFORMED_LEDGER_ENTRY"]))
 def test_pending_must_be_list(self): self.assertEqual(check_pending_duplicate("TSE:285A","BUY",None),(True,["BLOCK_DUPLICATE_PENDING_UNKNOWN"]))
 def test_non_dict_pending_blocks(self): self.assertEqual(check_pending_duplicate("TSE:285A","BUY",[None]),(True,["BLOCK_DUPLICATE_PENDING_UNKNOWN"]))
 def test_invalid_side_blocks(self): self.assertEqual(check_pending_duplicate("TSE:285A","HOLD",[]),(True,["BLOCK_DUPLICATE_PENDING_UNKNOWN"]))
