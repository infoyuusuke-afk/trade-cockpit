"""OWNER 2026-11-19 「メルはザラバが終わるまで、トレードし続ける、手法も状況によって変化させる」「とめるかどうかはまかせる」: from 2026-11-20
the day methods follow the Nikkei at each entry (up → buy methods, down → short methods, else the plan's); the loss line is メル's choice
(daily_stop_pct of its plan; null = trade until the session ends).
Synthetic data only; virtual, no orders."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as live  # noqa: E402

FI_HEAD = "captured_at,key,code,configured_month,contract_code,contract_month_seen,status,name,price\n"


def series(day, pts):
    return FI_HEAD + "".join("%sT%s:05+09:00,N225,N225,,,,OK,日経225,%s\n" % (day, hm, p) for hm, p in pts)


class Regime(unittest.TestCase):
    def test_up_down_and_between(self):
        up = [("09:00", 50000), ("09:30", 50100), ("09:45", 50250)]
        self.assertEqual(live.mel_regime(up, "09:45"), "上げ")          # +0.5 % from open, +0.3 % in 15 min
        self.assertIsNone(live.mel_regime(up, "09:30"))                 # +0.2 % from open only
        dn = [("09:00", 50000), ("09:30", 49900), ("09:45", 49750)]
        self.assertEqual(live.mel_regime(dn, "09:45"), "下げ")
        flat = [("09:00", 50000), ("09:30", 50200), ("09:45", 50190)]
        self.assertIsNone(live.mel_regime(flat, "09:45"))               # up from open but not over the last 15 min
        self.assertIsNone(live.mel_regime([], "10:00"))

    def test_only_values_up_to_the_minute(self):
        pts = [("09:00", 50000), ("09:30", 50000), ("09:45", 50000), ("09:46", 51000)]
        self.assertIsNone(live.mel_regime(pts, "09:45"))                # the 09:46 jump is not known at 09:45

    def test_methods_by_day(self):
        plan = {"methods": ["R2", "ON_SHORT"]}
        up = [("09:00", 50000), ("09:30", 50100), ("09:45", 50250)]
        self.assertEqual(live.mel_day_methods(plan, "2026-11-19", "09:45", up), ("R2",))       # before the switch: the plan
        self.assertEqual(live.mel_day_methods(plan, "2026-11-20", "09:45", up), ("R1", "R4"))  # up: buy methods
        self.assertEqual(live.mel_day_methods(plan, "2026-11-20", "09:30", up), ("R2",))       # between: the plan


class Today(unittest.TestCase):
    def test_switch_and_no_stop_when_mel_sets_none(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d) / "records"
            day = "2026-11-20"
            (rec / day).mkdir(parents=True)
            (rec / day / "futures_index.csv").write_text(series(day, [("09:00", 50000), ("09:30", 50100), ("09:45", 50250),
                                                                      ("10:30", 50250), ("11:00", 49900), ("11:15", 49700)]), encoding="utf-8")
            lock = {"date": day, "plan": {"methods": ["R2"], "size_pct": 50, "max_mult": 3.0, "daily_stop_pct": None, "overnight": False}}
            tr = [
                {"kind": "day", "rule": "R2", "ticker": "1.T", "name": "a", "side": -1, "fill": 1000.0, "in": "09:20", "out": "09:25",
                 "ret": -5.0, "exit": 1050.0, "last": 1050.0, "ticks": []},          # between: the plan's R2, a big loss
                {"kind": "day", "rule": "R4", "ticker": "2.T", "name": "b", "side": 1, "fill": 1000.0, "in": "09:46", "out": "10:00",
                 "ret": 1.0, "exit": 1010.0, "last": 1010.0, "ticks": []},           # up: R4 taken although the plan has R2 only
                {"kind": "day", "rule": "R2", "ticker": "3.T", "name": "c", "side": -1, "fill": 1000.0, "in": "09:47", "out": "10:10",
                 "ret": 1.0, "exit": 990.0, "last": 990.0, "ticks": []},             # up: R2 not taken
                {"kind": "day", "rule": "R5", "ticker": "4.T", "name": "e", "side": -1, "fill": 1000.0, "in": "11:16", "out": "11:20",
                 "ret": 1.0, "exit": 990.0, "last": 990.0, "ticks": []}]             # down: R5 taken, no stop after the loss
            got = live.mel_today(rec, tr, lock, {"from": "2026-11-12", "days": [["2026-11-19", 0, 3000000, 0, 0, None]]}, "15:30")
        self.assertEqual([r["name"] for r in got["rows"]], ["a", "b", "e"])
        self.assertIsNone(got["stopped_at"])

    def test_mel_line_still_stops_from_the_20th(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d) / "records"
            day = "2026-11-20"
            (rec / day).mkdir(parents=True)
            (rec / day / "futures_index.csv").write_text(series(day, [("09:00", 50000), ("09:30", 50000)]), encoding="utf-8")
            lock = {"date": day, "plan": {"methods": ["R2"], "size_pct": 50, "max_mult": 3.0, "daily_stop_pct": 0.5, "overnight": False}}
            tr = [{"kind": "day", "rule": "R2", "ticker": "1.T", "name": "a", "side": -1, "fill": 1000.0, "in": "09:20", "out": "09:25",
                   "ret": -5.0, "exit": 1050.0, "last": 1050.0, "ticks": []},
                  {"kind": "day", "rule": "R2", "ticker": "3.T", "name": "c", "side": -1, "fill": 1000.0, "in": "09:47", "out": "10:10",
                   "ret": 1.0, "exit": 990.0, "last": 990.0, "ticks": []}]
            got = live.mel_today(rec, tr, lock, {"from": "2026-11-12", "days": [["2026-11-19", 0, 3000000, 0, 0, None]]}, "15:30")
        self.assertEqual([r["name"] for r in got["rows"]], ["a"])   # メル chose a 0.5 % line: it stops after the loss
        self.assertEqual(got["stopped_at"], "09:47")

    def test_before_the_20th_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d) / "records"
            lock = {"date": "2026-11-19", "plan": {"methods": ["R2"], "size_pct": 50, "max_mult": 3.0, "daily_stop_pct": 0.1, "overnight": False}}
            tr = [{"kind": "day", "rule": "R2", "ticker": "1.T", "name": "a", "side": -1, "fill": 1000.0, "in": "09:20", "out": "09:25",
                   "ret": -5.0, "exit": 1050.0, "last": 1050.0, "ticks": []},
                  {"kind": "day", "rule": "R2", "ticker": "3.T", "name": "c", "side": -1, "fill": 1000.0, "in": "09:47", "out": "10:10",
                   "ret": 1.0, "exit": 990.0, "last": 990.0, "ticks": []}]
            got = live.mel_today(rec, tr, lock, {"from": "2026-11-12", "days": [["2026-11-18", 0, 3000000, 0, 0, None]]}, "15:30")
        self.assertEqual([r["name"] for r in got["rows"]], ["a"])
        self.assertEqual(got["stopped_at"], "09:47")


if __name__ == "__main__":
    unittest.main()
