import unittest
from scripts.backtest_15s import find_or5_vwap_signal,backtest_or5_vwap

class OR5VWAPTests(unittest.TestCase):
    def bars(self,n=30):
        return [{"ts":str(i),"open":100.0,"high":101.0,"low":99.0,"close":100.0,"volume":10.0} for i in range(n)]
    def test_long_reclaim_enters_next_bar(self):
        x=self.bars(); x[19]["close"]=99; x[20]["close"]=102; x[21]["open"]=103; x[-1]["close"]=104
        i=find_or5_vwap_signal(x,"LONG")
        self.assertEqual(i,20)
        t=backtest_or5_vwap(x,"LONG",0)[0]
        self.assertEqual(t["entry"],103)
        self.assertEqual(t["strategy_key"],"OR5_VWAP_RECLAIM_LONG")
    def test_short_reject_enters_next_bar(self):
        x=self.bars(); x[19]["close"]=101; x[20]["close"]=98; x[21]["open"]=97; x[-1]["close"]=96
        t=backtest_or5_vwap(x,"SHORT",0)[0]
        self.assertEqual(t["entry"],97)
        self.assertEqual(t["strategy_key"],"OR5_VWAP_REJECT_SHORT")
    def test_no_cross_no_trade(self):
        self.assertEqual(backtest_or5_vwap(self.bars(),"LONG"),[])
if __name__=="__main__": unittest.main()
