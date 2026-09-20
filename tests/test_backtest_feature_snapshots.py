import unittest
from scripts.backtest_15s import backtest_or_breakout,backtest_or5_vwap
class BacktestFeatureSnapshotTests(unittest.TestCase):
    def bars(self,n=70):
        return [{"ts":str(i),"open":100.0,"high":101.0,"low":99.0,"close":100.0,"volume":10.0} for i in range(n)]
    def test_or15_trade_has_signal_time_features(self):
        x=self.bars();x[60]["close"]=102;x[60]["volume"]=20;x[61]["open"]=103
        t=backtest_or_breakout(x,"LONG",0,prev_close=98,market={"nikkei_return_pct":0.5})[0]
        self.assertIn("volume_ratio_20",t);self.assertEqual(t["nikkei_return_pct"],0.5)
        self.assertAlmostEqual(t["gap_pct"],(100/98-1)*100)
    def test_or5_trade_keeps_missing_market_as_null(self):
        x=self.bars();x[19]["close"]=99;x[20]["close"]=102;x[21]["open"]=103
        t=backtest_or5_vwap(x,"LONG",0)[0]
        self.assertIsNone(t["futures_return_pct"])
if __name__=="__main__": unittest.main()
