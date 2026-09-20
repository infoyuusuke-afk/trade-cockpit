import unittest
from scripts.backtest_15s import or_range,vwap,backtest_or_breakout

class Backtest15sTests(unittest.TestCase):
    def bars(self,n=65):
        xs=[]
        for i in range(n):
            xs.append({"ts":str(i),"open":100.0,"high":101.0,"low":99.0,"close":100.0,"volume":10.0})
        return xs
    def test_or15_is_first_60_15s_bars(self):
        x=self.bars();x[59]["high"]=105
        self.assertEqual(or_range(x,60),(105,99.0))
    def test_vwap(self):
        x=[{"high":101,"low":99,"close":100,"volume":10}]
        self.assertEqual(vwap(x),100)
    def test_entry_is_next_bar_open_not_breakout_close(self):
        x=self.bars();x[60]["close"]=102;x[61]["open"]=103;x[-1]["close"]=104
        t=backtest_or_breakout(x,"LONG",0.1)[0]
        self.assertEqual(t["entry"],103)
        self.assertEqual(t["strategy_key"],"OR15_BREAKOUT_LONG")
    def test_no_breakout_no_trade(self):
        self.assertEqual(backtest_or_breakout(self.bars(),"LONG"),[])
if __name__=="__main__": unittest.main()
