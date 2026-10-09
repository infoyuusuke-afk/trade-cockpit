import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "preopen_scenario_ev",
    Path(__file__).parents[1] / "scripts" / "preopen_scenario_ev.py",
)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

JST = timezone(timedelta(hours=9))
P0_FILES = (
    "ms2_live/MS2_RSS_100_Collector.ps1",
    "downloads/AI_COCKPIT_GATEWAY_V9.ps1",
    "downloads/RUN_AI_COCKPIT_V9.ps1",
    "downloads/AI_COCKPIT_CONTROLLER_V9.ps1",
)


def at(hour, minute, second=0, day=6):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=JST)


def research_quote(**values):
    obs = engine.empty_observation(values.pop("decision_at"))
    available = values.pop("available_at")
    for name, value in values.items():
        obs = engine.note_feature(obs, name, value, available, "research_fixture", research=True)
    return obs


def outcome(scenario_id, family, merge_sign, index, pnl_exit, *, side="LONG", horizon="1m", decision=None):
    decision = decision or at(8, 40)
    known = decision + timedelta(seconds=engine.HORIZON_SECONDS[horizon]) + timedelta(seconds=index)
    entry = 100.0
    if side == "NO-TRADE":
        exit_price = entry
        mfe = 0.0
        mae = 0.0
    else:
        exit_price = pnl_exit
        mfe = 0.01
        mae = 0.01
    return {
        "outcome_id": "%s-%s-%s" % (scenario_id, side, index),
        "scenario_id": scenario_id,
        "family": family,
        "merge_sign": merge_sign,
        "side": side,
        "horizon": horizon,
        "decision_at": decision.isoformat(),
        "outcome_known_at": known.isoformat(),
        "feature_available_at": decision.isoformat(),
        "entry_price": entry,
        "exit_price": exit_price,
        "slippage_bps": 5,
        "cost_bps": 5,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "real_submit_allowed": False,
    }


class SchemaTests(unittest.TestCase):
    def test_catalog_is_wider_than_three_and_covers_the_required_families(self):
        catalog = engine.build_catalog()
        self.assertGreaterEqual(len(catalog), 100)
        self.assertLessEqual(len(catalog), 500)
        families = {item["family"] for item in catalog}
        for name in engine.FAMILIES:
            self.assertIn(name, families)
        ids = [item["scenario_id"] for item in catalog]
        self.assertEqual(len(ids), len(set(ids)))

    def test_empty_observation_does_not_invent_live_numbers(self):
        obs = engine.empty_observation(at(8, 30))
        self.assertEqual(obs["live_status"], "NOT_LIVE")
        self.assertFalse(obs["real_submit_allowed"])
        for name in engine.QUOTE_FEATURES:
            self.assertEqual(obs["features"][name]["status"], "UNAVAILABLE")
            self.assertIsNone(obs["features"][name]["value"])
        for name in engine.EXTERNAL_FEATURES:
            self.assertEqual(obs["features"][name]["status"], "NOT_LIVE")
            self.assertIsNone(obs["features"][name]["value"])

    def test_future_feature_is_not_usable(self):
        obs = engine.empty_observation(at(8, 30))
        obs = engine.note_feature(obs, "gap_pct", 2.0, at(8, 31), "late", research=True)
        self.assertEqual(obs["features"]["gap_pct"]["status"], "FUTURE")
        self.assertIsNone(obs["features"]["gap_pct"]["value"])

    def test_unconnected_value_stays_not_live(self):
        obs = engine.empty_observation(at(8, 30))
        obs = engine.note_feature(obs, "nikkei_futures", 40000, at(8, 29), "feed", live=False)
        self.assertEqual(obs["features"]["nikkei_futures"]["status"], "NOT_LIVE")
        self.assertIsNone(obs["features"]["nikkei_futures"]["value"])
        self.assertEqual(obs["live_status"], "NOT_LIVE")

    def test_special_buy_product_requires_every_part(self):
        obs = research_quote(
            decision_at=at(8, 40),
            available_at=at(8, 40),
            special_buy_duration_seconds=180,
            gap_pct=1.5,
            gu_change_3m=0.2,
            board_imbalance=0.4,
        )
        blocked = engine.special_buy_context(obs)
        self.assertEqual(blocked["status"], "NOT_LIVE")
        self.assertIsNone(blocked["value"])
        obs = engine.note_feature(obs, "regime_score", 0.5, at(8, 40), "research_fixture", research=True)
        obs = engine.note_feature(obs, "semiconductor_relative", 0.2, at(8, 40), "research_fixture", research=True)
        ready = engine.special_buy_context(obs)
        self.assertEqual(ready["status"], "OK")
        self.assertAlmostEqual(ready["value"], 180 * 1.5 * 0.2 * 0.4 * 0.5 * 0.2)

    def test_module_does_not_touch_p0_live_code_or_orders(self):
        text = Path(engine.__file__).read_text(encoding="utf-8")
        for name in ("RssOrder", "submit_shadow_order", "MS2_RSS_100_Collector", "AI_COCKPIT_GATEWAY_V9", "RUN_AI_COCKPIT_V9"):
            self.assertNotIn(name, text)
        self.assertIn("real_submit_allowed", text)


class MatchTests(unittest.TestCase):
    def _match_families(self, obs, phase):
        return {item["family"] for item in engine.CATALOG if engine.candidate_matches(item, obs, phase)}

    def test_each_required_family_can_match_without_collapsing_to_three(self):
        cases = {
            "normal_gu": research_quote(decision_at=at(8, 40), available_at=at(8, 40), gap_pct=1.5, special_quote="none", board_imbalance=0.3, regime_score=0.4, quote_price=100),
            "normal_gd": research_quote(decision_at=at(8, 40), available_at=at(8, 40), gap_pct=-1.5, special_quote="none", board_imbalance=-0.3, regime_score=-0.2, quote_price=100),
            "special_buy_continuation": research_quote(decision_at=at(8, 45), available_at=at(8, 45), special_quote="special_buy", special_buy_duration_seconds=200, gu_change_3m=0.0, gap_pct=1.2, board_imbalance=0.3, regime_score=0.2, semiconductor_relative=0.1, quote_price=100),
            "special_buy_gu_expansion": research_quote(decision_at=at(8, 45), available_at=at(8, 45), special_quote="special_buy", special_buy_duration_seconds=200, gu_change_3m=0.4, gap_pct=1.2, board_imbalance=0.3, regime_score=0.2, semiconductor_relative=0.1, quote_price=100),
            "gu_topping": research_quote(decision_at=at(8, 50), available_at=at(8, 50), gap_pct=2.0, gu_change_3m=0.0, board_imbalance=0.0, quote_price=100),
            "gu_shrink": research_quote(decision_at=at(8, 50), available_at=at(8, 50), gu_change_3m=-0.4, board_imbalance=0.0, quote_price=100),
            "yoriten": research_quote(decision_at=at(9, 2), available_at=at(9, 2), gap_pct=1.0, board_imbalance=0.0, open_price=100, last_price=99, session_high=101, quote_price=99),
            "yorisoko": research_quote(decision_at=at(9, 2), available_at=at(9, 2), gap_pct=-1.0, board_imbalance=0.0, open_price=100, last_price=101, session_low=99, quote_price=101),
            "pullback": research_quote(decision_at=at(9, 6), available_at=at(9, 6), gap_pct=1.4, board_imbalance=0.0, open_price=100, last_price=101, session_high=103, quote_price=101),
            "vwap_recovery": research_quote(decision_at=at(9, 6), available_at=at(9, 6), gap_pct=0.4, board_imbalance=0.0, vwap=100, last_price=100.2, prior_vs_vwap="below", quote_price=100.2),
            "or5_breakout": research_quote(decision_at=at(9, 6), available_at=at(9, 6), last_price=105, or5_complete=True, or5_high=104, board_imbalance=0.3, regime_score=0.2, quote_price=105),
            "or5_failure": research_quote(decision_at=at(9, 6), available_at=at(9, 6), last_price=99, or5_complete=True, or5_low=100, board_imbalance=-0.3, regime_score=-0.2, quote_price=99),
            "or15_breakout": research_quote(decision_at=at(9, 16), available_at=at(9, 16), last_price=106, or15_complete=True, or15_high=105, board_imbalance=0.3, regime_score=0.2, quote_price=106),
            "or15_failure": research_quote(decision_at=at(9, 16), available_at=at(9, 16), last_price=98, or15_complete=True, or15_low=99, board_imbalance=-0.3, regime_score=-0.2, quote_price=98),
            "skip": research_quote(decision_at=at(8, 40), available_at=at(8, 40), quote_price=100),
        }
        phases = {"yoriten": "post_open", "yorisoko": "post_open", "pullback": "post_open", "vwap_recovery": "post_open", "or5_breakout": "post_open", "or5_failure": "post_open", "or15_breakout": "post_open", "or15_failure": "post_open", "skip": "preopen"}
        for family, obs in cases.items():
            matched = self._match_families(obs, phases.get(family, "preopen"))
            self.assertIn(family, matched, family)
        self.assertGreater(len(engine.CATALOG), 3)

    def test_open_anchor_is_the_print_not_the_clock(self):
        self.assertEqual(engine.session_phase(at(9, 1), None, None), "preopen")
        self.assertEqual(engine.session_phase(at(9, 1), at(9, 0, 7), None), "post_open")
        with self.assertRaises(ValueError):
            engine.session_phase(at(8, 29), None, None)


class EstimatorTests(unittest.TestCase):
    def test_small_sample_cannot_display_a_high_ev(self):
        scenario_id = engine.CATALOG[0]["scenario_id"]
        rows = [outcome(scenario_id, "normal_gu", "gu_small", i, 110) for i in range(5)]
        stats = engine.estimate_rows(rows)
        self.assertEqual(stats["status"], "INSUFFICIENT_SAMPLE")
        self.assertFalse(stats["display_ev"])
        self.assertIsNone(stats["net_ev"])
        self.assertIsNone(stats["win_rate"])
        self.assertIsNone(stats["profit_factor"])

    def test_cost_and_slippage_are_required_and_reduce_long_ev(self):
        scenario_id = "scev1:cost"
        rows = [outcome(scenario_id, "normal_gu", "gu_small", i, 101) for i in range(30)]
        with self.assertRaises(ValueError):
            bare = dict(rows[0])
            del bare["slippage_bps"]
            engine.estimate_rows([bare])
        stats = engine.estimate_rows(rows)
        self.assertTrue(stats["display_ev"])
        self.assertLess(stats["net_ev"], 0.01)
        self.assertGreater(stats["mean_slippage_bps"], 0)

    def test_sides_are_estimated_separately_and_no_trade_is_flat(self):
        scenario_id = "scev1:sides"
        rows = [outcome(scenario_id, "normal_gu", "gu_small", i, 101, side="LONG") for i in range(30)]
        rows += [outcome(scenario_id, "normal_gu", "gu_small", i, 98, side="SHORT") for i in range(30)]
        rows += [outcome(scenario_id, "normal_gu", "gu_small", i, 100, side="NO-TRADE") for i in range(30)]
        published = engine.estimate_catalog(rows, at(12, 0), catalog=[{
            "scenario_id": scenario_id,
            "family": "normal_gu",
            "bins": {"gap": "gu_small"},
        }])
        cell = published[scenario_id]
        self.assertGreater(cell["LONG"]["1m"]["net_ev"], 0)
        self.assertGreater(cell["SHORT"]["1m"]["net_ev"], 0)
        self.assertEqual(cell["NO-TRADE"]["1m"]["net_ev"], 0)
        self.assertNotEqual(cell["LONG"]["1m"]["net_ev"], cell["SHORT"]["1m"]["net_ev"])
        for horizon in engine.HORIZONS:
            self.assertIn(horizon, cell["LONG"])

    def test_no_trade_cannot_smuggle_an_excursion(self):
        row = outcome("scev1:flat", "skip", "preopen", 1, 100, side="NO-TRADE")
        row["mfe_pct"] = 0.2
        with self.assertRaises(ValueError):
            engine.estimate_rows([row])

    def test_later_outcome_does_not_change_the_asof_estimate(self):
        scenario_id = engine.CATALOG[0]["scenario_id"]
        family = engine.CATALOG[0]["family"]
        sign = engine.CATALOG[0]["bins"].get("gap")
        early = [outcome(scenario_id, family, sign, i, 101, decision=at(8, 40, day=1)) for i in range(30)]
        for index, row in enumerate(early):
            row["outcome_known_at"] = at(15, 0, day=1).isoformat()
            row["decision_at"] = at(8, 40, day=1).isoformat()
            row["feature_available_at"] = row["decision_at"]
            row["outcome_id"] = "early-%s" % index
        late = outcome(scenario_id, family, sign, 99, 200, decision=at(8, 40, day=2))
        late["outcome_known_at"] = at(15, 0, day=2).isoformat()
        before = engine.estimate_catalog(early, at(8, 30, day=2))
        after = engine.estimate_catalog(early + [late], at(8, 30, day=2))
        self.assertEqual(before[scenario_id]["LONG"]["1m"]["sample_n"], after[scenario_id]["LONG"]["1m"]["sample_n"])
        self.assertEqual(before[scenario_id]["LONG"]["1m"]["net_ev"], after[scenario_id]["LONG"]["1m"]["net_ev"])

    def test_similar_bins_merge_without_publishing_the_tiny_winner(self):
        fine = engine.CATALOG[0]
        sibling = next(item for item in engine.CATALOG if item["family"] == fine["family"] and item["scenario_id"] != fine["scenario_id"] and item["bins"].get("gap") == fine["bins"].get("gap"))
        sign = fine["bins"].get("gap")
        rows = [outcome(fine["scenario_id"], fine["family"], sign, i, 110) for i in range(5)]
        rows += [outcome(sibling["scenario_id"], sibling["family"], sign, i + 10, 99) for i in range(25)]
        alone = engine.estimate_rows(rows[:5])
        self.assertIsNone(alone["net_ev"])
        published = engine.estimate_catalog(rows, at(16, 0), catalog=[fine, sibling])
        merged = published[fine["scenario_id"]]["LONG"]["1m"]
        self.assertTrue(merged["display_ev"])
        self.assertTrue(merged["merged"])
        self.assertNotAlmostEqual(merged["net_ev"], engine.net_return("LONG", 100, 110, 5, 5))

    def test_walk_forward_keeps_the_test_window_out_of_train(self):
        rows = []
        for index in range(40):
            decision = at(8, 40, day=1) + timedelta(days=index)
            row = outcome("scev1:wf", "normal_gu", "gu_small", index, 101, decision=decision)
            row["outcome_known_at"] = (decision + timedelta(minutes=1)).isoformat()
            rows.append(row)
        report = engine.walk_forward(rows, min_train=30, test_size=10, min_n=30)
        self.assertGreaterEqual(len(report["folds"]), 1)
        self.assertEqual(report["folds"][0]["train_n"], 30)
        self.assertLessEqual(report["folds"][0]["oos_n"], 10)
        self.assertFalse(report["real_submit_allowed"])


class SnapshotAndShadowTests(unittest.TestCase):
    def test_snapshot_before_0830_is_rejected_and_0830_stays_not_live(self):
        log = engine.ScenarioLog()
        early = research_quote(decision_at=at(8, 29), available_at=at(8, 29), quote_price=100)
        with self.assertRaises(ValueError):
            log.record_snapshot(early, [])
        first = research_quote(decision_at=at(8, 30), available_at=at(8, 30), quote_price=100, gap_pct=0.4, special_quote="none")
        stored = log.record_snapshot(first, [])
        self.assertEqual(stored["live_status"], "NOT_LIVE")
        self.assertEqual(stored["phase"], "preopen")
        self.assertFalse(stored["real_submit_allowed"])
        self.assertIsNone(stored["open_anchor_at"])

    def test_special_buy_three_minute_event_and_anchor_lock(self):
        log = engine.ScenarioLog()
        pre = research_quote(decision_at=at(8, 57), available_at=at(8, 57), quote_price=100, special_quote="special_buy", special_buy_duration_seconds=60, gu_change_3m=0.2, gap_pct=1.1, board_imbalance=0.3)
        first = log.record_snapshot(pre, [])
        self.assertEqual(first["event_kind"], "QUOTE_UPDATE")
        tick = research_quote(decision_at=at(9, 3), available_at=at(9, 3), quote_price=101, special_quote="special_buy", special_buy_duration_seconds=240, gu_change_3m=0.3, gap_pct=1.4, board_imbalance=0.3)
        event = log.record_snapshot(tick, [], open_anchor_at=at(9, 0, 7))
        self.assertEqual(event["event_kind"], "SPECIAL_BUY_3M")
        self.assertEqual(event["phase"], "post_open")
        self.assertEqual(log.open_anchor_at, at(9, 0, 7).isoformat())
        later = research_quote(decision_at=at(9, 6), available_at=at(9, 6), quote_price=101)
        with self.assertRaises(ValueError):
            log.record_snapshot(later, [], open_anchor_at=at(9, 0, 30))

    def test_records_are_immutable_and_shadow_is_virtual(self):
        fine = engine.CATALOG[0]
        sign = fine["bins"].get("gap")
        rows = [outcome(fine["scenario_id"], fine["family"], sign, i, 102) for i in range(30)]
        for index, row in enumerate(rows):
            row["outcome_known_at"] = at(15, 0, day=5).isoformat()
            row["decision_at"] = at(8, 40, day=5).isoformat()
            row["feature_available_at"] = row["decision_at"]
            row["outcome_id"] = "shadow-sample-%s" % index
        obs = research_quote(
            decision_at=at(8, 40),
            available_at=at(8, 40),
            gap_pct=1.5 if sign == "gu_medium" else 0.5,
            special_quote="none",
            board_imbalance=0.4 if fine["bins"].get("board") == "buy_heavy" else ( -0.4 if fine["bins"].get("board") == "sell_heavy" else 0.0),
            regime_score=0.4 if fine["bins"].get("regime") == "risk_on" else -0.4,
            quote_price=100,
        )
        log = engine.ScenarioLog()
        snapshot = log.record_snapshot(obs, rows, catalog=[fine])
        self.assertTrue(snapshot["matched"][0]["sides"]["LONG"]["display_ev"])
        candidate = log.propose_shadow(snapshot)
        self.assertIsNotNone(candidate)
        self.assertIsNone(candidate["quantity"])
        self.assertFalse(candidate["real_submit_allowed"])
        before = candidate["content_hash"]
        with self.assertRaises(ValueError):
            log.append(dict(candidate))
        score = log.score_after_close(candidate, at(15, 0), 100, 102, 5, 5, 0.02, 0.01)
        self.assertEqual(log._by_id[candidate["record_id"]]["content_hash"], before)
        self.assertNotEqual(score["record_id"], candidate["record_id"])
        sample = engine.outcome_from_score(score, fine["family"], sign)
        self.assertEqual(sample["scenario_id"], candidate["scenario_id"])
        self.assertFalse(sample["real_submit_allowed"])

    def test_dashboard_payload_has_no_dummy_ev_without_samples(self):
        log = engine.ScenarioLog()
        obs = research_quote(decision_at=at(8, 31), available_at=at(8, 31), quote_price=100, gap_pct=1.2, special_quote="none", board_imbalance=0.0)
        log.record_snapshot(obs, [])
        payload = engine.build_dashboard_payload(log)
        self.assertEqual(payload["live_status"], "NOT_LIVE")
        self.assertFalse(payload["real_submit_allowed"])
        self.assertIsNone(payload["race"][0]["long_net_ev"])
        self.assertIsNone(payload["race"][0]["short_net_ev"])
        self.assertEqual(payload["race"][0]["status"], "INSUFFICIENT_SAMPLE")
        for item in payload["top3"]:
            self.assertIsNone(item["net_ev"])
            self.assertFalse(item["display_ev"])
        for cell in payload["heatmap"]["cells"]:
            if not cell["current"]:
                self.assertIsNone(cell["net_ev"])
                self.assertEqual(cell["status"], "INSUFFICIENT_SAMPLE")

    def test_real_submit_true_is_rejected(self):
        log = engine.ScenarioLog()
        with self.assertRaises(ValueError):
            log.append({"record_id": "bad", "real_submit_allowed": True})


if __name__ == "__main__":
    unittest.main()
