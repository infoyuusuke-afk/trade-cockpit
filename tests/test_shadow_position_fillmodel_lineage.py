import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
JST = timezone(timedelta(hours=9))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ec = _load('ec', 'scripts/execution_contract.py')
se = _load('se', 'scripts/shadow_execution.py')
sp = _load('sp', 'scripts/shadow_position.py')

NOW = datetime(2026, 9, 17, 9, 0, 0, tzinfo=JST)
SUBMITTED_AT = NOW - timedelta(seconds=10)


def build_intent(**overrides):
    kwargs = dict(
        symbol="285A.T", side="BUY", quantity=100, order_type="LIMIT",
        limit_price=1500.0, planned_entry=1500.0, planned_stop=1450.0, planned_target=1600.0,
        strategy_id="day_ifo_long", strategy_version="1.0",
        decision_snapshot_id="snap-1", signal_known_at="2026-09-17T08:55:00+09:00",
        risk_policy_version="risk-gate-0.1.0", execution_policy_version="exec-v0.1",
        shadow_fill_model_version="shadow-fill-model-0.1", merge_hash="m" * 64,
    )
    kwargs.update(overrides)
    return ec.build_intent(**kwargs)


def entry_intent(**overrides):
    kwargs = dict(order_type="MARKET", limit_price=None)
    kwargs.update(overrides)
    return build_intent(**kwargs)


def risk_decision(**overrides):
    base = {
        "decision": "PASS", "merge_hash": "m" * 64, "allowed_qty": 100,
        "symbol": "285A.T", "side": "BUY", "policy_version": "risk-gate-0.1.0",
    }
    base.update(overrides)
    return base


def ticket(intent, **overrides):
    base = {
        "permission_status": "ORDER_TICKET_READY",
        "intent_hash": intent["intent_hash"],
        "merge_hash": intent["merge_hash"],
        "ticket_fingerprint": "fp-" + "a" * 60,
    }
    base.update(overrides)
    return base


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


def submit(intent, decision, tkt, *, known_orders=None, submitted_at=SUBMITTED_AT, now=NOW):
    return se.submit_shadow_order(intent, decision, tkt, known_orders=[] if known_orders is None else known_orders,
                                   submitted_at=submitted_at, now=now)


def filled_order(intent, **obs_overrides):
    """entry_intent()から生成したShadow Orderへ1回のobservationを適用し、
    Shadow Positionテストの入力として使うfilled/partial-filledなShadow
    Orderを作るテストヘルパー。observed_at/decisionはtest_shadow_execution.py
    と同じ規約（NOW, PASS/ORDER_TICKET_READY）を踏襲する。"""
    order = submit(intent, risk_decision(), ticket(intent))
    return se.evaluate_shadow_fill(order, observation(**obs_overrides), now=NOW)


class FillModelLineageBoundaryTest(unittest.TestCase):
    def test_position_rejects_intent_order_fill_model_version_mismatch(self):
        intent=entry_intent()
        order=filled_order(intent)
        tampered=dict(order)
        tampered["shadow_fill_model_version"]="shadow-fill-model-other"
        # Rebind order identity/fingerprint so the test isolates the cross-object lineage invariant.
        tampered["shadow_order_id"]=se.compute_shadow_order_id(tampered["intent_hash"],tampered["shadow_fill_model_version"])
        tampered["submission_context_fingerprint"]=se.compute_submission_context_fingerprint(tampered["shadow_order_id"],tampered["submitted_at"])
        tampered["order_context_fingerprint"]=se.compute_order_context_fingerprint(shadow_order_id=tampered["shadow_order_id"],intent_hash=tampered["intent_hash"],merge_hash=tampered["merge_hash"],ticket_fingerprint=tampered["ticket_fingerprint"],symbol=tampered["symbol"],side=tampered["side"],order_type=tampered["order_type"],limit_price=tampered["limit_price"],requested_qty=tampered["requested_qty"],shadow_fill_model_version=tampered["shadow_fill_model_version"],submitted_at=tampered["submitted_at"])
        out=sp.create_shadow_position(intent,tampered,now=NOW,known_positions=[])
        self.assertEqual(out["status"],"REJECTED")
        self.assertIn("REJECTED_LINEAGE_FILL_MODEL_VERSION_MISMATCH",out["reject_reasons"])
