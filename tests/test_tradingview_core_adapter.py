import tempfile,unittest
from pathlib import Path
from scripts.tradingview_core_adapter import adapt_csv,resolve_columns

class TradingViewCoreAdapterTests(unittest.TestCase):
 def test_aliases_and_jst_core_output(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.csv"
   p.write_text("time,open,high,low,close,volume\n2026-09-18T09:00:00+09:00,100,101,99,100.5,1000\n",encoding="utf-8")
   x=adapt_csv(p,"285A")[0]
   self.assertEqual(x["symbol"],"285A");self.assertEqual(x["market_date"],"2026-09-18")
   self.assertEqual(x["source"],"TRADINGVIEW_15S")
 def test_unknown_schema_fails(self):
  with self.assertRaises(ValueError):resolve_columns(["foo","open","high","low","close","volume"])
 def test_invalid_ohlc_fails(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.csv";p.write_text("time,open,high,low,close,volume\n2026-09-18 09:00:00,100,99,98,100,1\n")
   with self.assertRaises(ValueError):adapt_csv(p,"285A")
 def test_non_increasing_time_fails(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.csv";p.write_text("time,open,high,low,close,volume\n2026-09-18 09:00:15,100,101,99,100,1\n2026-09-18 09:00:00,100,101,99,100,1\n")
   with self.assertRaises(ValueError):adapt_csv(p,"285A")
if __name__=="__main__":unittest.main()
