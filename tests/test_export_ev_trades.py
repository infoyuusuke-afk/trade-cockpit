#!/usr/bin/env python3
import unittest
from scripts.export_ev_trades import rows

class ExportEVTradesTests(unittest.TestCase):
    def test_unlabelled_history_is_excluded(self):
        self.assertEqual(rows([{"triggered":True,"entry":100,"close":110,"side":"LONG","score":100}]),[])
    def test_labelled_long_is_exported(self):
        r=rows([{"strategy_key":"OR15_LONG","triggered":True,"entry":100,"close":102,"side":"LONG","ticker":"285A.T"}])[0]
        self.assertEqual(r["strategy_key"],"OR15_LONG");self.assertAlmostEqual(r["pnl_pct"],2.0)
    def test_short_direction_is_inverted(self):
        r=rows([{"strategy_key":"OR15_SHORT","triggered":True,"entry":100,"close":98,"side":"SHORT"}])[0]
        self.assertAlmostEqual(r["pnl_pct"],2.0)
if __name__=="__main__":unittest.main()
