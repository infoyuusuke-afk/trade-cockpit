import unittest
from scripts.tradingview_source_crosscheck import crosscheck_sources
def m(ts,c=100):
 return {"timestamp":ts,"open":100,"high":101,"low":99,"close":c,"volume":10,"source_timeframe":"15S"}
def r(ts,c=100):
 x=m(ts,c);x.pop("source_timeframe");return x
class SourceCrosscheckTests(unittest.TestCase):
 def test_exact_overlap_passes(self):
  x=crosscheck_sources([m("t1")],[r("t1")])
  self.assertEqual(x["status"],"PASS");self.assertEqual(x["matched_n"],1)
 def test_difference_is_reported_not_repaired(self):
  x=crosscheck_sources([m("t1",101)],[r("t1",100)])
  self.assertEqual(x["status"],"MISMATCH");self.assertEqual(x["mismatch_n"],1)
  self.assertFalse(x["auto_repair"])
 def test_one_sided_rows_are_counted(self):
  x=crosscheck_sources([m("t1"),m("t2")],[r("t1"),r("t3")])
  self.assertEqual(x["only_mcp_n"],1);self.assertEqual(x["only_replay_n"],1)
 def test_wrong_timeframe_fails(self):
  x=m("t1");x["source_timeframe"]="5"
  with self.assertRaises(ValueError):crosscheck_sources([x],[r("t1")])
if __name__=="__main__":unittest.main()
