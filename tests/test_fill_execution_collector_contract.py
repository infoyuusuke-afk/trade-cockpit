import sys,unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import fill_execution_collector_contract as c
NOW=datetime(2026,9,24,9,1,tzinfo=timezone.utc)
class T(unittest.TestCase):
 def manual(self,**kw):
  d={"observation_source":"MANUAL_VERIFIED_EXECUTION","shadow_order_id":"o1","evidence_ref":"private://execution/o1","observed_at":NOW,"observed_fill_qty":100,"observed_fill_price":1000.0,"verified_by":"operator"};d.update(kw);return d
 def test_manual_verified_input(self): self.assertEqual(c.validate_collector_input(self.manual()),[])
 def test_rejects_market_or_model_derived_outcome(self):
  for s in c.FORBIDDEN_DERIVED_SOURCES:
   self.assertIn("COLLECTOR_SOURCE_NOT_INDEPENDENT",c.validate_collector_input(self.manual(observation_source=s)))
 def test_manual_requires_verifier(self): self.assertIn("COLLECTOR_VERIFIER_REQUIRED",c.validate_collector_input(self.manual(verified_by="")))
 def test_broker_export_requires_execution_id(self):
  r=self.manual(observation_source="BROKER_EXECUTION_EXPORT");r.pop("verified_by")
  self.assertIn("COLLECTOR_BROKER_EXECUTION_ID_REQUIRED",c.validate_collector_input(r))
  r["broker_execution_id"]="exec-1";self.assertEqual(c.validate_collector_input(r),[])
 def test_rejects_invalid_qty_time_price(self):
  self.assertIn("COLLECTOR_FILL_QTY_INVALID",c.validate_collector_input(self.manual(observed_fill_qty=1.5)))
  self.assertIn("COLLECTOR_OBSERVED_AT_INVALID",c.validate_collector_input(self.manual(observed_at=datetime(2026,9,24,9,1))))
  self.assertIn("COLLECTOR_FILL_PRICE_INVALID",c.validate_collector_input(self.manual(observed_fill_price=0)))
if __name__=="__main__":unittest.main()
