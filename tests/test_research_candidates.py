import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.lead_lag_research import MIN_OBSERVATIONS, design_status, evaluate_pair
from scripts.research_candidates import UNIVERSE_SCOPE, candidate_from_observation, publish_production
from scripts.research_lane_arbitrage import LATEST

ROOT = Path(__file__).resolve().parents[1]


def _observation(**overrides):
    row = {
        "symbol": "7203.T",
        "side": "LONG",
        "candidate_created_at": "2026-10-06T09:10:00+09:00",
        "entry_candidate_at": "2026-10-06T09:11:00+09:00",
        "source_generator": "precision_watch",
        "trigger": "限定監視の条件",
        "main_reasons": ["出来高", "VWAP"],
        "market_regime": "RANGE",
        "available_at": "2026-10-06T09:10:00+09:00",
        "data_quality": "OK",
        "trading_adoption": False,
        "real_submit_allowed": False,
        "execution_authority": False,
    }
    row.update(overrides)
    return row


class ResearchCandidateTests(unittest.TestCase):
    def test_a_market_total_does_not_become_a_symbol(self):
        total = json.loads(LATEST.read_text(encoding="utf-8"))
        self.assertIsNone(candidate_from_observation(total))
        self.assertIsNone(candidate_from_observation({"id": "short_sale_ratio", "symbol": "285A.T", "side": "LONG"}))
        self.assertIsNone(candidate_from_observation(_observation(data_quality="STALE")))
        self.assertIsNone(candidate_from_observation(_observation(fixture=True)))
        self.assertIsNone(candidate_from_observation(_observation(universe_scope="FULL")))
        self.assertIsNone(candidate_from_observation(_observation(universe_scope="市場全体から選出")))
        self.assertIsNone(candidate_from_observation(_observation(available_at="2026-10-06T09:12:00+09:00")))
        made = candidate_from_observation(_observation())
        self.assertTrue(made["candidate_id"].startswith("rc-"))
        self.assertEqual(made["universe_scope"], UNIVERSE_SCOPE)
        self.assertEqual(made["side"], "LONG")
        self.assertEqual(made["main_reasons"], "出来高 / VWAP")
        self.assertFalse(made["price_fresh"])
        self.assertFalse(made["real_submit_allowed"])
        self.assertFalse(made["trading_adoption"])
        again = candidate_from_observation(made)
        self.assertEqual(again["candidate_id"], made["candidate_id"])

    def test_production_file_keeps_real_rows_and_drops_fixtures(self):
        made = candidate_from_observation(_observation())
        fixture = dict(made, fixture=True, candidate_id="cand-1", symbol="285A.T")
        total = json.loads(LATEST.read_text(encoding="utf-8"))
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = publish_production(
                [fixture, total, made],
                candidates_path=root / "candidates.jsonl",
                latest_path=root / "latest.json",
            )
            stored = (root / "candidates.jsonl").read_text(encoding="utf-8")
            self.assertEqual(payload["production_candidate_count"], 1)
            self.assertEqual(payload["universe_scope"], UNIVERSE_SCOPE)
            self.assertNotIn("cand-1", stored)
            self.assertNotIn("285A.T", stored)
            self.assertNotIn("証券会社", stored)
            self.assertIn(made["candidate_id"], stored)
            self.assertFalse(payload["real_submit_allowed"])
            self.assertFalse(payload["live_signal_changed"])

    def test_entry_rules_stay_fixed(self):
        import ai_shadow_supervisor as supervisor

        self.assertEqual(
            supervisor.LONG_ENTRY_SIGNALS,
            frozenset({"初動買い候補", "買いサイン", "持ち越しロング確定"}),
        )
        self.assertEqual(
            supervisor.SHORT_ENTRY_SIGNALS,
            frozenset({"初動ショート候補", "空売りサイン", "持ち越しショート確定"}),
        )

    def test_lead_lag_design_stores_no_coefficient(self):
        status = design_status()
        self.assertEqual(status["status"], "DESIGN_ONLY")
        self.assertEqual(status["measured_pairs"], 0)
        self.assertEqual(status["correlation"], "NOT AVAILABLE")
        self.assertEqual(status["lead_lag"], "NOT AVAILABLE")
        self.assertEqual(status["universe_scope"], UNIVERSE_SCOPE)
        self.assertFalse(status["market_totals_are_symbol_leads"])
        self.assertFalse(status["trading_adoption"])
        self.assertFalse(status["real_submit_allowed"])
        short = [{"session_date": "2026-10-01", "available_at": "2026-10-02T16:00:00+09:00", "value": 1}]
        self.assertEqual(evaluate_pair(short, short)["reason"], "INSUFFICIENT_OR_UNALIGNED")
        rows = [
            {
                "session_date": f"2026-01-{day:02d}",
                "available_at": f"2026-01-{day:02d}T16:00:00+09:00",
                "value": day,
            }
            for day in range(1, MIN_OBSERVATIONS + 1)
        ]
        opened = evaluate_pair(rows, rows)
        self.assertEqual(opened["reason"], "GATE_OPEN_NOT_COMPUTED")
        self.assertEqual(opened["measured_pairs"], 0)
        self.assertEqual(opened["correlation"], "NOT AVAILABLE")
        self.assertNotIn("coefficient", json.dumps(opened))
        leaked = evaluate_pair(rows, [dict(row, fixture=True) for row in rows])
        self.assertEqual(leaked["measured_pairs"], 0)
        self.assertEqual(leaked["correlation"], "NOT AVAILABLE")
