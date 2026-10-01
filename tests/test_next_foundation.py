import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.next_foundation.board import classify_selection
from scripts.next_foundation.config import load_config, validate_config
from scripts.next_foundation.pipeline import run
from scripts.next_foundation.score import (
    component_or,
    component_price_change,
    component_rank_velocity,
    score_market,
)
from scripts.next_foundation.states import LIFECYCLE_PHASES, assign_state
from scripts.next_foundation.universe import (
    DiscoveryNotConfigured,
    MonitorLayerError,
    Ms2MonitorRoster,
    TradingViewScreenerDiscovery,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "next_market_sample.json"


def _full_features(**overrides):
    features = {
        "price_change_15s": 0.08,
        "price_accel_45s": 0.05,
        "volume_surge_ratio": 1.2,
        "turnover_accel": 1.1,
        "high_update_frequency": 0.2,
        "vwap_position": 0.1,
        "or5_state": "INSIDE",
        "or15_state": "INSIDE",
        "pullback_shallowness": 0.4,
        "relative_strength": 0.05,
        "liquidity": 80_000_000,
    }
    features.update(overrides)
    return features


def _candidate(symbol, features, rank_history=None, price=1000):
    return {
        "symbol": symbol,
        "name": symbol,
        "price": price,
        "rank_history": rank_history or [],
        "features": features,
    }


def _payload(candidates, **extra):
    payload = {
        "source_mode": "sample",
        "as_of": "2026-10-01T10:15:00+09:00",
        "selection_mode": "scheduled_morning",
        "sources": [{"source_id": "sample_discovery", "layer": "discovery", "candidates": candidates}],
    }
    payload.update(extra)
    return payload


class NextScoreTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_missing_feature_is_not_zero_and_fail_closes_when_required(self):
        features = _full_features(liquidity=None)
        scored = score_market(features, [], self.config)
        self.assertIsNone(scored["market_score"])
        self.assertTrue(scored["fail_closed"])
        self.assertIn("MISSING_REQUIRED_FEATURE", scored["reason_codes"])
        self.assertNotEqual(scored["market_score"], 0)

    def test_explicit_zero_change_is_scored(self):
        scored = score_market(_full_features(price_change_15s=0.0), [], self.config)
        self.assertFalse(scored["fail_closed"])
        self.assertIsNotNone(scored["market_score"])
        self.assertGreater(scored["market_score"], 0)

    def test_extended_spike_scores_below_early_move(self):
        self.assertGreater(component_price_change(0.25), component_price_change(2.5))

    def test_unknown_or_is_not_inside(self):
        self.assertIsNone(component_or(None))
        self.assertNotEqual(component_or(None), component_or("INSIDE"))
        self.assertGreater(component_or("ABOVE"), component_or("INSIDE"))

    def test_velocity_unknown_is_not_flat(self):
        self.assertIsNone(component_rank_velocity(None))
        self.assertLess(component_rank_velocity(0), component_rank_velocity(5))

    def test_weight_change_moves_the_score(self):
        calm = score_market(_full_features(price_accel_45s=0.4, liquidity=40_000_000), [], self.config)
        shifted = json.loads(json.dumps(self.config))
        shifted["weights"]["price_accel_45s"] += 0.03
        shifted["weights"]["liquidity"] -= 0.03
        validate_config(shifted)
        rescored = score_market(_full_features(price_accel_45s=0.4, liquidity=40_000_000), [], shifted)
        self.assertGreater(rescored["market_score"], calm["market_score"])

    def test_weights_must_sum_to_one(self):
        broken = json.loads(json.dumps(self.config))
        broken["weights"]["liquidity"] = 0.5
        with self.assertRaises(ValueError):
            validate_config(broken)


class NextFunnelTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.board = run(self.payload)

    def test_sample_funnel_prefers_rank_velocity_over_raw_score(self):
        self.assertEqual(self.board["active100_count"], 25)
        self.assertLess(len(self.board["next20"]), 20)
        self.assertLess(len(self.board["next5"]), 5)
        self.assertGreater(len(self.board["next5"]), 0)
        climber = self.board["next5"][0]
        leader = next(row for row in self.board["active100"] if row["symbol"] == "A100")
        chaser = next(row for row in self.board["active100"] if row["symbol"] == "A300")
        symbols = [row["symbol"] for row in self.board["next5"]]
        self.assertEqual(symbols, ["A200", "A100"])
        self.assertEqual(climber["symbol"], "A200")
        self.assertEqual(climber["next_rank"], 1)
        self.assertEqual(climber["rank"], 2)
        self.assertEqual(climber["previous_rank"], 7)
        self.assertEqual(climber["rank_path"], [42, 18, 7, 2])
        self.assertEqual(climber["state"], "IGNITION")
        self.assertEqual(climber["primary_reasons"][0], "PRICE_ACCEL_45S")
        self.assertGreater(leader["score"], climber["score"])
        self.assertEqual(leader["rank"], 1)
        self.assertEqual(leader["next_rank"], 2)
        self.assertEqual(leader["rank_velocity"], 0)
        self.assertNotIn("A300", symbols)
        self.assertNotIn("B020", symbols)
        self.assertNotIn("B019", symbols)
        self.assertNotIn("B018", symbols)
        for row in [*self.board["next20"], *self.board["next5"]]:
            self.assertGreaterEqual(row["score"], 58)
            self.assertNotEqual(row["state"], "WATCH")
            self.assertIn(row["state"], ("PRE_NEXT", "IGNITION", "CONFIRMED"))
            self.assertEqual(row["coverage"], 1.0)
        self.assertLess(chaser["score"], climber["score"])
        self.assertTrue(climber["on_monitor_layer"])
        self.assertNotIn("Z999", {row["symbol"] for row in self.board["active100"]})
        self.assertIn("MONITOR_CANDIDATES_IGNORED", self.board["warnings"])

    def test_missing_and_unknown_are_not_filled_with_normals(self):
        excluded = {row["symbol"]: row for row in self.board["excluded"]}
        self.assertIn("A999", excluded)
        self.assertIn("liquidity", excluded["A999"]["reason_codes"])
        flat = next(row for row in self.board["active100"] if row["symbol"] == "A000")
        self.assertEqual(flat["features"]["price_change_15s"], 0.0)
        self.assertIsNotNone(flat["score"])
        unknown = next(row for row in self.board["active100"] if row["symbol"] == "A910")
        self.assertIsNone(unknown["features"]["or5_state"])
        self.assertIsNone(unknown["features"]["or15_state"])
        self.assertNotIn("OR5_INSIDE", unknown["reason_codes"])
        self.assertFalse(self.board["orders_enabled"])

    def test_every_active_member_has_a_reason(self):
        for row in self.board["active100"]:
            self.assertTrue(row["reason_codes"], row["symbol"])
            self.assertLessEqual(len(row["primary_reasons"]), 3)

    def test_judgment_log_keeps_forward_slots_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "next_judgments.jsonl"
            board = run(self.payload, log_path=log_path)
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), board["universe_count"])
            climber = next(json.loads(line) for line in lines if json.loads(line)["symbol"] == "A200")
            for key in ("timestamp", "symbol", "score", "rank", "previous_rank", "rank_velocity", "state", "reason_codes", "features"):
                self.assertIn(key, climber)
            self.assertEqual(climber["forward"]["anchor_price"], 4820)
            for horizon in ("30s", "1m", "3m", "5m"):
                slot = climber["forward"]["horizons"][horizon]
                self.assertIsNone(slot["return"])
                self.assertIsNone(slot["mfe"])
                self.assertIsNone(slot["mae"])
            missing = next(json.loads(line) for line in lines if json.loads(line)["symbol"] == "A999")
            self.assertIsNone(missing["score"])
            self.assertTrue(missing["fail_closed"])

    def test_active100_caps_at_one_hundred_without_inventing_next(self):
        candidates = []
        for index in range(120):
            candidates.append(_candidate(
                f"{index:04d}",
                _full_features(relative_strength=index / 1000),
                price=1000 + index,
            ))
        board = run(_payload(candidates))
        self.assertEqual(board["active100_count"], 100)
        self.assertEqual(len(board["next20"]), 0)
        self.assertEqual(len(board["next5"]), 0)
        self.assertTrue(board["funnel_fail_closed"])
        self.assertEqual(board["funnel_reason"], "RANK_VELOCITY_UNAVAILABLE")
        self.assertEqual(board["active100"][0]["symbol"], "0119")
        self.assertNotIn("0000", {row["symbol"] for row in board["active100"]})

    def test_weak_watch_names_do_not_fill_next_slots(self):
        mild = []
        for index in range(8):
            mild.append(_candidate(
                f"W{index:03d}",
                _full_features(relative_strength=0.01 * index),
                rank_history=[{"rank": index + 3, "timestamp": "2026-10-01T10:10:00+09:00"}],
            ))
        board = run(_payload(mild))
        self.assertEqual(board["next5"], [])
        self.assertEqual(board["next20"], [])
        self.assertFalse(board["funnel_fail_closed"])
        self.assertEqual(board["funnel_reason"], "NEXT_ELIGIBILITY_UNMET")
        self.assertTrue(all(row["state"] == "WATCH" for row in board["active100"]))

    def test_empty_active_names_its_own_reason(self):
        board = run({"as_of": "2026-10-01T10:15:00+09:00", "sources": []})
        self.assertEqual(board["funnel_reason"], "ACTIVE100_EMPTY")
        self.assertTrue(board["funnel_fail_closed"])

    def test_partial_coverage_cannot_enter_next_even_with_a_higher_score(self):
        sparse = _candidate(
            "S900",
            _full_features(
                price_change_15s=0.30,
                price_accel_45s=0.40,
                volume_surge_ratio=3.2,
                turnover_accel=3.0,
                high_update_frequency=4,
                vwap_position=0.20,
                or5_state="ABOVE",
                or15_state="ABOVE",
                pullback_shallowness=0.95,
                relative_strength=None,
                liquidity=1_200_000_000,
            ),
            rank_history=[{"rank": 12, "timestamp": "2026-10-01T10:12:00+09:00"}],
            price=2500,
        )
        complete = _candidate(
            "F900",
            _full_features(relative_strength=0.05, price_accel_45s=0.08),
            rank_history=[{"rank": 4, "timestamp": "2026-10-01T10:12:00+09:00"}],
        )
        board = run(_payload([sparse, complete]))
        by_symbol = {row["symbol"]: row for row in board["active100"]}
        self.assertGreater(by_symbol["S900"]["market_score"], by_symbol["F900"]["market_score"])
        self.assertLess(by_symbol["S900"]["coverage"], 1)
        self.assertNotIn("S900", {row["symbol"] for row in board["next20"]})
        self.assertNotIn("S900", {row["symbol"] for row in board["next5"]})

    def test_insufficient_coverage_is_not_called_missing_velocity(self):
        sparse = _candidate(
            "S901",
            _full_features(relative_strength=None, price_accel_45s=0.4, volume_surge_ratio=3),
            rank_history=[{"rank": 8, "timestamp": "2026-10-01T10:12:00+09:00"}],
        )
        board = run(_payload([sparse]))
        self.assertEqual(board["next5"], [])
        self.assertTrue(board["funnel_fail_closed"])
        self.assertEqual(board["funnel_reason"], "COMPLETE_SCORE_UNAVAILABLE")


class NextMembershipTests(unittest.TestCase):
    def test_intraday_emergency_promotes_without_waiting_for_the_next_session(self):
        weak = []
        for index in range(100):
            weak.append(_candidate(f"S{index:03d}", _full_features(relative_strength=index / 10000), price=500 + index))
        emergency = _candidate("E100", _full_features(
            price_change_15s=0.28,
            price_accel_45s=0.36,
            volume_surge_ratio=2.8,
            turnover_accel=2.4,
            high_update_frequency=3,
            vwap_position=0.22,
            or5_state="ABOVE",
            pullback_shallowness=0.84,
            relative_strength=0.55,
            liquidity=180_000_000,
        ), price=4820)
        previous = {"members": [row["symbol"] for row in weak], "symbols": {}}
        board = run(
            _payload([*weak, emergency], selection_mode="intraday"),
            previous=previous,
        )
        promoted = next(row for row in board["active100"] if row["symbol"] == "E100")
        self.assertEqual(promoted["membership"], "EMERGENCY")
        self.assertIn("EMERGENCY_PROMOTION", promoted["reason_codes"])
        self.assertEqual(board["active100_count"], 100)
        self.assertNotIn("S000", {row["symbol"] for row in board["active100"]})

    def test_scheduled_morning_rebuilds_instead_of_keeping_a_stale_member(self):
        strong = _candidate("H100", _full_features(relative_strength=0.9, price_accel_45s=0.3))
        weak = _candidate("W100", _full_features(relative_strength=-0.4, price_accel_45s=-0.2, liquidity=40_000_000))
        board = run(
            _payload([strong, weak], selection_mode="scheduled_morning"),
            previous={"members": ["W100"], "symbols": {}},
        )
        self.assertEqual(board["selection_kind"], "SCHEDULED_MORNING")
        symbols = {row["symbol"] for row in board["active100"]}
        self.assertIn("H100", symbols)
        self.assertIn("W100", symbols)
        self.assertTrue(all(row["membership"] == "SCHEDULED" for row in board["active100"]))

    def test_clock_selects_morning_and_afternoon_reselection(self):
        config = load_config()
        morning = classify_selection("2026-10-01T09:00:00+09:00", None, config)
        afternoon = classify_selection("2026-10-01T12:30:00+09:00", None, config)
        intraday = classify_selection("2026-10-01T10:15:00+09:00", None, config)
        self.assertEqual(morning["selection_kind"], "SCHEDULED_MORNING")
        self.assertTrue(morning["rebuild"])
        self.assertEqual(afternoon["selection_kind"], "SCHEDULED_AFTERNOON")
        self.assertEqual(intraday["selection_kind"], "INTRADAY")
        self.assertTrue(intraday["allow_emergency"])
        with self.assertRaises(ValueError):
            classify_selection("2026-10-01T10:15:00", None, config)


class NextStateTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def _row(self, **extra):
        row = {
            "fail_closed": False,
            "funnel": "NEXT5",
            "score": 80,
            "rank_velocity": 2,
            "reason_codes": ["PRICE_ACCEL_45S", "VOLUME_SURGE"],
            "features": {"price_accel_45s": 0.3},
        }
        row.update(extra)
        return row

    def test_lifecycle_slot_covers_the_reserved_phases(self):
        self.assertEqual(
            LIFECYCLE_PHASES,
            ("PRE_IGNITION", "IGNITION", "EXPANSION", "TREND", "MATURE", "EXHAUSTION"),
        )
        state = assign_state(self._row(), None, self.config)
        self.assertEqual(state["state"], "IGNITION")
        self.assertEqual(state["lifecycle_state"], "IGNITION")
        self.assertIn("TREND", state["lifecycle_phases"])
        self.assertIn("MATURE", state["lifecycle_phases"])

    def test_unknown_velocity_does_not_confirm(self):
        previous = {"state": "IGNITION", "consecutive_ignition": 1, "peak_score": 80}
        unknown = assign_state(self._row(rank_velocity=None), previous, self.config)
        zero = assign_state(self._row(rank_velocity=0), previous, self.config)
        active = assign_state(self._row(funnel="ACTIVE100", rank_velocity=None, score=95), previous, self.config)
        observed = assign_state(self._row(rank_velocity=2), previous, self.config)
        self.assertIsNone(self._row(rank_velocity=None)["rank_velocity"])
        self.assertEqual(self._row(rank_velocity=0)["rank_velocity"], 0)
        self.assertEqual(unknown["state"], "IGNITION")
        self.assertNotEqual(unknown["state"], "CONFIRMED")
        self.assertEqual(zero["state"], "IGNITION")
        self.assertNotEqual(active["state"], "CONFIRMED")
        self.assertEqual(observed["state"], "CONFIRMED")
        self.assertEqual(observed["lifecycle_state"], "EXPANSION")
        self.assertTrue(observed["lifecycle_alias"])

    def test_peak_score_persists_across_a_sequence(self):
        first = assign_state(self._row(score=80, rank_velocity=2), None, self.config)
        self.assertEqual(first["state"], "IGNITION")
        self.assertEqual(first["peak_score"], 80)
        second = assign_state(self._row(score=90, rank_velocity=0.4), first, self.config)
        self.assertEqual(second["state"], "IGNITION")
        self.assertEqual(second["peak_score"], 90)
        dipped = assign_state(self._row(score=85, rank_velocity=0.4), second, self.config)
        self.assertEqual(dipped["state"], "IGNITION")
        self.assertEqual(dipped["peak_score"], 90)
        cooled = assign_state(self._row(score=70, rank_velocity=-2), second, self.config)
        self.assertEqual(cooled["state"], "COOLING")
        self.assertEqual(cooled["peak_score"], 90)
        reset = assign_state(self._row(score=40, rank_velocity=0, reason_codes=["TOP_UNIVERSE_SCORE"]), cooled, self.config)
        self.assertEqual(reset["state"], "WATCH")
        self.assertEqual(reset["peak_score"], 40)

    def test_rollover_cools_before_it_can_confirm(self):
        previous = {"state": "IGNITION", "consecutive_ignition": 1, "peak_score": 90}
        cooled = assign_state(self._row(rank_velocity=-2, features={"price_accel_45s": -0.1}), previous, self.config)
        self.assertEqual(cooled["state"], "COOLING")
        self.assertEqual(cooled["lifecycle_state"], "EXHAUSTION")
        self.assertEqual(cooled["peak_score"], 90)

    def test_next20_without_ignition_is_pre_next(self):
        state = assign_state(self._row(funnel="NEXT20", score=60, reason_codes=["SHALLOW_PULLBACK"]), None, self.config)
        self.assertEqual(state["state"], "PRE_NEXT")
        self.assertEqual(state["lifecycle_state"], "PRE_IGNITION")

    def test_fail_closed_has_no_trade_state(self):
        state = assign_state(self._row(fail_closed=True, score=None), None, self.config)
        self.assertIsNone(state["state"])
        self.assertIsNone(state["lifecycle_state"])


class NextUniverseTests(unittest.TestCase):
    def test_tradingview_adapter_does_not_call_out_until_rows_are_injected(self):
        with self.assertRaises(DiscoveryNotConfigured):
            TradingViewScreenerDiscovery().load()
        rows = TradingViewScreenerDiscovery(rows=[{"symbol": "A200"}]).load()
        self.assertEqual(rows[0]["symbol"], "A200")

    def test_ms2_monitor_cannot_supply_discovery_rows(self):
        with self.assertRaises(MonitorLayerError):
            Ms2MonitorRoster(["A200"]).load()

    def test_empty_discovery_fail_closes_the_board(self):
        board = run({"as_of": "2026-10-01T10:15:00+09:00", "sources": []})
        self.assertTrue(board["fail_closed"])
        self.assertEqual(board["active100_count"], 0)
        self.assertEqual(board["next5"], [])

    def test_conflicting_discovery_values_fail_closed(self):
        features = _full_features()
        other = dict(features)
        other["price_accel_45s"] = 0.4
        board = run(_payload([] , sources=[
            {"source_id": "left", "layer": "discovery", "candidates": [_candidate("C100", features)]},
            {"source_id": "right", "layer": "discovery", "candidates": [_candidate("C100", other)]},
        ]))
        self.assertEqual(board["excluded"][0]["symbol"], "C100")
        self.assertIn("INVALID_FEATURE", board["excluded"][0]["reason_codes"])
        self.assertIsNone(board["excluded"][0].get("score"))


class NextUiContractTests(unittest.TestCase):
    def test_dashboard_keeps_a_next_card_slot_on_the_realtime_tab(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        weekly = (ROOT / "scripts" / "weekly_tabs.py").read_text(encoding="utf-8")
        generator = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")
        script = (ROOT / "next_board.js").read_text(encoding="utf-8")
        for text in (index, generator):
            self.assertIn('id="next-discovery"', text)
            self.assertIn("next_board.js", text)
            self.assertIn("next_board.css", text)
        for text in (index, weekly):
            self.assertIn('s.id==="next-discovery"', text)
        self.assertIn("FAIL-CLOSED", script)
        self.assertIn("STALE", script)
        self.assertIn("evaluateNextBoardFreshness", script)
        self.assertIn("next_board_freshness.js", index)
        self.assertIn("next_board_freshness.js", generator)
        self.assertNotIn("28580", script)
        self.assertNotIn("28581", script)
        self.assertNotIn("28582", script)
        self.assertNotIn("28583", script)
        self.assertNotIn("speechSynthesis", script)
        freshness = (ROOT / "next_board_freshness.js").read_text(encoding="utf-8")
        self.assertIn("SESSION_EXPIRED", freshness)
        self.assertIn("FUTURE_INVALID", freshness)
        self.assertIn("SAMPLE_NOT_PRODUCTION", freshness)

    def test_production_board_is_fail_closed_not_a_sample_ranking(self):
        board = json.loads((ROOT / "next_board.json").read_text(encoding="utf-8"))
        self.assertTrue(board["fail_closed"])
        self.assertEqual(board["fail_closed_reason"], "LIVE_SOURCE_NOT_CONFIGURED")
        self.assertNotEqual(board.get("source_mode"), "sample")
        self.assertEqual(board["next5"], [])
        self.assertEqual(board["next20"], [])
        blob = json.dumps(board)
        self.assertNotIn("A200", blob)
        self.assertNotIn("A100", blob)
        self.assertNotIn("B020", blob)

    def test_freshness_script_rejects_stale_and_sample_snapshots(self):
        result = subprocess.run(
            ["node", "--test", str(ROOT / "tests" / "next_board_freshness.test.mjs")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
