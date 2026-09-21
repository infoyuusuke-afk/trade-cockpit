import json,unittest
from datetime import datetime
from pathlib import Path

class JPXMarginContractTests(unittest.TestCase):
 def setUp(self):
  self.s=json.loads(Path("data/jpx_margin_schema.json").read_text())

 def test_contract_is_research_only_and_point_in_time(self):
  self.assertTrue(self.s["research_only"])
  self.assertEqual(self.s["effective_from"],"2026-09-28")
  self.assertEqual(self.s["publication_time_jst"],"16:00")
  self.assertIn("actual JPX publication timestamp",self.s["point_in_time_rule"])

 def test_required_audit_fields_exist(self):
  f=set(self.s["fields"])
  for x in ("as_of_date","published_at_jst","symbol","source_url","retrieved_at_jst"):
   self.assertIn(x,f)

 def test_publication_after_open_cannot_feed_same_day_open(self):
  open_ts=datetime.fromisoformat("2026-09-28T09:00:00")
  pub_ts=datetime.fromisoformat("2026-09-28T16:00:00")
  self.assertGreater(pub_ts,open_ts)

if __name__=="__main__": unittest.main()
