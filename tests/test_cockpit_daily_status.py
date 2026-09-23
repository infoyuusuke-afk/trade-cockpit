import unittest
from scripts.cockpit_daily_status import build_status
class TestDailyStatus(unittest.TestCase):
 def test_no_trade_market_can_be_ready(self):
  o={"owner_traded":False,"lanes":[{"lane":"MARKET_DAILY","reason":"verified_market_day"}]}
  p={"status":"READY_FOR_OWNER_REVIEW"}
  x=build_status(o,[],p)
  self.assertEqual(x["market_daily"],"READY_FOR_REVIEW");self.assertEqual(x["trade_analysis"],"NO_PERSONAL_TRADE")
 def test_wait_data_visible(self):
  o={"owner_traded":False,"lanes":[{"lane":"MARKET_DAILY","reason":"WAIT_DATA"}]}
  self.assertEqual(build_status(o)["market_daily"],"WAIT_DATA")
 def test_quality_block_visible(self):
  o={"lanes":[{"lane":"MARKET_DAILY","reason":"verified_market_day"}]}
  self.assertEqual(build_status(o,["CLAIM_WITHOUT_EVIDENCE"])["market_daily"],"QUALITY_BLOCKED")
if __name__=="__main__": unittest.main()
