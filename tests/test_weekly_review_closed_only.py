"""OWNER 2026-10-24 「週間振り返り修正」: the Saturday review counts only closed trades, once each,
after the OWNER's contract cost (楽天証券ゼロコース・制度信用: commission 0, one day of interest)."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location("wt", Path(__file__).parents[1] / "scripts/weekly_tabs.py")
wt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wt)


def rec(date, ticker, side, result, exit_reason, pnl, entry=1000.0, r=1.0):
    return {"date": date, "name": ticker, "ticker": ticker, "side": side, "entry": entry, "shares": 100,
            "result": result, "exit_reason": exit_reason, "pnl_yen": pnl, "r": r, "simulated_fill": entry}


class ClosedOnly(unittest.TestCase):
    def build(self, rows):
        with tempfile.TemporaryDirectory() as d:
            wt.HISTORY = Path(d) / "h.json"
            wt.DATA = Path(d) / "data.json"
            wt.HISTORY.write_text(json.dumps(rows), encoding="utf-8")
            return wt.build_weekly(datetime(2026, 10, 24, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")))

    def test_open_marks_excluded_duplicates_once_cost_taken(self):
        rows = [
            rec("2026-10-19", "A", "LONG", "IFO利確1", "TARGET1", 5000),
            rec("2026-10-19", "A", "LONG", "IFO利確1", "TARGET1", 5000),          # same record twice
            rec("2026-10-20", "B", "SHORT", "IFO損切り", "STOP", -3000, entry=3650.0, r=-1.0),
            rec("2026-10-21", "C", "LONG", "時点評価・未決済", "OPEN_MARK", 9000),  # open mark, not a win
            rec("2026-10-22", "D", "LONG", "順序不明（成績除外）", None, 4000),
            rec("2026-10-23", "E", "LONG", "未発動（見送り）", "NOT_TRIGGERED", None),
            rec("2026-10-12", "F", "LONG", "IFO利確1", "TARGET1", 7000),          # previous week
        ]
        w = self.build(rows)
        self.assertEqual(w["count"], 2)
        self.assertEqual(w["wins"], 1)
        self.assertEqual(w["win_rate"], 50.0)
        self.assertEqual(w["open_excluded"], 2)
        self.assertEqual(w["duplicates_excluded"], 1)
        # A long 1000x100: ceil(100000*0.028/365)=8; B short 3650x100: ceil(365000*0.011/365)=11
        self.assertEqual(w["cost"], 8 + 11)
        self.assertEqual(w["pnl"], (5000 - 8) + (-3000 - 11))
        self.assertIn("ゼロコース", w["cost_basis"])
        html = wt.weekly_html(w)
        self.assertIn("決済済みの仮想取引", html)
        self.assertIn("未決済 2件・重複 1件", html)

    def test_no_closed_trade(self):
        w = self.build([rec("2026-10-21", "C", "LONG", "時点評価・未決済", "OPEN_MARK", 9000)])
        self.assertEqual((w["count"], w["win_rate"], w["pnl"], w["open_excluded"]), (0, 0, 0, 1))
        self.assertIn("確定取引なし", wt.weekly_html(w))


if __name__ == "__main__":
    unittest.main()
