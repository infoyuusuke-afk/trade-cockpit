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
        self.assertEqual(m.synthetic_demo(), "PASS: SYNTHETIC_OWNER_TO_SHADOW_CORE_NO_REAL_ORDER")

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

    def synthetic_execution_inputs(self):
        start = self.now
        now = self.now + timedelta(seconds=2)
        policy = {
            "policy_version": "execution-safety-0.1.0",
            "max_ticket_age_sec": 15,
            "max_price_drift_bps": 50,
            "authorization_ttl_sec": 3600,
            "master_kill_ttl_sec": 3600,
            "daily_stop_yen": 3000,
            "max_open_positions": 1,
        }
        risk = {
            "decision": "PASS", "merge_hash": "m" * 64,
            "allowed_qty": 100, "symbol": "285A", "side": "BUY",
            "policy_version": "risk-gate-0.1.0", "horizon": "day",
        }
        snap = {
            "simulation_only": True,
            "kill_switch": {
                "status": "ARMED", "armed_at": start.isoformat(),
                "expires_at": (start + timedelta(seconds=3600)).isoformat(),
            },
            "human_session_authorized": True,
            "authorization_issued_at": start.isoformat(),
            "authorization_expires_at": (start + timedelta(seconds=3600)).isoformat(),
            "authorization_session_id": "MOCK_NOT_AUTHENTICATED",
            "data_freshness": "OK",
            "market_session_allowed": True,
            "symbol_tradeable": True,
            "broker_link_health": "OK",
            "conflict_state": "CANDIDATE_READY",
            "expected_position_qty": 0,
            "broker_position_qty": 0,
            "buying_power_check": True,
            "short_availability_check": True,
            "realized_pnl_today_yen": 0.0,
            "open_positions_count": 0,
            "known_intents": [],
            "pending_orders": [],
            "price_tick_valid": True,
            "qty_lot_valid": True,
            "quote_price": 2000.0,
            "quote_asof": (start + timedelta(seconds=1)).isoformat(),
            "broker_snapshot_fingerprint": "SYNTHETIC_FIXTURE_NOT_A_REAL_BROKER",
        }
        return {
            "now": now, "quote_price": 2000.0,
            "quote_asof": (start + timedelta(seconds=1)).isoformat(),
            "risk_decision": risk,
            "simulated_broker_snapshot": snap,
            "execution_policy": policy,
            "known_shadow_orders": [],
        }

    def test_existing_permission_and_shadow_engine_are_really_called(self):
        ticket, pending = self.create()
        decision = self.decide(pending)
        args = self.synthetic_execution_inputs()
        out = m.dispatch_synthetic_shadow_order(ticket, pending, decision, **args)
        self.assertEqual(out["state"], "SIMULATED_SHADOW_ORDER_NEW", out)
        self.assertEqual(out["shadow_status"], "NEW")
        self.assertEqual(len(out["shadow_order_id"]), 64)
        self.assertFalse(out["real_submit_allowed"])
        self.assertNotIn("broker_order_id", out)

    def test_core_shadow_duplicate_guard_refuses_second_order(self):
        ticket, pending = self.create()
        decision = self.decide(pending)
        args = self.synthetic_execution_inputs()
        first = m.dispatch_synthetic_shadow_order(ticket, pending, decision, **args)
        self.assertEqual(first["state"], "SIMULATED_SHADOW_ORDER_NEW", first)
        args["known_shadow_orders"] = [{
            "shadow_order_id": first["shadow_order_id"], "real_submit_allowed": False,
        }]
        second = m.dispatch_synthetic_shadow_order(ticket, pending, decision, **args)
        self.assertEqual(second["state"], "BLOCKED")
        self.assertIn("DUPLICATE_IGNORED", second["reason"])

    def test_core_permission_master_kill_disarmed_is_blocked(self):
        ticket, pending = self.create()
        decision = self.decide(pending)
        args = self.synthetic_execution_inputs()
        args["simulated_broker_snapshot"]["kill_switch"]["status"] = "DISARMED"
        out = m.dispatch_synthetic_shadow_order(ticket, pending, decision, **args)
        self.assertEqual(out["state"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_DISARMED", out.get("block_reasons", []))

    def test_core_requires_simulated_broker_snapshot_and_risk_lineage(self):
        ticket, pending = self.create()
        decision = self.decide(pending)
        args = self.synthetic_execution_inputs()
        args["simulated_broker_snapshot"]["simulation_only"] = False
        out = m.dispatch_synthetic_shadow_order(ticket, pending, decision, **args)
        self.assertEqual(out["state"], "BLOCKED")
        args = self.synthetic_execution_inputs()
        args["risk_decision"]["allowed_qty"] = 200
        out = m.dispatch_synthetic_shadow_order(ticket, pending, decision, **args)
        self.assertEqual(out["state"], "BLOCKED")
        self.assertIn("BLOCK_RISK_LINEAGE_MISMATCH", out.get("block_reasons", []))

    def test_owner_label_is_not_device_authentication(self):
        source = inspect.getsource(m)
        self.assertIn("NOT identity authentication", source)
        self.assertIn("never calls a broker", source)
        self.assertNotIn("RssOrder(", source)
        self.assertFalse(m.evaluate_shadow_handoff.__doc__ is None)


if __name__ == "__main__":
    unittest.main()
