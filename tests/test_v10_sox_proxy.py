"""OWNER 2026-11-10 「SOXの目安の計算と音声のスクリプトをGitHubに上げて監査に回して」. Synthetic numbers only."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import unittest

from scripts import v10_sox_proxy as sp

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))


def series(n, f):
    d0 = datetime(2025, 1, 1)
    return {(d0 + timedelta(days=i)).date().isoformat(): f(i) for i in range(n)}


class Fit(unittest.TestCase):
    def test_slope_two(self):
        nq = series(200, lambda i: 100 * (1.001 if i % 2 else 0.999) ** i)
        # SOX day change = 2 × the futures day change exactly
        keys = sorted(nq)
        sox = {keys[0]: 1000.0}
        for a, b in zip(keys, keys[1:]):
            sox[b] = sox[a] * (1 + 2 * (nq[b] / nq[a] - 1))
        f = sp.fit_beta(sox, nq)
        self.assertAlmostEqual(f["beta"], 2.0, places=2)
        self.assertLess(f["err_pct"], 0.01)
        self.assertEqual(f["days"], 199)

    def test_too_short_or_flat(self):
        with self.assertRaises(ValueError):
            sp.fit_beta(series(50, lambda i: 100 + i), series(50, lambda i: 100 + i))
        with self.assertRaises(ValueError):
            sp.fit_beta(series(200, lambda i: 100 + i), series(200, lambda i: 100.0))


class Close(unittest.TestCase):
    def test_new_york_close_winter_and_summer(self):
        self.assertEqual(datetime.fromtimestamp(sp.us_close_ts("2026-11-06"), JST).strftime("%m-%d %H:%M"), "11-07 06:00")   # EST
        self.assertEqual(datetime.fromtimestamp(sp.us_close_ts("2026-10-30"), JST).strftime("%m-%d %H:%M"), "10-31 05:00")   # EDT
        self.assertEqual(datetime.fromtimestamp(sp.us_close_ts("2026-03-06"), JST).strftime("%H:%M"), "06:00")   # before 3/8
        self.assertEqual(datetime.fromtimestamp(sp.us_close_ts("2026-03-09"), JST).strftime("%H:%M"), "05:00")   # after 3/8

    def test_base_is_the_bar_before_the_close(self):
        t0 = sp.us_close_ts("2026-11-06")
        bars = [(t0 - 600, 100.0), (t0 - 300, 101.0), (t0, 150.0), (t0 + 300, 160.0)]
        self.assertEqual(sp.base_price(bars, t0), 101.0)
        self.assertIsNone(sp.base_price([(t0, 1.0)], t0))


class Doc(unittest.TestCase):
    SC = {"real_submit_allowed": False, "trade_instruction": False, "close": 1000.0, "as_of": "2026-11-06", "zone": {"from": 1100, "to": 1200}}
    FIT = {"beta": 2.0, "err_pct": 1.4, "corr": 0.88, "days": 250}

    def bars(self, now_price):
        t0 = sp.us_close_ts("2026-11-06")
        return [(t0 - 300, 100.0), (t0 + 3600 * 30, now_price)]

    def test_estimate_and_states(self):
        d = sp.make_doc("2026-11-09", "10:00", self.SC, self.FIT, self.bars(105.0))
        self.assertEqual((d["estimate"], d["state"], d["nq_change_pct"]), (1100, "IN", 5.0))
        self.assertIs(d["real_submit_allowed"], False)
        self.assertIs(d["trade_instruction"], False)
        self.assertEqual(d["schema_version"], "100b-v10-sox-proxy-v1")
        self.assertEqual(sp.make_doc("2026-11-09", "10:00", self.SC, self.FIT, self.bars(104.0))["state"], "NEAR")   # 1080 ≥ 1078
        self.assertEqual(sp.make_doc("2026-11-09", "10:00", self.SC, self.FIT, self.bars(101.0))["state"], "BELOW")
        self.assertEqual(sp.make_doc("2026-11-09", "10:00", self.SC, self.FIT, self.bars(115.0))["state"], "ABOVE")

    def test_refuses_bad_inputs(self):
        for sc in (dict(self.SC, real_submit_allowed=True), dict(self.SC, zone={"from": 1200, "to": 1100}), dict(self.SC, close=0)):
            with self.assertRaises(ValueError):
                sp.make_doc("2026-11-09", "10:00", sc, self.FIT, self.bars(105.0))
        t0 = sp.us_close_ts("2026-11-06")
        with self.assertRaises(ValueError):   # no price after the close yet
            sp.make_doc("2026-11-09", "10:00", self.SC, self.FIT, [(t0 - 600, 100.0), (t0 - 300, 101.0)])

    def test_session(self):
        self.assertTrue(sp.in_session("09:00") and sp.in_session("15:30"))
        self.assertFalse(sp.in_session("08:59") or sp.in_session("15:31"))


class Voice(unittest.TestCase):
    def test_once_a_day_each(self):
        t, s = sp.what_to_say("NEAR", {}, "10:00")
        self.assertEqual((t, s), (sp.SAY_NEAR, {"NEAR": "10:00"}))
        self.assertEqual(sp.what_to_say("NEAR", s, "10:05")[0], None)
        t, s = sp.what_to_say("IN", s, "10:30")
        self.assertEqual((t, s), (sp.SAY_IN, {"NEAR": "10:00", "IN": "10:30"}))
        self.assertIsNone(sp.what_to_say("IN", s, "11:00")[0])
        # IN first also covers NEAR
        t, s = sp.what_to_say("IN", {}, "09:10")
        self.assertEqual(s, {"IN": "09:10", "NEAR": "09:10"})
        self.assertIsNone(sp.what_to_say("NEAR", s, "09:15")[0])
        self.assertIsNone(sp.what_to_say("BELOW", {}, "09:15")[0])

    def test_words_say_it_is_not_sox(self):
        for t in (sp.SAY_IN, sp.SAY_NEAR):
            self.assertIn("SOXそのものではありません", t)

    def test_no_paths_network_or_orders(self):
        src = (ROOT / "scripts" / "v10_sox_proxy.py").read_text(encoding="utf-8")
        for w in ("urllib", "requests", "subprocess", "open(", "Path(", "C:\\\\", "Desktop", "announce", "submit_order"):
            self.assertNotIn(w, src)


if __name__ == "__main__":
    unittest.main()
