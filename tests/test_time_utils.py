import unittest
from scripts.time_utils import parse_market_ts,assert_observed_by

class TimeUtilsTests(unittest.TestCase):
 def test_utc_and_jst_are_same_instant(self):
  a=parse_market_ts("2026-09-18T00:00:00Z")
  b=parse_market_ts("2026-09-18T09:00:00+09:00")
  self.assertEqual(a,b)

 def test_naive_market_time_defaults_to_jst(self):
  a=parse_market_ts("2026-09-18T09:00:00")
  b=parse_market_ts("2026-09-18T09:00:00+09:00")
  self.assertEqual(a,b)

 def test_future_information_fails_across_offsets(self):
  with self.assertRaises(ValueError):
   assert_observed_by("2026-09-18T00:00:01Z","2026-09-18T09:00:00+09:00")

if __name__=="__main__": unittest.main()
