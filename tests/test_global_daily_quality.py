import unittest
from scripts.global_daily_quality import validate_brief
class TestGlobalDailyQuality(unittest.TestCase):
 def base(self):
  return {"locale":"en","verified":True,"external_publish_allowed":False,"literal_translation":False,
   "sections":{"index_context":{},"market_leaders":[],"themes":[],"notable_moves":[],"unknowns":[]},
   "claims":[{"type":"OBSERVED","text":"x","evidence_refs":["e1"]}]}
 def test_valid(self): self.assertEqual(validate_brief(self.base()),[])
 def test_fact_needs_evidence(self):
  x=self.base();x["claims"][0]["evidence_refs"]=[]
  self.assertIn("CLAIM_WITHOUT_EVIDENCE",validate_brief(x))
 def test_global_not_literal_translation(self):
  x=self.base();x["literal_translation"]=True
  self.assertIn("GLOBAL_LITERAL_TRANSLATION_FORBIDDEN",validate_brief(x))
 def test_publication_locked(self):
  x=self.base();x["external_publish_allowed"]=True
  self.assertIn("PUBLICATION_NOT_LOCKED",validate_brief(x))
if __name__=="__main__": unittest.main()
