import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / 'scripts/shadow_fill_model.py'
spec = importlib.util.spec_from_file_location('sfm', SCRIPT_PATH)
sfm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sfm)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 17, 9, 0, 0, tzinfo=JST)
SUBMITTED_AT = NOW - timedelta(seconds=10)


def observation(**overrides):
    base = {
        "observed_at": NOW,
        "bid": 1499.0, "ask": 1500.0,
        "bid_qty": 500, "ask_qty": 500,
        "last_trade_price": 1500.0, "last_trade_qty": 100,
        "tick_size": 1.0,
        "data_freshness": "OK",
    }
    base.update(overrides)
    return base


class ValidateObservationTests(unittest.TestCase):
    def test_valid_observation_passes(self):
        ok, reasons = sfm.validate_observation(observation(), now=NOW)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_non_dict_observation_rejected(self):
        ok, reasons = sfm.validate_observation("not-a-dict", now=NOW)
        self.assertFalse(ok)
        self.assertIn("OBSERVATION_INVALID_TYPE", reasons)


class MarketFillTests(unittest.TestCase):
    """Golden #8/#9/#10: MARKET entry fill model."""

    def test_golden_8_market_buy_uses_ask_never_mid_or_last(self):
        obs = observation(bid=1400.0, ask=1500.0, last_trade_price=9999.0)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["reference_price"], 1500.0)
        self.assertEqual(result["avg_fill_price"], 1500.0)
        self.assertEqual(result["filled_qty"], 100)
        self.assertEqual(result["fill_confidence"], "PROBABLE")

    def test_golden_9_market_sell_uses_bid_never_mid_or_last(self):
        obs = observation(bid=1400.0, ask=1500.0, last_trade_price=9999.0)
        result = sfm.evaluate_market_fill(side="SELL", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["reference_price"], 1400.0)
        self.assertEqual(result["avg_fill_price"], 1400.0)
        self.assertEqual(result["filled_qty"], 100)

    def test_golden_10_visible_qty_insufficient_partial_only(self):
        obs = observation(ask_qty=40)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 40)
        self.assertEqual(result["fill_reason"], "PARTIAL_FILL_VISIBLE_QTY_ONLY")

    def test_full_fill_when_visible_qty_sufficient(self):
        obs = observation(ask_qty=500)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 100)
        self.assertEqual(result["fill_reason"], "FULL_FILL_VISIBLE_QTY_SUFFICIENT")

    def test_missing_ask_qty_does_not_assume_full_fill(self):
        obs = observation(ask_qty=None)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "VISIBLE_QTY_UNAVAILABLE")

    def test_zero_visible_qty_no_fill(self):
        obs = observation(ask_qty=0)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "VISIBLE_QTY_ZERO")


class MarketSubmittedAtGateTests(unittest.TestCase):
    """Phase 5.0.2 hardening Blocker 1（C-060-GPT comment 5708285624）:
    MARKETもLIMIT同様、Shadow submit後のobservationのみを使う——従来
    MARKETだけこの制約が無く、submit前のquoteでもfillできてしまっていた。"""

    def test_hardening_golden_1_market_observation_before_submitted_at_no_fill(self):
        obs = observation(observed_at=SUBMITTED_AT - timedelta(seconds=1))
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW,
                                           submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "OBSERVATION_BEFORE_SUBMISSION")

    def test_market_observation_exactly_at_submitted_at_no_fill(self):
        obs = observation(observed_at=SUBMITTED_AT)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW,
                                           submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "OBSERVATION_BEFORE_SUBMISSION")

    def test_market_naive_submitted_at_rejected(self):
        obs = observation(observed_at=NOW)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW,
                                           submitted_at=datetime(2026, 9, 17, 8, 59, 0))
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "SUBMITTED_AT_NOT_TIMEZONE_AWARE")

    def test_market_observation_after_submitted_at_fills_normally(self):
        obs = observation(observed_at=SUBMITTED_AT + timedelta(seconds=1))
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW,
                                           submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 100)


class SlippageNotModeledTests(unittest.TestCase):
    """Phase 5.0.1 hardening Blocker 3（C-057R-GPT comment 5707963859）:
    v0.1はslippageを実測/推定していないため、fill時も常にNoneのまま
    ——0.0を「計測したらゼロだった」と誤記録しない。"""

    def test_hardening_golden_8_market_full_fill_slippage_not_modeled(self):
        obs = observation(ask_qty=500)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 100)
        self.assertIsNone(result["slippage_yen"])
        self.assertIsNone(result["slippage_bps"])
        self.assertEqual(result["slippage_model_status"], "NOT_MODELED_V0_1")

    def test_hardening_golden_8_market_partial_fill_slippage_not_modeled(self):
        obs = observation(ask_qty=40)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 40)
        self.assertIsNone(result["slippage_yen"])
        self.assertIsNone(result["slippage_bps"])
        self.assertEqual(result["slippage_model_status"], "NOT_MODELED_V0_1")

    def test_no_fill_slippage_model_status_is_none_too(self):
        """fillしていない場合はslippageの問い自体が成立しないため、
        slippage_model_statusもNoneのまま（"NOT_MODELED_V0_1"にしない）。"""
        obs = observation(ask_qty=0)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertIsNone(result["slippage_yen"])
        self.assertIsNone(result["slippage_model_status"])


class DataQualityGuardTests(unittest.TestCase):
    """Golden #14/#15/#16: stale/missing/future/malformed/crossed data -> no fill.
    MARKET経由で代表確認する（validate_observation()はLIMITとも共通）。"""

    def test_golden_14_stale_data_no_fill(self):
        obs = observation(data_freshness="STALE")
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_confidence"], "UNOBSERVABLE")

    def test_golden_14_missing_data_no_fill(self):
        obs = observation(data_freshness="MISSING")
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)

    def test_golden_14_future_timestamp_no_fill(self):
        obs = observation(observed_at=NOW + timedelta(seconds=5))
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)

    def test_golden_15_naive_timestamp_no_fill(self):
        obs = observation(observed_at=datetime(2026, 9, 17, 9, 0, 0))
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)

    def test_golden_15_non_datetime_timestamp_no_fill(self):
        obs = observation(observed_at="2026-09-17T09:00:00+09:00")
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)

    def test_golden_16_bid_greater_than_ask_no_fill(self):
        obs = observation(bid=1501.0, ask=1500.0)
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)

    def test_golden_16_nan_no_fill(self):
        obs = observation(ask=float("nan"))
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)

    def test_golden_16_inf_no_fill(self):
        obs = observation(bid=float("inf"))
        result = sfm.evaluate_market_fill(side="BUY", requested_qty=100, observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)


class LimitFillTests(unittest.TestCase):
    """Golden #11/#12/#13: LIMIT entry fill model."""

    def test_golden_11_limit_buy_trade_through_certain_fill(self):
        obs = observation(observed_at=NOW, last_trade_price=1490.0)
        result = sfm.evaluate_limit_fill(side="BUY", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 100)
        self.assertEqual(result["fill_confidence"], "CERTAIN")
        self.assertEqual(result["fill_reason"], "TRADE_THROUGH")
        self.assertEqual(result["avg_fill_price"], 1500.0)

    def test_golden_12_limit_buy_touch_only_uncertain_not_certain(self):
        obs = observation(observed_at=NOW, last_trade_price=1500.0)
        result = sfm.evaluate_limit_fill(side="BUY", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_confidence"], "UNCERTAIN")
        self.assertEqual(result["fill_reason"], "TOUCH_ONLY")

    def test_golden_13_no_post_submit_trade_no_fill(self):
        obs = observation(observed_at=NOW, last_trade_price=None)
        result = sfm.evaluate_limit_fill(side="BUY", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "NO_POST_SUBMIT_TRADE")

    def test_golden_13_observation_before_submission_ignored(self):
        """Shadow submit後のtrade observationのみを使う——submit前のobservationで
        trade-throughに見える値が入っていても一切使わない。"""
        obs = observation(observed_at=SUBMITTED_AT - timedelta(seconds=1), last_trade_price=1000.0)
        result = sfm.evaluate_limit_fill(side="BUY", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "OBSERVATION_BEFORE_SUBMISSION")

    def test_limit_buy_no_trade_at_or_through_limit(self):
        obs = observation(observed_at=NOW, last_trade_price=1600.0)
        result = sfm.evaluate_limit_fill(side="BUY", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_confidence"], "CERTAIN")
        self.assertEqual(result["fill_reason"], "NO_TRADE_AT_OR_THROUGH_LIMIT")

    def test_limit_sell_trade_through_certain_fill(self):
        obs = observation(observed_at=NOW, last_trade_price=1510.0)
        result = sfm.evaluate_limit_fill(side="SELL", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 100)
        self.assertEqual(result["fill_confidence"], "CERTAIN")
        self.assertEqual(result["fill_reason"], "TRADE_THROUGH")

    def test_limit_sell_touch_only_uncertain(self):
        obs = observation(observed_at=NOW, last_trade_price=1500.0)
        result = sfm.evaluate_limit_fill(side="SELL", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_confidence"], "UNCERTAIN")

    def test_limit_sell_no_trade_at_or_through_limit(self):
        obs = observation(observed_at=NOW, last_trade_price=1400.0)
        result = sfm.evaluate_limit_fill(side="SELL", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "NO_TRADE_AT_OR_THROUGH_LIMIT")

    def test_limit_stale_data_no_fill(self):
        obs = observation(observed_at=NOW, last_trade_price=1490.0, data_freshness="STALE")
        result = sfm.evaluate_limit_fill(side="BUY", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_confidence"], "UNOBSERVABLE")

    def test_hardening_golden_9_limit_trade_through_slippage_not_modeled(self):
        """Phase 5.0.1 Blocker 3 Golden #9: LIMIT trade-throughでも
        未モデル化slippageはNone（limit価格の保守的fillと"slippage=0"は
        同義ではない）。"""
        obs = observation(observed_at=NOW, last_trade_price=1490.0)
        result = sfm.evaluate_limit_fill(side="BUY", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW, submitted_at=SUBMITTED_AT)
        self.assertEqual(result["filled_qty"], 100)
        self.assertIsNone(result["slippage_yen"])
        self.assertIsNone(result["slippage_bps"])
        self.assertEqual(result["slippage_model_status"], "NOT_MODELED_V0_1")

    def test_limit_naive_submitted_at_rejected(self):
        obs = observation(observed_at=NOW, last_trade_price=1490.0)
        result = sfm.evaluate_limit_fill(side="BUY", requested_qty=100, limit_price=1500.0,
                                          observation=obs, now=NOW,
                                          submitted_at=datetime(2026, 9, 17, 8, 59, 0))
        self.assertEqual(result["filled_qty"], 0)
        self.assertEqual(result["fill_reason"], "SUBMITTED_AT_NOT_TIMEZONE_AWARE")


if __name__ == "__main__":
    unittest.main()
