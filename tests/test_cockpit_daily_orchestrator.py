import unittest
from scripts.cockpit_daily_orchestrator import plan_day,completion_summary
class TestDailyOrchestrator(unittest.TestCase):
 def test_market_daily_survives_no_trade_day(self):
  p=plan_day({"market_verified":True,"owner_traded":False})
  s=completion_summary(p)
  self.assertTrue(s["market_daily_planned"]);self.assertFalse(s["personal_trade_required"])
 def test_missing_market_fails_closed(self):
  p=plan_day({"market_verified":False,"owner_traded":False})
  m=[x for x in p["lanes"] if x["lane"]=="MARKET_DAILY"][0]
  self.assertEqual(m["reason"],"WAIT_DATA");self.assertFalse(m["required"])
 def test_development_can_feed_entertainment_without_trade(self):
  p=plan_day({"market_verified":True,"owner_traded":False,"development_events":2})
  self.assertTrue(completion_summary(p)["entertainment_candidate"])
 def test_no_side_effect_permissions(self):
  p=plan_day({"market_verified":True})
  self.assertFalse(p["real_submit_allowed"]);self.assertFalse(p["external_publish_allowed"])
if __name__=="__main__": unittest.main()
