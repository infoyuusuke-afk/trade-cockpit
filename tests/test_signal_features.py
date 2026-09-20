import unittest
from scripts.signal_features import signal_features
class SignalFeatureTests(unittest.TestCase):
    def bars(self,n=21):
        return [{"open":100.0,"high":101.0,"low":99.0,"close":100.0,"volume":10.0} for _ in range(n)]
    def test_volume_ratio_and_gap(self):
        x=self.bars();x[20]["volume"]=20
        f=signal_features(x,20,prev_close=98)
        self.assertEqual(f["volume_ratio_20"],2.0)
        self.assertAlmostEqual(f["gap_pct"],(100/98-1)*100)
    def test_market_context_is_null_when_missing(self):
        f=signal_features(self.bars(),20)
        self.assertIsNone(f["nikkei_return_pct"])
        self.assertIsNone(f["futures_return_pct"])
    def test_market_context_is_passed_not_inferred(self):
        f=signal_features(self.bars(),20,market={"nikkei_return_pct":1.2})
        self.assertEqual(f["nikkei_return_pct"],1.2)
        self.assertIsNone(f["topix_return_pct"])
if __name__=="__main__": unittest.main()
