import unittest
from datetime import datetime,timezone
from unittest.mock import patch
import scripts.shadow_position as sp
class KnownPositionLedgerBoundaryTest(unittest.TestCase):
 def test_malformed_known_position_id_is_rejected_before_create(self):
  intent={"intent_hash":"x"}
  order={"shadow_order_id":"o"}
  with patch.object(sp.se,"validate_shadow_order_state",return_value=[]), patch.object(sp.ec,"compute_intent_hash",return_value="x"):
   out=sp.create_shadow_position(intent,order,now=datetime.now(timezone.utc),known_positions=[{}])
  self.assertEqual(out["status"],"REJECTED")
  self.assertIn("REJECTED_KNOWN_POSITIONS_INVALID",out["reject_reasons"])
 def test_non_string_known_position_id_is_rejected(self):
  intent={"intent_hash":"x"};order={"shadow_order_id":"o"}
  with patch.object(sp.se,"validate_shadow_order_state",return_value=[]), patch.object(sp.ec,"compute_intent_hash",return_value="x"):
   out=sp.create_shadow_position(intent,order,now=datetime.now(timezone.utc),known_positions=[{"position_id":123}])
  self.assertEqual(out["status"],"REJECTED")
