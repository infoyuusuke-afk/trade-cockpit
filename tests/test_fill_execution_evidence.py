import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import fill_execution_evidence as e
class T(unittest.TestCase):
 def meta(self,**kw):
  d={"observation_source":"MANUAL_VERIFIED_EXECUTION","shadow_order_id":"o1","source_path":"data/private/execution/2026-09-24/o1.json","sha256":"a"*64,"anchor":"b"*64};d.update(kw);return d
 def test_accepts_private_bound_metadata(self): self.assertEqual(e.validate_execution_evidence(self.meta(),shadow_order_id="o1",observation_source="MANUAL_VERIFIED_EXECUTION"),[])
 def test_rejects_public_or_traversal_path(self):
  for p in ("docs/o1.json","../data/private/o1.json","data/private/../docs/o1.json"):
   self.assertIn("EVIDENCE_PATH_NOT_PRIVATE",e.validate_execution_evidence(self.meta(source_path=p),shadow_order_id="o1",observation_source="MANUAL_VERIFIED_EXECUTION"))
 def test_rejects_identity_mismatch(self): self.assertIn("EVIDENCE_ORDER_ID_MISMATCH",e.validate_execution_evidence(self.meta(shadow_order_id="other"),shadow_order_id="o1",observation_source="MANUAL_VERIFIED_EXECUTION"))
 def test_rejects_source_mismatch(self): self.assertIn("EVIDENCE_SOURCE_MISMATCH",e.validate_execution_evidence(self.meta(observation_source="BROKER_EXECUTION_EXPORT"),shadow_order_id="o1",observation_source="MANUAL_VERIFIED_EXECUTION"))
 def test_rejects_bad_digest_or_anchor(self):
  self.assertIn("EVIDENCE_SHA256_INVALID",e.validate_execution_evidence(self.meta(sha256="x"),shadow_order_id="o1",observation_source="MANUAL_VERIFIED_EXECUTION"))
  self.assertIn("EVIDENCE_ANCHOR_INVALID",e.validate_execution_evidence(self.meta(anchor="x"),shadow_order_id="o1",observation_source="MANUAL_VERIFIED_EXECUTION"))
if __name__=="__main__":unittest.main()
