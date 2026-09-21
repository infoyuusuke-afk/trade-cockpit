import unittest
from scripts.preopen_context import validate_preopen_context

class PreopenContextTests(unittest.TestCase):
 def test_allows_only_information_observed_by_decision(self):
  c={"values":{"pts_return_pct":2.1,"futures_return_pct":0.8},
     "observed_at":{"pts_return_pct":"2026-09-18T08:50:00","futures_return_pct":"2026-09-18T08:59:00"}}
  v=validate_preopen_context(c,"2026-09-18T09:00:00")
  self.assertEqual(v["pts_return_pct"],2.1)

 def test_future_information_fails_closed(self):
  c={"values":{"futures_return_pct":1.0},
     "observed_at":{"futures_return_pct":"2026-09-18T09:00:15"}}
  with self.assertRaises(ValueError):
   validate_preopen_context(c,"2026-09-18T09:00:00")

 def test_unapproved_same_day_feature_fails_closed(self):
  c={"values":{"intraday_range_pct":5.0},
     "observed_at":{"intraday_range_pct":"2026-09-18T08:59:00"}}
  with self.assertRaises(ValueError):
   validate_preopen_context(c,"2026-09-18T09:00:00")

 def test_missing_observation_time_fails_closed(self):
  with self.assertRaises(ValueError):
   validate_preopen_context({"values":{"pts_return_pct":1.0},"observed_at":{}},"2026-09-18T09:00:00")

 def test_stale_fast_market_feature_fails_closed(self):
  c={"values":{"futures_return_pct":1.0},
     "observed_at":{"futures_return_pct":"2026-09-18T08:30:00"}}
  with self.assertRaises(ValueError):
   validate_preopen_context(c,"2026-09-18T09:00:00")

 def test_feature_specific_freshness_can_be_tightened(self):
  c={"values":{"pts_return_pct":1.0},
     "observed_at":{"pts_return_pct":"2026-09-18T08:50:00"},
     "max_age_sec":{"pts_return_pct":300}}
  with self.assertRaises(ValueError):
   validate_preopen_context(c,"2026-09-18T09:00:00")

if __name__=="__main__": unittest.main()
