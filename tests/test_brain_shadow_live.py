import json
import unittest
from pathlib import Path

from scripts.brain_shadow_live import (
    AUTHORITY,
    FORBIDDEN_LABEL,
    INSUFFICIENT_SAMPLE,
    NOT_AVAILABLE,
    SHADOW_BANNER,
    live_view,
    publish_live_view,
)
from scripts.shadow_trade_ledger import SOURCE_LIVE, SOURCE_SYNTHETIC, build_shadow_trade

ROOT = Path(__file__).resolve().parents[1]


def _candidate(**overrides):
    row = {
        "candidate_id": "cand-1",
        "symbol": "285A.T",
        "side": "LONG",
        "discovered_at": "2026-10-06T09:34:18+09:00",
        "entry_candidate_at": "2026-10-06T09:35:00+09:00",
        "entry_trigger": "OR5上抜け + VWAP維持",
        "price": 19120,
        "price_fresh": True,
        "reason": "半導体が先行",
        "candidate_generator": "research_lane",
        "correlation": "半導体指数",
        "lead_lag": "先導銘柄",
        "market_regime": "RANGE",
        "universe_scope": "LIMITED / PRECISION_WATCH_ONLY",
        "execution_authority": False,
        "real_submit_allowed": False,
    }
    row.update(overrides)
    return row


def _exit(**overrides):
    row = {
        "record_class": "shadow_trade",
        "trade_id": "285A.T|LONG|7",
        "symbol": "285A.T",
        "side": "LONG",
        "strategy": "BASELINE",
        "model_id": "BASELINE",
        "entry_seq": 7,
        "entry_fill_at": "2026-10-06T09:36:42+09:00",
        "entry_price": 19120,
        "exit_fill_at": "2026-10-06T10:05:00+09:00",
        "gross_pnl": 40,
        "source_stage": SOURCE_LIVE,
        "data_quality": "OK",
        "candidate_id": "cand-1",
        "commission": "FEE_UNKNOWN",
        "real_submit_allowed": False,
        "quantity": None,
    }
    row.update(overrides)
    return row


class BrainShadowLiveTests(unittest.TestCase):
    def test_empty_view_keeps_brain_off_the_entry(self):
        view = live_view()
        self.assertEqual(view["brain"]["authority"], AUTHORITY)
        self.assertFalse(view["brain"]["execution_authority"])
        self.assertEqual(view["brain"]["side"], NOT_AVAILABLE)
        self.assertEqual(view["brain"]["symbol"], NOT_AVAILABLE)
        self.assertEqual(view["brain"]["price"], NOT_AVAILABLE)
        self.assertEqual(view["brain"]["ev_pf_n"], INSUFFICIENT_SAMPLE)
        self.assertTrue(view["brain"]["research_status"].startswith("FETCHED "))
        self.assertIn("trading_adoption=false", view["brain"]["research_status"])
        self.assertEqual(view["shadow"]["state"], "WAITING")
        self.assertEqual(view["shadow"]["banner"], SHADOW_BANNER)
        self.assertEqual(view["shadow"]["fill"], NOT_AVAILABLE)
        self.assertFalse(view["link"]["linked"])
        self.assertEqual(view["accuracy"]["selection"], INSUFFICIENT_SAMPLE)
        self.assertFalse(view["real_submit_allowed"])
        self.assertFalse(view["live_signal_changed"])
        blob = json.dumps(view, ensure_ascii=False)
        self.assertNotIn(FORBIDDEN_LABEL, blob)

    def test_execution_claim_and_stale_price_are_not_a_candidate(self):
        claimed = live_view([_candidate(execution_authority=True)])
        self.assertEqual(claimed["brain"]["symbol"], NOT_AVAILABLE)
        wide = live_view([_candidate(universe_scope="FULL")])
        market = live_view([_candidate(universe_scope="市場全体から選出")])
        self.assertEqual(wide["brain"]["symbol"], NOT_AVAILABLE)
        self.assertEqual(market["brain"]["symbol"], NOT_AVAILABLE)
        self.assertEqual(wide["brain"]["universe_scope"], "LIMITED / PRECISION_WATCH_ONLY")
        watched = live_view([_candidate(side="WATCH")])
        self.assertEqual(watched["brain"]["side"], "WATCH")
        stale = live_view([_candidate(price_fresh=False)])
        self.assertEqual(stale["brain"]["symbol"], "285A.T")
        self.assertEqual(stale["brain"]["side"], "LONG CANDIDATE")
        self.assertEqual(stale["brain"]["price"], NOT_AVAILABLE)
        self.assertNotIn("ENTRY", stale["brain"]["side"])
        self.assertEqual(stale["brain"]["authority"], AUTHORITY)

    def test_shadow_fill_stays_off_the_brain_card_until_ids_match(self):
        unrelated = live_view([_candidate(candidate_id="cand-brain")], [_exit(candidate_id="cand-shadow")])
        self.assertEqual(unrelated["brain"]["discovered_at"], "2026-10-06T09:34:18+09:00")
        self.assertEqual(unrelated["shadow"]["state"], "EXIT")
        self.assertEqual(unrelated["shadow"]["fill"], "19,120円")
        self.assertEqual(unrelated["shadow"]["entry_at"], "2026-10-06T09:36:42+09:00")
        self.assertEqual(unrelated["shadow"]["pnl"], "+40円/株")
        self.assertFalse(unrelated["link"]["linked"])
        self.assertTrue(all(item["at"] == NOT_AVAILABLE for item in unrelated["timeline"]))
        self.assertEqual(unrelated["brain"]["ev_pf_n"], INSUFFICIENT_SAMPLE)

        joined = live_view([_candidate()], [_exit()])
        self.assertTrue(joined["link"]["linked"])
        self.assertEqual(joined["link"]["trade_id"], "285A.T|LONG|7")
        clocks = {item["phase"]: item["at"] for item in joined["timeline"]}
        self.assertEqual(clocks["brain_discovered"], "2026-10-06T09:34:18+09:00")
        self.assertEqual(clocks["shadow_entry"], "2026-10-06T09:36:42+09:00")
        self.assertEqual(clocks["shadow_exit"], "2026-10-06T10:05:00+09:00")
        self.assertEqual(clocks["result"], "+40円/株")

    def test_synthetic_and_stale_rows_do_not_become_the_live_shadow(self):
        synthetic = live_view([], [_exit(source_stage=SOURCE_SYNTHETIC)])
        stale = live_view([], [_exit(data_quality="STALE")])
        self.assertEqual(synthetic["shadow"]["state"], "WAITING")
        self.assertEqual(stale["shadow"]["state"], "WAITING")
        opened = live_view([], [], [{
            "event_type": "virtual_entry",
            "ticker": "285A.T",
            "side": "LONG",
            "strategy": "BASELINE",
            "at": "2026-10-06T09:36:42+09:00",
            "fill_price": 19120,
            "candidate_id": "cand-1",
            "real_submit_allowed": False,
            "quantity": None,
        }])
        self.assertEqual(opened["shadow"]["state"], "ENTRY")
        self.assertEqual(opened["shadow"]["fill"], "19,120円")
        self.assertEqual(opened["shadow"]["pnl"], NOT_AVAILABLE)
        held = live_view([], [], [{
            "event_type": "virtual_entry",
            "ticker": "285A.T",
            "side": "SHORT",
            "strategy": "BASELINE",
            "at": "2026-10-06T09:36:42+09:00",
            "marked_at": "2026-10-06T09:40:00+09:00",
            "fill_price": 19120,
            "mark_price": 19080,
            "mark_fresh": True,
            "real_submit_allowed": False,
            "quantity": None,
        }])
        self.assertEqual(held["shadow"]["state"], "IN POSITION")
        self.assertEqual(held["shadow"]["side"], "SHORT")
        self.assertEqual(held["shadow"]["pnl"], "+40円/株")
        synthetic_open = live_view([], [], [{
            "event_type": "virtual_entry",
            "acceptance_class": "synthetic",
            "ticker": "285A.T",
            "side": "LONG",
            "at": "2026-10-06T09:36:42+09:00",
            "fill_price": 19120,
            "real_submit_allowed": False,
            "quantity": None,
        }])
        self.assertEqual(synthetic_open["shadow"]["state"], "WAITING")

    def test_candidate_id_is_recorded_without_becoming_an_entry_signal(self):
        import ai_shadow_supervisor as supervisor

        row = supervisor.entry_candidate({
            "ticker": "285A.T",
            "signal": "買いサイン",
            "strategy": "OR15",
            "price": 1500.0,
            "entry_price": 1500.0,
            "stop_price": 1450.0,
            "source_timestamp": "09:16:00",
            "data": "LIVE",
            "candidate_id": "cand-9",
        })
        self.assertEqual(row["candidate_id"], "cand-9")
        self.assertNotIn("candidate_id", supervisor.entry_candidate({
            "ticker": "285A.T",
            "signal": "買いサイン",
            "strategy": "OR15",
            "price": 1500.0,
            "entry_price": 1500.0,
            "stop_price": 1450.0,
            "source_timestamp": "09:16:00",
            "data": "LIVE",
        }))
        trade = build_shadow_trade(
            {"seq": 3, "at": "2026-10-06T09:36:42+09:00", "source_timestamp": "09:36:00", "candidate_id": "cand-9", "bid": 19110, "ask": 19130},
            {"ticker": "285A.T", "side": "LONG", "strategy": "BASELINE", "fill_entry_price": 19120, "fill_exit_price": 19180, "entry_slippage_yen": 10, "exit_slippage_yen": 10, "fill_pnl_per_share_yen": 60, "mae_yen": 20, "mfe_yen": 80, "at": "2026-10-06T10:00:00+09:00"},
            exit_signal_at="10:00:00",
            source_stage=SOURCE_LIVE,
            data_quality="OK",
        )
        self.assertEqual(trade["candidate_id"], "cand-9")
        self.assertFalse(trade["real_submit_allowed"])
        text = (ROOT / "scripts" / "ai_shadow_supervisor.py").read_text(encoding="utf-8")
        self.assertIn("LONG_ENTRY_SIGNALS = frozenset", text)

    def test_control_page_splits_the_two_cards(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("trade_control.js?v=research-candidate-1", page)
        self.assertIn("AI BRAIN LIVE", script)
        self.assertIn("AI SHADOW LIVE", script)
        self.assertIn(AUTHORITY, script)
        self.assertIn(SHADOW_BANNER, script)
        self.assertIn('text.includes("BRAIN ENTRY")', script)
        self.assertNotIn("BRAIN ENTRY:", script)
        published = publish_live_view(ROOT)
        saved = json.loads((ROOT / "brain_shadow_live.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, published)
        self.assertEqual(saved["shadow"]["state"], "WAITING")
        self.assertEqual(saved["brain"]["ev_pf_n"], INSUFFICIENT_SAMPLE)
        self.assertEqual(saved["brain"]["authority"], AUTHORITY)
        self.assertEqual(saved["brain"]["universe_scope"], "LIMITED / PRECISION_WATCH_ONLY")
        self.assertEqual(saved["brain"]["symbol"], NOT_AVAILABLE)
        self.assertEqual(saved["brain"]["production_candidate_count"], 0)
        self.assertEqual(saved["brain"]["linked_candidate_count"], 0)
        self.assertEqual(saved["brain"]["shadow_entry_count"], 0)
        self.assertEqual(saved["brain"]["lead_lag_engine"], "DESIGN_ONLY / NOT MEASURED")
        self.assertIn("FETCHED 3/17", saved["brain"]["research_status"])
        self.assertNotIn("cand-1", json.dumps(saved))
        stored = ROOT / "data" / "research_candidates" / "candidates.jsonl"
        self.assertTrue(stored.exists())
        self.assertNotIn("cand-1", stored.read_text(encoding="utf-8"))
        self.assertNotIn("285A", stored.read_text(encoding="utf-8"))
        self.assertFalse(saved["real_submit_allowed"])
