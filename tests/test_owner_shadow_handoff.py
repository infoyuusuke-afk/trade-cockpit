"""Synthetic Owner mobile review only: no broker, no device authentication."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import inspect
import unittest

from scripts import owner_approval_queue as q
from scripts import owner_shadow_handoff as m

JST = timezone(timedelta(hours=9))


class ShadowHandoffAcceptance(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 5, 9, 0, 0, tzinfo=JST)
        self.signals = {
            "updated_at": self.now.isoformat(),
            "prepared": [{
                "code": "285A", "name": "合成テスト専用",
                "action": "LONG", "strategy_key": "SYNTHETIC_OR15",
                "signal_date": "2026-01-05", "trigger": 2000.0,
                "stop": 1995.0, "data_freshness_sec": 0,
            }],
        }
        self.cal = {"groups": {"SYNTHETIC_OR15": {
            "risk_gate": "PASS", "risk_reason": "OK",
            "ev_score": 80, "sample_size": 100,
            "profit_factor": 1.5, "avg_pl_pct": 0.2,
        }}}
        self.proof = {
            "kind": "MS2_RSS_WORKBOOK",
            "machine_use_permitted": True,
            "source_authenticated": True,
            "rights_reference": "SYNTHETIC_FIXTURE_ONLY",
            "observed_at": self.now.isoformat(),
            "available_at": self.now.isoformat(),
        }

    def create(self):
        return m.create_paper_review(
            self.signals, self.cal, self.proof, now=self.now, quantity=100)

    def decide(self, pending, choice="APPROVE"):
        return m.simulate_owner_decision(
            pending, choice,
            decided_at=(self.now + timedelta(seconds=1)).isoformat())

    def evaluate(self, ticket, pending, decision, **kw):
        args = {
            "now": self.now + timedelta(seconds=2),
            "quote_price": 2000.0,
            "quote_asof": (self.now + timedelta(seconds=1)).isoformat(),
        }
        args.update(kw)
        return m.evaluate_shadow_handoff(ticket, pending, decision, **args)

    def test_synthetic_end_to_end_owner_review_to_shadow_ready(self):
        ticket, pending = self.create()
        self.assertEqual(pending["approval_type"], "SHADOW_REVIEW")
        self.assertEqual(pending["status"], "PENDING_OWNER")
        self.assertFalse(pending["auto_approve"])
        self.assertFalse(ticket["real_submit_allowed"])
        decision = self.decide(pending)
        result = self.evaluate(ticket, pending, decision)
        self.assertEqual(result["state"], "SIMULATED_SHADOW_READY")
        self.assertFalse(result["real_submit_allowed"])
        self.assertNotIn("broker_order_id", result)
        self.assertEqual(m.synthetic_demo(), "PASS: SYNTHETIC_OWNER_PAPER_HANDOFF_ONLY")

    def test_no_automatic_approval_or_real_money_queue(self):
        ticket, pending = self.create()
        self.assertEqual(pending["approval_type"], "SHADOW_REVIEW")
        self.assertNotEqual(pending["approval_type"], "REAL_MONEY_SUBMIT")
        self.assertIs(pending["auto_approve"], False)
        blocked = self.evaluate(ticket, pending, pending)
        self.assertEqual(blocked["state"], "BLOCKED")

    def test_manual_simulated_reject_never_shadow_ready(self):
        ticket, pending = self.create()
        result = self.evaluate(ticket, pending, self.decide(pending, "REJECT"))
        self.assertEqual(result["state"], "REJECTED")
        self.assertFalse(result["real_submit_allowed"])

    def test_model_source_unverified_rejected(self):
        for key, value in (
            ("machine_use_permitted", False),
            ("source_authenticated", False),
            ("kind", "TRADINGVIEW"),
            ("rights_reference", ""),
        ):
            with self.subTest(key=key):
                backup = self.proof[key]
                self.proof[key] = value
                with self.assertRaises(ValueError):
                    self.create()
                self.proof[key] = backup

    def test_market_observation_stale_future_and_undated_rejected(self):
        for value in (
            (self.now - timedelta(seconds=30)).isoformat(),
            (self.now + timedelta(seconds=1)).isoformat(),
            "2026-01-05T09:00:00",
            "INVALID",
        ):
            with self.subTest(value=value):
                self.proof["observed_at"] = value
                with self.assertRaises(ValueError):
                    self.create()

    def test_future_availability_rejected(self):
        self.proof["available_at"] = (self.now + timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            self.create()

    def test_stale_signal_and_candidate_quote_rejected(self):
        self.signals["updated_at"] = (self.now - timedelta(seconds=16)).isoformat()
        with self.assertRaises(ValueError):
            self.create()
        self.signals["updated_at"] = self.now.isoformat()
        self.signals["prepared"][0]["data_freshness_sec"] = 16
        with self.assertRaises(ValueError):
            self.create()

    def test_no_empirical_ev_or_pass_gate_rejected(self):
        for field, value in (
            ("risk_gate", "BLOCK"),
            ("sample_size", 29),
            ("profit_factor", 0.9),
            ("avg_pl_pct", -0.2),
            ("ev_score", float("nan")),
        ):
            with self.subTest(field=field):
                original = self.cal["groups"]["SYNTHETIC_OR15"][field]
                self.cal["groups"]["SYNTHETIC_OR15"][field] = value
                with self.assertRaises(ValueError):
                    self.create()
                self.cal["groups"]["SYNTHETIC_OR15"][field] = original

    def test_quantity_lot_risk_notional_and_stop_geometry(self):
        for qty in (0, -100, True, 25, 200):
            with self.subTest(qty=qty):
                with self.assertRaises(ValueError):
                    m.create_paper_review(
                        self.signals, self.cal, self.proof, now=self.now, quantity=qty)
        self.signals["prepared"][0]["stop"] = 2001.0
        with self.assertRaises(ValueError):
            self.create()

    def test_ticket_mutation_invalidates_simulated_approval(self):
        for key, value in (
            ("quantity", 200),
            ("limit_price", 2100.0),
            ("stop_price", 1800.0),
            ("side", "SELL"),
            ("company_name", "改ざん"),
            ("real_submit_allowed", True),
        ):
            with self.subTest(key=key):
                ticket, pending = self.create()
                decision = self.decide(pending)
                ticket[key] = value
                result = self.evaluate(ticket, pending, decision)
                self.assertEqual(result["state"], "BLOCKED")
                self.assertFalse(result["real_submit_allowed"])

    def test_queue_or_approval_forgery_blocked(self):
        ticket, pending = self.create()
        decision = self.decide(pending)
        for key, value in (
            ("approval_type", "REAL_MONEY_SUBMIT"),
            ("decided_by", "SYSTEM"),
            ("summary", {"mode": "PAPER_ONLY", "ticket_fingerprint": "FORGED"}),
            ("approval_id", "OTHER"),
        ):
            with self.subTest(key=key):
                altered = dict(decision)
                altered[key] = value
                result = self.evaluate(ticket, pending, altered)
                self.assertEqual(result["state"], "BLOCKED")

    def test_expiry_replay_and_stale_price_blocked(self):
        ticket, pending = self.create()
        decision = self.decide(pending)
        for kw in (
            {"now": self.now + timedelta(seconds=61)},
            {"consumed_ids": {ticket["request_id"]}},
            {"quote_asof": (self.now - timedelta(seconds=20)).isoformat()},
            {"quote_asof": (self.now + timedelta(seconds=5)).isoformat()},
            {"quote_price": 2012.0},
        ):
            with self.subTest(kw=kw):
                result = self.evaluate(ticket, pending, decision, **kw)
                self.assertEqual(result["state"], "BLOCKED")
                self.assertFalse(result["real_submit_allowed"])

    def test_valid_short_risk_direction_stays_paper_only(self):
        self.signals["prepared"][0]["action"] = "SHORT"
        self.signals["prepared"][0]["stop"] = 2005.0
        ticket, pending = self.create()
        self.assertEqual(ticket["side"], "SELL")
        self.assertEqual(self.evaluate(ticket, pending, self.decide(pending))["state"], "SIMULATED_SHADOW_READY")

    def test_owner_label_is_not_device_authentication(self):
        source = inspect.getsource(m)
        self.assertIn("NOT identity authentication", source)
        self.assertIn("never calls a broker", source)
        self.assertNotIn("RssOrder(", source)
        self.assertFalse(m.evaluate_shadow_handoff.__doc__ is None)


if __name__ == "__main__":
    unittest.main()
