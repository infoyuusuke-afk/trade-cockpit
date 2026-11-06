"""OWNER 2026-11-07: the records-to-gate conversion. Made-up rows only; no record or ledger is in the repository."""
import csv
from pathlib import Path
import tempfile
import unittest

from scripts import v10_gate_trades as conv
from scripts import v10_pass_gate as gate
from scripts import v10_signal_ev_table as ev


class Contract(unittest.TestCase):
    def test_a_short_that_made_money_is_positive(self):
        got = {"state": "FILLED", "side": -1, "gross_pct": 1.5, "fill_price": 1000.0}
        t = conv.from_replay(got, "2026-11-04", "R5")
        self.assertEqual(t["gross_pct"], 1.5)
        self.assertEqual(t["cost_pct"], ev.cost_pct(-1))
        # the gate does not turn it round again
        self.assertEqual(gate.net_pct(t), gate.net_pct(dict(t, side=1)))

    def test_ev_replay_signs_a_short_for_the_trade(self):
        got = ev._result(-1, 1000.0, 990.0, "TARGET", "09:00:00", "09:10:00")
        self.assertGreater(got["gross_pct"], 0)

    def test_unfilled_is_not_a_trade(self):
        self.assertIsNone(conv.from_replay({"state": "NOT_FILLED"}, "d", "R5"))
        self.assertIsNone(conv.from_replay({}, "d", "R5"))

    def test_ledger_cost_is_not_taken_twice(self):
        t = conv.from_r09_row({"status": "TRADE", "net_pct": "-0.513", "E": "2549.0", "date": "2026-11-06"})
        self.assertEqual((t["gross_pct"], t["cost_pct"], t["side"]), (-0.513, 0.0, -1))
        h = conv.from_h2_row({"status": "CLOSED", "net_pct": "-10.1", "entry": "2000", "entry_day": "2026-10-28", "rule": "H2-15_stop10"})
        self.assertEqual((h["gross_pct"], h["cost_pct"]), (-10.1, 0.0))

    def test_rows_that_are_not_trades(self):
        self.assertIsNone(conv.from_r09_row({"status": "NO_ARM", "net_pct": "", "E": ""}))
        self.assertIsNone(conv.from_h2_row({"status": "CANDIDATE", "net_pct": "", "entry": "", "entry_day": "", "rule": "H2-15"}))

    def test_an_open_h2_stays_open_for_the_gate(self):
        h = conv.from_h2_row({"status": "OPEN", "net_pct": "-28.4", "entry": "2489.5", "entry_day": "2026-10-28", "rule": "H2-15"})
        self.assertEqual(gate.evaluate([h])["closed"], 0)
        self.assertEqual(gate.evaluate([h])["open_ignored"], 1)


class Ticks(unittest.TestCase):
    def test_stale_rows_are_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ticks.csv"
            with open(p, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["captured_at", "ticker", "exchange_time", "price"])
                w.writerow(["2026-11-06 08:39:00", "1.T", "15:24:41", "9"])   # last night's print at the start
                w.writerow(["2026-11-06 09:01:00", "1.T", "15:24:41", "9"])   # the same print still on the sheet
                w.writerow(["2026-11-05 09:01:00", "1.T", "09:01:00", "9"])   # another day
                w.writerow(["2026-11-06 09:01:01", "2.T", "09:01:00", "5"])   # not wanted
                w.writerow(["2026-11-06 09:01:01", "1.T", "09:01:00", "10"])
            got = conv.load_ticks(p, "2026-11-06", {"1.T"})
        self.assertEqual([x[2] for x in got["1.T"]], [10.0])


class SharedDays(unittest.TestCase):
    def test_the_gate_can_cut_on_the_shared_calendar(self):
        def t(day):
            return {"status": gate.CLOSED, "day": day, "side": 1, "gross_pct": 1.0, "price": 1000.0, "cost_pct": 0.0}
        rows = [t("d3"), t("d4"), t("d4"), t("d5")]
        own = gate.evaluate(rows)
        shared = gate.evaluate(rows, calendar=["d1", "d2", "d3", "d4", "d5", "d6"])
        self.assertEqual(own["first_half"]["n"], 1)      # own days d3 | d4 d5
        self.assertEqual(shared["first_half"]["n"], 1)   # calendar d1 d2 d3 | d4 d5 d6
        rows = [t("d1"), t("d5"), t("d5"), t("d6")]
        self.assertEqual(gate.evaluate(rows)["first_half"]["n"], 1)
        self.assertEqual(gate.evaluate(rows, calendar=["d1", "d2", "d3", "d4", "d5", "d6"])["first_half"]["n"], 1)
        rows = [t("d2"), t("d3"), t("d6")]
        self.assertEqual(gate.evaluate(rows)["first_half"]["n"], 1)      # d2 | d3 d6
        self.assertEqual(gate.evaluate(rows, calendar=["d1", "d2", "d3", "d4", "d5", "d6"])["first_half"]["n"], 2)


if __name__ == "__main__":
    unittest.main()
