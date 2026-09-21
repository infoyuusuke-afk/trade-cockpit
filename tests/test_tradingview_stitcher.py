import unittest
from scripts.tradingview_stitcher import stitch_segments

def r(ts,c=100):
 return {"symbol":"285A","market_date":ts[:10],"timestamp":ts,
         "open":100,"high":101,"low":99,"close":c,"volume":10}

class StitcherTests(unittest.TestCase):
 def test_identical_overlap_deduplicates(self):
  a=[r("2026-09-18T09:00:00+09:00"),r("2026-09-18T09:00:15+09:00")]
  b=[r("2026-09-18T09:00:15+09:00"),r("2026-09-18T09:00:30+09:00")]
  x=stitch_segments([a,b])
  self.assertEqual(len(x["rows"]),3);self.assertEqual(x["audit"]["duplicate_overlap_rows"],1)
 def test_overlap_mismatch_fails(self):
  a=[r("2026-09-18T09:00:00+09:00",100)]
  b=[r("2026-09-18T09:00:00+09:00",101)]
  with self.assertRaises(ValueError):stitch_segments([a,b])
 def test_intraday_gap_is_audited_not_filled(self):
  x=stitch_segments([[r("2026-09-18T09:00:00+09:00"),r("2026-09-18T09:00:45+09:00")]])
  self.assertEqual(x["audit"]["gap_count"],1);self.assertFalse(x["audit"]["interpolation_used"])
 def test_overnight_gap_not_flagged(self):
  x=stitch_segments([[r("2026-09-17T15:30:00+09:00"),r("2026-09-18T09:00:00+09:00")]])
  self.assertEqual(x["audit"]["gap_count"],0)
if __name__=="__main__":unittest.main()
