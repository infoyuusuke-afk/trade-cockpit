import sys,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import fill_model_calibration_adapter as a
import fill_model_calibration as c
JST=timezone(timedelta(hours=9))
S=datetime(2026,9,24,9,0,tzinfo=JST);P=datetime(2026,9,24,9,0,1,tzinfo=JST);O=datetime(2026,9,24,9,1,tzinfo=JST)
def pred(**kw):
 d={"shadow_order_id":"o1","model_version":"shadow-fill-model-0.1","submitted_at":S,"predicted_at":P,"order_type":"MARKET","side":"BUY","requested_qty":100,"predicted_fill_qty":100,"trading_unit":100};d.update(kw);return d
def out(**kw):
 d={"shadow_order_id":"o1","observation_source":"MANUAL_VERIFIED_EXECUTION","verified_by":"operator","evidence_ref":"private://execution/o1","evidence_meta":{"observation_source":"MANUAL_VERIFIED_EXECUTION","shadow_order_id":"o1","source_path":"data/private/execution/o1.json","sha256":"a"*64,"anchor":"b"*64},"observed_at":O,"observed_fill_qty":100};d.update(kw);return d
class T(unittest.TestCase):
 def test_builds_contract_valid_record(self):
  r=a.build_calibration_record(prediction=pred(),outcome=out());self.assertEqual(c.evaluate([r],now=O)["sample_size"],1)
 def test_rejects_ms2_market_data_as_actual_outcome(self):
  for source in ("MS2_TICKS","MS2_MARKET_SNAPSHOT","MS2_EXECUTION_OBSERVATION"):
   with self.subTest(source=source):
    with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(observation_source=source))
 def test_manual_source_requires_provenance(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(verified_by=""))
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(evidence_ref=""))
 def test_broker_export_requires_evidence_ref(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(observation_source="BROKER_EXECUTION_EXPORT",evidence_ref=""))
 def test_rejects_missing_or_invalid_evidence_metadata(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(evidence_meta=None))
  bad=out()["evidence_meta"].copy();bad["source_path"]="docs/o1.json"
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(evidence_meta=bad))
 def test_rejects_evidence_order_id_mismatch(self):
  bad=out()["evidence_meta"].copy();bad["shadow_order_id"]="other"
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(evidence_meta=bad))
 def test_rejects_model_self_observation(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(observation_source="SHADOW_FILL_MODEL"))
 def test_rejects_identity_mismatch(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(shadow_order_id="other"))
 def test_rejects_noncausal_outcome(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(observed_at=P))
 def test_context_requires_point_in_time_provenance(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(spread_yen=1.0,tick_size=1.0),outcome=out())
 def test_valid_context_survives_contract(self):
  r=a.build_calibration_record(prediction=pred(spread_yen=1.0,tick_size=1.0,context_observed_at=P,context_freshness="OK"),outcome=out());self.assertEqual(c.evaluate([r],now=O)["sample_size"],1)
 def test_price_is_all_or_nothing(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(predicted_fill_price=100.0),outcome=out())
 def test_observed_price_requires_positive_observed_fill(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(predicted_fill_price=100.0),outcome=out(observed_fill_qty=0,observed_fill_price=101.0))
 def test_rejects_missing_trading_unit(self):
  p=pred();del p["trading_unit"]
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=p,outcome=out())
 def test_rejects_non_lot_requested_quantity(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(requested_qty=150),outcome=out())
 def test_rejects_non_lot_predicted_fill(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(predicted_fill_qty=50),outcome=out())
 def test_rejects_non_lot_observed_fill(self):
  with self.assertRaises(ValueError):a.build_calibration_record(prediction=pred(),outcome=out(observed_fill_qty=50))
 def test_accepts_one_share_unit_instrument(self):
  r=a.build_calibration_record(prediction=pred(requested_qty=3,predicted_fill_qty=2,trading_unit=1),outcome=out(observed_fill_qty=1));self.assertEqual(c.evaluate([r],now=O)["sample_size"],1)
if __name__=="__main__":unittest.main()
