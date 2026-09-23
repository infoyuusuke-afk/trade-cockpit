import importlib.util
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
ec=load("ec_c103","scripts/execution_contract.py");se=load("se_c103","scripts/shadow_execution.py")
JST=timezone(timedelta(hours=9));NOW=datetime(2026,9,17,9,0,tzinfo=JST);SUBMITTED=NOW-timedelta(seconds=10)
def inputs():
 i=ec.build_intent(symbol="285A.T",side="BUY",quantity=100,order_type="MARKET",strategy_id="s",strategy_version="1",decision_snapshot_id="d",signal_known_at="2026-09-17T08:55:00+09:00",risk_policy_version="risk-gate-0.1.0",execution_policy_version="exec-v0.1",shadow_fill_model_version="shadow-fill-model-0.1",merge_hash="m"*64,planned_entry=1500.0,planned_stop=1450.0,planned_target=1600.0)
 r={"decision":"PASS","merge_hash":"m"*64,"allowed_qty":100,"symbol":"285A.T","side":"BUY","policy_version":"risk-gate-0.1.0"}
 t={"permission_status":"ORDER_TICKET_READY","intent_hash":i["intent_hash"],"merge_hash":i["merge_hash"],"ticket_fingerprint":"fp-"+"a"*60}
 return i,r,t
class KnownOrderLedgerBoundaryTest(unittest.TestCase):
 def test_missing_shadow_order_id_rejected(self):
  i,r,t=inputs();o=se.submit_shadow_order(i,r,t,known_orders=[{}],submitted_at=SUBMITTED,now=NOW);self.assertEqual(o["status"],"REJECTED");self.assertIn("REJECTED_KNOWN_ORDERS_INVALID",o["reject_reasons"])
 def test_non_string_shadow_order_id_rejected(self):
  i,r,t=inputs();o=se.submit_shadow_order(i,r,t,known_orders=[{"shadow_order_id":123}],submitted_at=SUBMITTED,now=NOW);self.assertEqual(o["status"],"REJECTED");self.assertIn("REJECTED_KNOWN_ORDERS_INVALID",o["reject_reasons"])
