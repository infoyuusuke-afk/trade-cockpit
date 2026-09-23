import unittest
from scripts.cockpit_rest_day import apply_rest_day
class TestRestDay(unittest.TestCase):
 def test_market_continues_when_owner_unavailable(self):
  x=apply_rest_day({"entry":"AI_COCKPIT"},False)
  self.assertTrue(x["market_daily_should_continue"]);self.assertFalse(x["personal_trade_expected"])
 def test_no_penalty_for_no_trade(self):
  self.assertFalse(apply_rest_day({})["personal_trade_penalty"])
 def test_sensitive_actions_stay_locked(self):
  x=apply_rest_day({})
  self.assertFalse(x["real_submit_allowed"]);self.assertFalse(x["external_publish_allowed"])
if __name__=="__main__": unittest.main()
