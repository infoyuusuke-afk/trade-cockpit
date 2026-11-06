"""OWNER 2026-11-06: the one pass gate. Each of the four conditions alone must fail a method. Synthetic trades only."""
import random
import unittest

from scripts import v10_pass_gate as gate


def trade(day, gross, side=1, status="CLOSED", price=1000.0, cost=0.0):
    return {"status": status, "day": day, "side": side, "gross_pct": gross, "price": price, "cost_pct": cost}


def days(n):
    return ["2026-10-%02d" % (i + 1) for i in range(n)]


def good(n=80):
    """Noisy wins in both halves: passes all four."""
    rng = random.Random(7)
    d = days(20)
    return [trade(d[i % 20], 1.0 + rng.uniform(-.5, 1.5) if i % 4 else -.6) for i in range(n)]


class FourConditions(unittest.TestCase):
    def test_a_good_method_passes(self):
        got = gate.evaluate(good())
        self.assertTrue(got["passed"], got)
        self.assertEqual(got["label"], "合格")
        self.assertEqual(got["failed"], [])

    def test_only_count_fails(self):
        got = gate.evaluate(good()[:29])
        self.assertFalse(got["passed"])
        self.assertEqual(got["failed"], ["count"])

    def test_thirty_closed_is_enough(self):
        self.assertTrue(gate.evaluate(good(30))["checks"]["count"])

    def test_only_mean_fails_because_of_cost(self):
        # gross is fine; the cost takes the mean below zero
        trades = [dict(t, cost_pct=0.0) for t in good()]
        mean = gate.evaluate(trades)["mean_net_pct"]
        got = gate.evaluate([dict(t, cost_pct=mean + .01) for t in trades])
        self.assertFalse(got["checks"]["mean"])
        self.assertIn("mean", got["failed"])
        self.assertTrue(got["checks"]["count"])

    def test_only_random_fails(self):
        # above zero in both halves but no better than a coin
        d = days(20)
        rng = random.Random(3)
        trades = [trade(d[i % 20], rng.choice((12.0, -11.8))) for i in range(40)]
        while True:
            got = gate.evaluate(trades)
            if got["checks"]["mean"] and got["checks"]["periods"]:
                break
            trades = [trade(d[i % 20], rng.choice((12.0, -11.8))) for i in range(40)]
        self.assertEqual(got["failed"], ["random"])

    def test_only_periods_fails(self):
        d = days(20)
        trades = [trade(d[i], 2.0 + i % 3 * .1) for i in range(10) for _ in range(5)]
        trades += [trade(d[i], -.1) for i in range(10, 20) for _ in range(5)]
        got = gate.evaluate(trades)
        self.assertEqual(got["failed"], ["periods"], got)

    def test_periods_need_both_halves(self):
        trades = [trade("2026-10-01", 1.0 + i * .01) for i in range(40)]
        self.assertFalse(gate.evaluate(trades)["checks"]["periods"])


class WhatCounts(unittest.TestCase):
    def test_open_trades_are_not_counted(self):
        trades = good()[:20] + [trade("2026-10-30", 5.0, status="OPEN") for _ in range(50)]
        got = gate.evaluate(trades)
        self.assertEqual(got["closed"], 20)
        self.assertEqual(got["open_ignored"], 50)
        self.assertIn("count", got["failed"])

    def test_mixing_marked_trades_raises_pf_and_the_gate_ignores_them(self):
        # regression: a marked-to-market value must not lift the PF
        closed = [trade("2026-10-%02d" % (i % 20 + 1), 1.0 if i % 2 else -1.0) for i in range(40)]
        marked = [dict(trade("2026-10-30", 3.0), status="MARKED") for _ in range(40)]
        only = gate.evaluate(closed)
        mixed_pf = gate.profit_factor([gate.net_pct(t) for t in closed + marked])
        self.assertGreater(mixed_pf, only["pf_net"])
        self.assertEqual(gate.evaluate(closed + marked)["pf_net"], only["pf_net"])
        self.assertEqual(gate.evaluate(closed + marked)["closed"], 40)

    def test_a_trade_without_cost_cannot_pass(self):
        trades = good()
        del trades[0]["cost_pct"]
        got = gate.evaluate(trades)
        self.assertEqual(got["invalid"], 1)
        self.assertIn("count", got["failed"])

    def test_no_trades(self):
        got = gate.evaluate([])
        self.assertFalse(got["passed"])
        self.assertEqual(set(got["failed"]), {"count", "mean", "random", "periods"})


class Cost(unittest.TestCase):
    def test_slippage_is_at_least_one_tick_each_side(self):
        self.assertAlmostEqual(gate.net_pct(trade("d", 1.0, price=1000.0, cost=.02)), 1.0 - .02 - .2)
        self.assertAlmostEqual(gate.net_pct(trade("d", 1.0, price=1000.0), slippage_ticks=0), .8)

    def test_tick_table_takes_the_coarse_side(self):
        self.assertEqual([gate.tick_size(p) for p in (3000, 3001, 5001, 30001)], [1, 5, 10, 50])

    def test_pf_without_a_loss_is_not_infinite(self):
        self.assertIsNone(gate.profit_factor([1.0, 0.0]))
        self.assertEqual(gate.profit_factor([2.0, 0.0, -1.0]), 2.0)

    def test_the_verdict_is_repeatable(self):
        self.assertEqual(gate.evaluate(good()), gate.evaluate(good()))


if __name__ == "__main__":
    unittest.main()
