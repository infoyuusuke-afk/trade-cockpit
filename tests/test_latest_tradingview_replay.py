import os,tempfile,time,unittest
from pathlib import Path
from scripts.run_latest_tradingview_replay import find_latest_replay

class LatestReplayTests(unittest.TestCase):
 def test_selects_latest_285a_csv_preferring_15s_hint(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   a=root/"TSE_285A, 1.csv";a.write_text("x")
   b=root/"TSE_285A, 15S_new.csv";b.write_text("x")
   self.assertEqual(find_latest_replay(root),b)
 def test_ignores_other_symbols(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/"TSE_7203, 15S.csv").write_text("x")
   with self.assertRaisesRegex(FileNotFoundError,"NO_REPLAY_CSV_FOR_SYMBOL"):
    find_latest_replay(root)
if __name__=="__main__":unittest.main()
