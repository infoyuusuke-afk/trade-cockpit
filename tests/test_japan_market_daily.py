import unittest
from scripts.japan_market_daily import build_daily_briefs
class TestJapanMarketDaily(unittest.TestCase):
 def base(self):
  return {"date_jst":"2026-09-24","nikkei":{"close":1},"topix":{"close":1},"themes":["semiconductors"],"notable_moves":[],"evidence":["source-a"],"verified":True,"sanitized":True}
 def test_builds_jp_and_global_even_without_trade(self):
  x=self.base();x["owner_traded"]=False
  out=build_daily_briefs(x)
  self.assertEqual([z["locale"] for z in out],["ja-JP","en"])
  self.assertTrue(all(z["owner_traded"] is False for z in out))
 def test_publish_requires_owner(self):
  self.assertTrue(all(z["owner_approval_required"] and not z["external_publish_allowed"] for z in build_daily_briefs(self.base())))
 def test_unverified_rejected(self):
  x=self.base();x["verified"]=False
  with self.assertRaises(ValueError): build_daily_briefs(x)
if __name__=="__main__": unittest.main()
