import unittest
from scripts.participant_regime import build_regime_features,descriptive_regime_tags,hierarchical_ev_key

class ParticipantRegimeTests(unittest.TestCase):
 def base(self):
  return {"price":12000,"turnover":60_000_000_000,"opening_volume_share":.30,
          "or5_width_pct":1.2,"or15_width_pct":2.1,"vwap_reversion_rate":.55,
          "intraday_range_pct":6.0}

 def test_missing_required_feature_fails_closed(self):
  x=self.base(); del x["turnover"]
  self.assertFalse(build_regime_features(x)["eligible"])

 def test_tags_are_descriptive_not_participant_identity(self):
  f=build_regime_features(self.base())["features"]
  tags=descriptive_regime_tags(f)
  self.assertIn("HIGH_PRICE",tags)
  self.assertIn("HIGH_TURNOVER",tags)
  self.assertNotIn("INSTITUTIONAL",tags)

 def test_ev_hierarchy_keeps_symbol_and_cluster_separate(self):
  x=hierarchical_ev_key("285A","R3","RISK_OFF","10:00","OR15_BREAK")
  self.assertNotEqual(x["cluster_key"],x["symbol_key"])
  self.assertIn("285A",x["symbol_key"])
  self.assertNotIn("285A",x["cluster_key"])

if __name__=="__main__": unittest.main()
