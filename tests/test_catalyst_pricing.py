import unittest
from scripts.catalyst_pricing import pricing_features,sell_the_news_context

class CatalystPricingTests(unittest.TestCase):
 def test_prior_runup_is_descriptive_not_trade_signal(self):
  e={"event_id":"mna-1","state":"CONFIRMED"}
  p=pricing_features(e,100,115,2.0)
  x=sell_the_news_context(p,True)
  self.assertAlmostEqual(x["price_move_since_first_known_pct"],15)
  self.assertTrue(x["prior_runup"])
  self.assertTrue(x["sell_the_news_research_case"])
  self.assertNotIn("action",x)

 def test_prior_selloff_can_be_separate_confirmation_case(self):
  e={"event_id":"earn-1","state":"CONFIRMED"}
  p=pricing_features(e,100,90)
  x=sell_the_news_context(p,True)
  self.assertTrue(x["prior_selloff"])
  self.assertTrue(x["buy_the_news_research_case"])

 def test_invalid_prices_fail_closed(self):
  with self.assertRaises(ValueError):
   pricing_features({"event_id":"x","state":"RUMOR"},0,100)

if __name__=="__main__": unittest.main()
