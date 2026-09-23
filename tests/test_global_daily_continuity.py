import unittest
from scripts.global_daily_continuity import continuity
class TestContinuity(unittest.TestCase):
 def test_no_trade_does_not_count_as_missing_market_brief(self):
  x=continuity([{"date_jst":"2026-09-24","market_expected":True,"market_brief_ready":True,"owner_traded":False}])
  self.assertEqual(x["missing_market_brief_dates"],[]);self.assertEqual(x["owner_trade_days"],0)
 def test_missing_expected_market_brief_is_visible(self):
  x=continuity([{"date_jst":"2026-09-24","market_expected":True,"market_brief_ready":False,"owner_traded":False}])
  self.assertEqual(x["missing_market_brief_dates"],["2026-09-24"])
if __name__=="__main__": unittest.main()
