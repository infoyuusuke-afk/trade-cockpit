import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 6, 10, 0, tzinfo=JST)
PAST = NOW - timedelta(days=1)


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


brain = _load("ai_brain_research", "scripts/ai_brain_research.py")
shadow = _load("ai_shadow_supervisor_for_brain", "scripts/ai_shadow_supervisor.py")
calendar = _load("event_calendar_for_brain", "scripts/event_calendar.py")


def _trial(model, pnl, stage, index, feature=None, *, side="LONG", available_at=PAST, regime="SEMI"):
    features = {}
    if feature is not None:
        features[feature] = {"value": 1.0, "available_at": available_at}
    return {
        "model_id": model,
        "side": side,
        "stage": stage,
        "decided_at": NOW - timedelta(minutes=index + 1),
        "regime": regime,
        "pnl_per_share_yen": pnl,
        "cost_yen_per_share": 0.0,
        "mae_yen": 4.0,
        "mfe_yen": 9.0,
        "slippage_yen": 1.0,
        "features": features,
    }


def _ladder(model, pnl, feature=None, n=8, available_at=PAST):
    rows = []
    for stage in brain.STAGES:
        for index in range(n):
            rows.append(_trial(model, pnl, stage, index, feature, available_at=available_at))
    return rows


def _summary(model, side, ev, n=30):
    regime = {"n": n, "net_ev": ev}
    return {
        "model_id": model,
        "side": side,
        "promotion_candidate": True,
        "edge_claim": True,
        "real_submit_allowed": False,
        "oos_net_ev": ev,
        "oos_n": n,
        "ci_low": ev,
        "avg_slippage_yen": 1.0,
        "regimes": {"SEMI": regime},
    }


class ResearchLayerTests(unittest.TestCase):
    def test_registry_separates_acquired_connected_and_unfetched(self):
        self.assertEqual(brain.registry_ids("acquired"), (
            "credit_buy", "credit_sell", "credit_ratio", "shortable_quantity",
            "prior_pts", "common_decision", "tdnet_material",
        ))
        self.assertEqual(brain.registry_ids("connected"), (
            "usdjpy", "us_rates", "sox", "earnings_estimates", "sq_calendar",
        ))
        self.assertIn("silver", brain.registry_ids("expansion"))
        self.assertIn("nt_ratio", brain.registry_ids("expansion"))
        self.assertIn("official_speech", brain.registry_ids("expansion"))

    def test_baseline_side_stays_on_the_live_signal(self):
        row = {
            "ticker": "285A.T", "signal": "買いサイン", "price": 19120.0,
            "entry_price": 19120.0, "stop_price": 19000.0, "data": "LIVE",
            "credit_ratio": 9.0,
        }
        self.assertEqual(brain.baseline_side(row), "LONG")
        self.assertEqual(brain.baseline_side({**row, "signal": "市場時間外"}), "NO_TRADE")
        self.assertEqual(shadow.LONG_ENTRY_SIGNALS, frozenset({"初動買い候補", "買いサイン", "持ち越しロング確定"}))

    def test_acquired_features_need_a_stamp(self):
        row = {
            "credit_buy": 10.0, "credit_sell": 2.0, "credit_ratio": 5.0,
            "shortable_quantity": 100.0, "prior_pts_bias": 12.0,
            "common_decision": "TREND LONG", "material_score": 18.0,
            "credit_ratio_available_at": PAST,
        }
        shot = brain.snapshot_acquired(row, NOW)
        self.assertEqual(shot["credit_ratio"]["status"], "PRESENT")
        self.assertEqual(shot["credit_buy"]["status"], "UNSTAMPED")
        self.assertEqual(shot["common_decision"]["status"], "UNSTAMPED")
        self.assertNotIn("silver", shot)

    def test_world_market_and_macro_reject_future_or_unverified_values(self):
        parsed = {"rows": {
            "511": {"value": 150.2, "observed_at": "2026-10-05", "verified": True},
            "811": {"value": 4.1, "observed_at": "2026-10-06", "verified": True},
            "611": {"value": 5000.0, "observed_at": "2026-10-05T18:00:00+09:00", "verified": False},
        }}
        shot = brain.snapshot_world_market(parsed, NOW)
        self.assertEqual(shot["usdjpy"]["status"], "PRESENT")
        self.assertEqual(shot["usdjpy"]["value"], 150.2)
        self.assertEqual(shot["us_rates"]["status"], "LOOKAHEAD_EXCLUDED")
        self.assertEqual(shot["sox"]["status"], "UNVERIFIED")
        macro = brain.snapshot_macro_observations([
            {"instrument": "USDJPY", "value": 149.0, "observed_at": PAST},
            {"instrument": "SOX", "value": 4800.0, "observed_at": NOW + timedelta(hours=1)},
        ], NOW)
        self.assertEqual(macro["usdjpy"]["status"], "PRESENT")
        self.assertEqual(macro["sox"]["status"], "LOOKAHEAD_EXCLUDED")

    def test_earnings_and_sq_calendar_use_only_published_times(self):
        naked = brain.snapshot_earnings({"score": 70}, NOW)
        self.assertEqual(naked["earnings_estimates"]["status"], "UNSTAMPED")
        stamped = brain.snapshot_earnings({"score": 70, "available_at": PAST}, NOW)
        self.assertEqual(stamped["earnings_estimates"]["status"], "PRESENT")
        unfetched = calendar.event("sq-10", "月例SQ", "2026-10-09", "日本需給", "jpx_last", time_jst="寄り付き")
        self.assertEqual(brain.snapshot_sq_calendar([unfetched], NOW)["sq_calendar"]["status"], "UNSTAMPED")
        fetched = calendar.event("sq-10", "月例SQ", "2026-10-09", "日本需給", "jpx_last", time_jst="寄り付き", fetched_at=PAST.isoformat())
        before = brain.snapshot_sq_calendar([fetched], NOW)
        self.assertEqual(before["sq_calendar"]["status"], "PRESENT")
        self.assertEqual(before["sq_calendar"]["value"], "off")
        on_day = brain.snapshot_sq_calendar([fetched], datetime(2026, 10, 9, 10, 0, tzinfo=JST))
        self.assertEqual(on_day["sq_calendar"]["value"], "on")

    def test_small_or_lookahead_samples_are_not_an_edge(self):
        small = _ladder(brain.BASELINE_MODEL, 18, n=7) + _ladder("BASELINE+credit_ratio", 27, "credit_ratio", n=7)
        summary = brain.summarize_model(small, model_id="BASELINE+credit_ratio", side="LONG")
        self.assertEqual(summary["measurement_status"], "INSUFFICIENT_SAMPLE")
        self.assertFalse(summary["promotion_candidate"])
        leaked = _ladder(brain.BASELINE_MODEL, 18) + _ladder(
            "BASELINE+credit_ratio", 27, "credit_ratio", available_at=NOW + timedelta(hours=2),
        )
        leaked_summary = brain.summarize_model(leaked, model_id="BASELINE+credit_ratio", side="LONG")
        self.assertEqual(leaked_summary["measurement_status"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(leaked_summary["live_roundtrip"], "NOT_RUN/RESEARCH_LAYER")

    def test_reproduced_post_cost_edge_can_be_a_candidate_only(self):
        rows = _ladder(brain.BASELINE_MODEL, 18) + _ladder("BASELINE+credit_ratio", 27, "credit_ratio")
        summary = brain.summarize_model(rows, model_id="BASELINE+credit_ratio", side="LONG")
        self.assertEqual(summary["baseline_ev"], 18.0)
        self.assertEqual(summary["feature_ev"], 27.0)
        self.assertEqual(summary["delta_ev"], 9.0)
        self.assertEqual(summary["sample_n"], 8)
        self.assertEqual(summary["measurement_status"], "PIPELINE_ONLY")
        self.assertIn("STATISTICAL_SAMPLE", summary["edge_block_reasons"])
        self.assertFalse(summary["promotion_candidate"])
        self.assertFalse(summary["edge_claim"])
        self.assertFalse(summary["is_entry_trigger"])
        self.assertFalse(summary["real_submit_allowed"])
        self.assertEqual(summary["regimes"]["SEMI"]["n"], 8)

    def test_oos_sign_flip_is_rejected(self):
        rows = []
        for stage in brain.STAGES:
            model_pnl = 10 if stage == "oos" else 30
            for index in range(8):
                rows.append(_trial(brain.BASELINE_MODEL, 18, stage, index))
                rows.append(_trial("BASELINE+credit_ratio", model_pnl, stage, index, "credit_ratio"))
        summary = brain.summarize_model(rows, model_id="BASELINE+credit_ratio", side="LONG")
        self.assertEqual(summary["measurement_status"], "OOS_FAILED")
        self.assertFalse(summary["promotion_candidate"])

    def test_meta_brain_picks_expectancy_not_a_majority_or_an_llm_label(self):
        summaries = [
            _summary("BASELINE+credit_ratio", "SHORT", 10),
            _summary("BASELINE+prior_pts", "SHORT", 11),
            _summary("BASELINE+tdnet_material", "SHORT", 12),
            _summary("BASELINE+investor_futures_flow", "LONG", 41),
            _summary("BASELINE+credit_ratio+prior_pts+tdnet_material", "LONG", 12),
        ]
        chosen = brain.select_research_candidate(summaries, current_regime="SEMI", llm_side="SHORT")
        self.assertEqual(chosen["model_id"], "BASELINE+investor_futures_flow")
        self.assertEqual(chosen["selected_side"], "LONG")
        self.assertFalse(chosen["majority_vote"])
        self.assertFalse(chosen["llm_decides_numeric_trade"])
        self.assertEqual(chosen["llm_role"], "STRUCTURE_UNSTRUCTURED_TEXT_ONLY")
        self.assertFalse(chosen["is_entry_trigger"])
        empty = brain.select_research_candidate([], current_regime="SEMI", llm_side="LONG")
        self.assertEqual(empty["selected_side"], "NO_TRADE")

    def test_statistical_bar_can_pass_only_with_variance_and_a_preregistered_family(self):
        rows = []
        for stage in brain.STAGES:
            for index in range(30):
                rows.append(_trial(brain.BASELINE_MODEL, 10 + (index % 5), stage, index))
                rows.append(_trial("BASELINE+credit_ratio", 40 + (index % 5), stage, index, "credit_ratio"))
        summary = brain.summarize_model(rows, model_id="BASELINE+credit_ratio", side="LONG", family_size=1)
        self.assertEqual(summary["measurement_status"], "OOS_REPRODUCED")
        self.assertTrue(summary["edge_claim"])
        self.assertGreater(summary["effect_size"], 0)
        self.assertGreater(summary["adjusted_delta_ci_low"], 0)
        blocked = brain.summarize_model(rows, model_id="BASELINE+credit_ratio", side="LONG", family_size=12)
        self.assertTrue(blocked["edge_claim"])
        self.assertGreater(blocked["family_size"], 1)

    def _exit(self, **overrides):
        entry_at = NOW - timedelta(minutes=30)
        exit_at = NOW - timedelta(minutes=5)
        event = {
            "event_type": "virtual_exit",
            "seq": 2,
            "related_entry_seq": 1,
            "at": exit_at.isoformat(),
            "ticker": "285A.T",
            "side": "LONG",
            "performance_bucket": "clean_strategy",
            "fill_entry_price": 19130.0,
            "fill_exit_price": 19170.0,
            "fill_pnl_per_share_yen": 40.0,
            "slippage_yen": 20.0,
            "mae_yen": 80.0,
            "mfe_yen": 170.0,
            "fee_yen_per_share": 1.0,
            "real_submit_allowed": False,
        }
        event.update(overrides)
        return event

    def _entry(self, **overrides):
        event = {
            "event_type": "virtual_entry",
            "seq": 1,
            "at": (NOW - timedelta(minutes=30)).isoformat(),
            "ticker": "285A.T",
            "side": "LONG",
            "real_submit_allowed": False,
        }
        event.update(overrides)
        return event

    def test_only_confirmed_live_exits_enter_the_baseline_shadow_stage(self):
        clean = [self._entry(), self._exit()]
        ingested = brain.ingest_shadow_exits(clean)
        self.assertEqual(ingested["clean_n"], 1)
        self.assertEqual(ingested["trials"][0]["source"], "live_shadow")
        self.assertEqual(ingested["trials"][0]["stage"], "shadow")
        self.assertEqual(ingested["trials"][0]["model_id"], "BASELINE")
        metrics = brain.baseline_shadow_metrics(ingested["trials"])
        self.assertEqual(metrics["by_side"]["LONG"]["n"], 1)
        self.assertEqual(metrics["by_side"]["LONG"]["net_ev"], 39.0)
        self.assertEqual(metrics["by_side"]["SHORT"]["n"], 0)
        self.assertFalse(metrics["promotion_candidate"])
        duplicated = brain.ingest_shadow_exits(clean + [self._exit(seq=3)])
        self.assertEqual(duplicated["clean_n"], 1)
        self.assertEqual(duplicated["excluded"][-1]["reason"], "DUPLICATE")

    def test_bad_shadow_rows_are_excluded_without_mixing_sources(self):
        ledger = [
            self._entry(),
            self._exit(acceptance_class="synthetic"),
            self._exit(seq=4, related_entry_seq=9, fee_yen_per_share=None),
            self._entry(seq=9, at=(NOW - timedelta(minutes=40)).isoformat()),
            self._exit(seq=5, related_entry_seq=8, at=(NOW - timedelta(hours=2)).isoformat()),
            self._entry(seq=8, at=(NOW - timedelta(minutes=10)).isoformat()),
            self._exit(seq=6, related_entry_seq=7, stale=True),
            self._entry(seq=7),
            self._exit(seq=11, related_entry_seq=10, ticker=""),
            self._entry(seq=10),
            self._entry(seq=12),
        ]
        ingested = brain.ingest_shadow_exits(ledger)
        reasons = [item["reason"] for item in ingested["excluded"]]
        self.assertEqual(ingested["clean_n"], 0)
        self.assertIn("SYNTHETIC_NOT_LIVE_SHADOW", reasons)
        self.assertIn("FEE_UNKNOWN", reasons)
        self.assertIn("TIMESTAMP_INCONSISTENT", reasons)
        self.assertIn("STALE_PRICE", reasons)
        self.assertIn("IDENTITY_UNKNOWN", reasons)
        self.assertIn("INCOMPLETE", reasons)
        self.assertTrue(all(item["source"] != "live_shadow" or item["reason"] != "SYNTHETIC_NOT_LIVE_SHADOW" for item in ingested["excluded"]))

    def test_feature_comparison_uses_the_same_trade_ids(self):
        first = self._entry()
        second = self._entry(seq=3, at=(NOW - timedelta(minutes=40)).isoformat(), side="SHORT")
        exits = [
            self._exit(features={"credit_ratio": {"value": 5.0, "available_at": PAST}}),
            self._exit(seq=4, related_entry_seq=3, side="SHORT", fill_pnl_per_share_yen=-10.0, features={}),
        ]
        ingested = brain.ingest_shadow_exits([first, second, *exits])
        self.assertEqual(ingested["clean_n"], 2)
        mismatched = brain.paired_feature_comparison(ingested["trials"], "credit_ratio")
        self.assertEqual(mismatched["population_status"], "POPULATION_MISMATCH")
        self.assertIsNone(mismatched["delta_ev"])
        self.assertEqual(mismatched["baseline_n"], 2)
        self.assertEqual(mismatched["feature_n"], 1)
        for trial in ingested["trials"]:
            trial["features"] = {"credit_ratio": {"value": 5.0, "available_at": PAST}}
        recorded = brain.paired_feature_comparison(ingested["trials"], "credit_ratio")
        self.assertEqual(recorded["population_status"], "FEATURE_RECORDED_MODEL_NOT_APPLIED")
        self.assertEqual(recorded["baseline_n"], recorded["feature_n"])
        self.assertIsNone(recorded["delta_ev"])
        self.assertFalse(recorded["edge_claim"])

    def test_research_data_lane_does_not_adopt_unfetched_sources(self):
        lane = brain.research_data_lane()
        self.assertEqual([item["id"] for item in lane if item["priority"] == 1], ["nt_ratio", "investor_futures_flow", "futures_options_positioning"])
        self.assertLess(lane[0]["priority"], next(item["priority"] for item in lane if item["id"] == "short_sale_ratio"))
        self.assertLess(
            next(item["priority"] for item in lane if item["id"] == "crude"),
            next(item["priority"] for item in lane if item["id"] == "official_speech"),
        )
        self.assertTrue(all(item["fetch_status"] == "NOT_FETCHED" and item["trading_adoption"] is False for item in lane))
        shikiho = next(item for item in lane if item["id"] == "shikiho_fundamentals")
        self.assertIn("転載しない", shikiho["license"])

    def test_module_does_not_submit_or_edit_the_live_rule(self):
        text = (ROOT / "scripts" / "ai_brain_research.py").read_text(encoding="utf-8")
        self.assertNotIn("submit_shadow_order", text)
        self.assertNotIn("shadow_execution", text)
        self.assertNotIn("apply_cycle", text)
        self.assertNotIn("real_submit_allowed = True", text)
        self.assertNotIn('real_submit_allowed"] = True', text)
