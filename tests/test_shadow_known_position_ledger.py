import importlib.util
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
ec=load("ec_c102","scripts/execution_contract.py");se=load("se_c102","scripts/shadow_execution.py");sp=load("sp_c102","scripts/shadow_position.py")
JST=timezone(timedelta(hours=9));NOW=datetime(2026,9,17,9,0,tzinfo=JST);SUBMITTED=NOW-timedelta(seconds=10)
def valid_pair():
 intent=ec.build_intent(symbol="285A.T",side="BUY",quantity=100,order_type="MARKET",strategy_id="s",strategy_version="1",decision_snapshot_id="d",signal_known_at="2026-09-17T08:55:00+09:00",risk_policy_version="risk-gate-0.1.0",execution_policy_version="exec-v0.1",shadow_fill_model_version="shadow-fill-model-0.1",merge_hash="m"*64,planned_entry=1500.0,planned_stop=1450.0,planned_target=1600.0)
 risk={"decision":"PASS","merge_hash":"m"*64,"allowed_qty":100,"symbol":"285A.T","side":"BUY","policy_version":"risk-gate-0.1.0"}
 ticket={"permission_status":"ORDER_TICKET_READY","intent_hash":intent["intent_hash"],"merge_hash":intent["merge_hash"],"ticket_fingerprint":"fp-"+"a"*60}
 order=se.submit_shadow_order(intent,risk,ticket,known_orders=[],submitted_at=SUBMITTED,now=NOW)
 obs={"observed_at":NOW,"bid":1499.0,"ask":1500.0,"bid_qty":500,"ask_qty":500,"last_trade_price":1500.0,"last_trade_qty":100,"tick_size":1.0,"data_freshness":"OK"}
 return intent,se.evaluate_shadow_fill(order,obs,now=NOW)
class KnownPositionLedgerBoundaryTest(unittest.TestCase):
 def test_missing_position_id_rejected(self):
  i,o=valid_pair();out=sp.create_shadow_position(i,o,now=NOW,known_positions=[{}]);self.assertEqual(out["status"],"REJECTED");self.assertIn("REJECTED_KNOWN_POSITIONS_INVALID",out["reject_reasons"])
 def test_non_string_position_id_rejected(self):
  i,o=valid_pair();out=sp.create_shadow_position(i,o,now=NOW,known_positions=[{"position_id":123}]);self.assertEqual(out["status"],"REJECTED");self.assertIn("REJECTED_KNOWN_POSITIONS_INVALID",out["reject_reasons"])
