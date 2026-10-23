"""OWNER 2026-10-24 「相関の仕組みの直し」: US previous-day relations are judged on the Tokyo opening gap
over the whole history, both halves and the big US days; Korea's previous day, the Nintendo hypothesis
and automatically picked pairs are removed. Synthetic data only."""
import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("cs", Path(__file__).parents[1] / "scripts/correlation_scan.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


def frames(n, link, seed):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2024-06-03", periods=n)
    us = rng.normal(0, 2.5, n)                       # US daily return, % (dated the day before Tokyo)
    us_close = pd.Series(100 * np.cumprod(1 + us / 100), index=days - pd.Timedelta(days=1))
    gap = link * us + rng.normal(0, 1.5, n)          # Tokyo gap follows the US day by `link`
    after = rng.normal(0, 1.5, n)                    # the move after the open does not
    close, opens, prev = [], [], 1000.0
    for g, a in zip(gap, after):
        o = prev * (1 + g / 100)
        c = o * (1 + a / 100)
        opens.append(o)
        close.append(c)
        prev = c
    jp = pd.DataFrame({"Open": opens, "Close": close}, index=days)
    return jp, us_close


class GapTest(unittest.TestCase):
    def test_real_lead_is_confirmed_on_the_gap_not_after_the_open(self):
        jp, us = frames(300, 0.6, 1)
        r = cs.gap_test(jp, us)
        state, score = cs.gap_verdict(r)
        self.assertEqual(state, "確認")
        self.assertGreater(r["corr_all"], 0.5)
        self.assertLess(abs(r["corr_after_open"]), 0.2)
        self.assertGreaterEqual(r["big_days"], cs.MIN_BIG_DAYS)
        self.assertGreaterEqual(score, 65)

    def test_no_link_is_not_confirmed(self):
        jp, us = frames(300, 0.0, 2)
        self.assertIn(cs.gap_verdict(cs.gap_test(jp, us))[0], ("不成立", "不安定"))

    def test_short_history_is_not_judged(self):
        jp, us = frames(80, 0.6, 3)
        self.assertEqual(cs.gap_verdict(cs.gap_test(jp, us))[0], "根拠不足")

    def test_removed_relations_are_listed_and_not_scanned(self):
        peers = {p for _, p, _ in cs.US_LEAD}
        self.assertFalse(peers & {"000660.KS", "005930.KS", "7974.T"})
        self.assertEqual(len(cs.REMOVED), 3)


if __name__ == "__main__":
    unittest.main()
