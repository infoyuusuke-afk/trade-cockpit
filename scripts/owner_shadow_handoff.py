"""Synthetic-only AI candidate -> Owner review -> shadow handoff.

This is a pure in-memory rehearsal, NOT a live mobile authorization service:
- never reads private market files, network, credentials or broker state;
- never calls a broker, RssOrder, Excel, real orders or actual shadow fills;
- the owner_approval_queue 'OWNER' string is NOT identity authentication;
- a caller's source_proof is NOT cryptographically verified provenance.
All outputs keep real_submit_allowed=False. Real release needs separate
authenticated device and independent risk/provenance verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

from scripts import build_mobile_approvals, owner_approval_queue
from scripts import execution_contract, execution_permission, shadow_execution, shadow_fill_model

SCHEMA = "owner-shadow-handoff-1.0"
MAX_SOURCE_AGE_SECONDS = 15
REVIEW_TTL_SECONDS = 60
MAX_QUOTE_DRIFT_BPS = 50
MAX_NOTIONAL_YEN = 300_000
MAX_RISK_YEN = 750
APPROVAL_TYPE = "SHADOW_REVIEW"
VALID_SOURCES = frozenset({"MS2_RSS_WORKBOOK", "OFFICIAL_LICENSED_API"})


def _timestamp(value) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("timestamp invalid") from exc
    if parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed


def _now(value) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    return value


def _num(value, *, positive=True) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("finite numeric value required")
    if positive and value <= 0:
        raise ValueError("positive numeric value required")
    return float(value)


def _fresh(stamp: datetime, now: datetime, max_seconds: int) -> bool:
    age = (now - stamp).total_seconds()
    return 0 <= age <= max_seconds


def _digest(ticket: dict) -> str:
    fields = {k: v for k, v in ticket.items() if k != "ticket_fingerprint"}
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_paper_review(signals: dict, calibration: dict, source_proof: dict, *,
                        now: datetime, quantity: int, lot_size: int = 100,
                        candidate_index: int = 0) -> tuple[dict, dict]:
    """Reject unknown/stale/unlicensed/malformed inputs; create one paper review.

    Explicit source proof is an input to a PURE synthetic rehearsal only,
    not a claim that an LLM can certify vendor rights or trading provenance.
    """
    now = _now(now)
    if not isinstance(signals, dict) or not isinstance(calibration, dict):
        raise ValueError("signal and calibration dictionaries required")
    if not isinstance(source_proof, dict):
        raise ValueError("source proof required")
    if source_proof.get("kind") not in VALID_SOURCES:
        raise ValueError("source is not admitted")
    if source_proof.get("machine_use_permitted") is not True:
        raise ValueError("machine use rights not verified")
    if source_proof.get("source_authenticated") is not True:
        raise ValueError("source not authenticated")
    rights_reference = source_proof.get("rights_reference")
    if not isinstance(rights_reference, str) or not rights_reference.strip():
        raise ValueError("rights reference missing")
    observation = _timestamp(source_proof.get("observed_at"))
    availability = _timestamp(source_proof.get("available_at"))
    if not _fresh(observation, now, MAX_SOURCE_AGE_SECONDS):
        raise ValueError("market observation stale or future")
    if availability > observation or availability > now:
        raise ValueError("future or impossible public information availability")
    updated = _timestamp(signals.get("updated_at"))
    if not _fresh(updated, now, MAX_SOURCE_AGE_SECONDS):
        raise ValueError("signals stale or future")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity invalid")
    if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
        raise ValueError("lot size invalid")
    if quantity % lot_size:
        raise ValueError("quantity violates lot size")
    if isinstance(candidate_index, bool) or not isinstance(candidate_index, int):
        raise ValueError("candidate index invalid")
    if candidate_index < 0 or candidate_index >= 10:
        raise ValueError("candidate index out of scope")
    feed = build_mobile_approvals.build(signals, calibration, limit=10)
    if feed.get("mode") != "paper" or feed.get("schema_version") != 1:
        raise ValueError("mobile feed is not paper")
    candidates = feed.get("requests") or []
    if candidate_index >= len(candidates):
        raise ValueError("candidate not available")
    item = candidates[candidate_index]
    if item.get("paper_only") is not True or item.get("risk_gate") != "PASS":
        raise ValueError("candidate risk/EV gate is not PASS")
    if item.get("action") not in ("LONG", "SHORT"):
        raise ValueError("candidate direction unapproved")
    freshness = _num(item.get("data_freshness_sec"), positive=False)
    if not (0 <= freshness <= MAX_SOURCE_AGE_SECONDS):
        raise ValueError("candidate quote stale")
    sample = item.get("sample_size")
    if isinstance(sample, bool) or not isinstance(sample, int) or sample < 30:
        raise ValueError("insufficient empirical N")
    _num(item.get("ev_score"), positive=False)
    if _num(item.get("profit_factor")) <= 1:
        raise ValueError("PF not positive in synthetic gate")
    if _num(item.get("avg_pl_pct"), positive=False) <= 0:
        raise ValueError("expected return not positive in synthetic gate")
    symbol = item.get("symbol")
    name = item.get("name")
    strategy = item.get("strategy_key")
    if not all(isinstance(x, str) and x.strip() for x in (symbol, name, strategy)):
        raise ValueError("symbol/name/strategy missing")
    entry = _num(item.get("trigger_price"))
    stop = _num(item.get("stop_price"))
    if item["action"] == "LONG" and stop >= entry:
        raise ValueError("LONG stop direction invalid")
    if item["action"] == "SHORT" and stop <= entry:
        raise ValueError("SHORT stop direction invalid")
    notional = entry * quantity
    risk = abs(entry - stop) * quantity
    if notional > MAX_NOTIONAL_YEN or risk > MAX_RISK_YEN:
        raise ValueError("paper safety budget exceeded")
    request_id = item.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request ID missing")
    expires = now + timedelta(seconds=REVIEW_TTL_SECONDS)
    ticket = {
        "schema_version": SCHEMA,
        "mode": "PAPER_ONLY",
        "source_mode": source_proof["kind"],
        "rights_reference": rights_reference,
        "request_id": request_id,
        "symbol": symbol,
        "company_name": name,
        "side": "BUY" if item["action"] == "LONG" else "SELL",
        "strategy_key": strategy,
        "quantity": quantity,
        "limit_price": entry,
        "stop_price": stop,
        "notional_yen": notional,
        "risk_yen": risk,
        "sample_size": sample,
        "profit_factor": item["profit_factor"],
        "avg_pl_pct": item["avg_pl_pct"],
        "data_as_of": observation.isoformat(),
        "available_at": availability.isoformat(),
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "real_submit_allowed": False,
    }
    ticket["ticket_fingerprint"] = _digest(ticket)
    queue_item = owner_approval_queue.build_queue([{
        "approval_id": request_id,
        "approval_type": APPROVAL_TYPE,
        "created_at": ticket["created_at"],
        "summary": {
            "mode": "PAPER_ONLY",
            "ticket_fingerprint": ticket["ticket_fingerprint"],
            "real_submit_allowed": False,
        },
    }])[0]
    return ticket, queue_item


def simulate_owner_decision(queue_item: dict, decision: str, *, decided_at: str):
    """For TESTS ONLY; OWNER literal is not real identity authentication."""
    if not isinstance(queue_item, dict) or queue_item.get("approval_type") != APPROVAL_TYPE:
        raise ValueError("not a shadow review")
    return owner_approval_queue.decide(
        queue_item, decision, decided_at=decided_at, decided_by="OWNER"
    )


def evaluate_shadow_handoff(ticket: dict, pending: dict, decision: dict, *,
                            now: datetime, quote_price: float, quote_asof: str,
                            consumed_ids: set[str] | None = None) -> dict:
    """Only returns a synthetic shadow eligibility event, NEVER sends an order."""
    result = {
        "schema_version": SCHEMA,
        "state": "BLOCKED",
        "reason": "UNVERIFIED",
        "mode": "PAPER_ONLY",
        "real_submit_allowed": False,
    }
    try:
        now = _now(now)
        if not all(isinstance(obj, dict) for obj in (ticket, pending, decision)):
            raise ValueError("invalid input")
        if ticket.get("schema_version") != SCHEMA or ticket.get("mode") != "PAPER_ONLY":
            raise ValueError("not paper-only")
        if ticket.get("real_submit_allowed") is not False:
            raise ValueError("submit flag unsafe")
        if ticket.get("ticket_fingerprint") != _digest(ticket):
            raise ValueError("ticket fingerprint changed")
        ident = ticket.get("request_id")
        if not isinstance(ident, str) or not ident:
            raise ValueError("request ID missing")
        if consumed_ids is not None and ident in consumed_ids:
            raise ValueError("duplicate review ID")
        expected_summary = {
            "mode": "PAPER_ONLY", "ticket_fingerprint": ticket["ticket_fingerprint"],
            "real_submit_allowed": False,
        }
        if pending.get("approval_id") != ident or pending.get("approval_type") != APPROVAL_TYPE or pending.get("status") != "PENDING_OWNER" or pending.get("auto_approve") is not False or pending.get("summary") != expected_summary:
            raise ValueError("pending item lineage failed")
        if decision.get("approval_id") != ident or decision.get("approval_type") != APPROVAL_TYPE or decision.get("summary") != expected_summary or decision.get("auto_approve") is not False or decision.get("decided_by") != "OWNER":
            raise ValueError("decision lineage failed")
        if decision.get("status") == "OWNER_REJECTED":
            return {**result, "state": "REJECTED", "reason": "SIMULATED_OWNER_REJECTED"}
        if decision.get("status") != "OWNER_APPROVED":
            raise ValueError("no simulated Owner approval")
        start = _timestamp(ticket["created_at"])
        expiry = _timestamp(ticket["expires_at"])
        decided = _timestamp(decision.get("decided_at"))
        if not (start <= decided <= now <= expiry):
            raise ValueError("decision or ticket expired")
        quote_time = _timestamp(quote_asof)
        if not _fresh(quote_time, now, MAX_SOURCE_AGE_SECONDS):
            raise ValueError("quote stale or future")
        old = _num(ticket.get("limit_price"))
        new = _num(quote_price)
        drift_bps = abs(new - old) / old * 10_000
        if drift_bps > MAX_QUOTE_DRIFT_BPS:
            raise ValueError("quote drift exceeded")
        # This is NOT a shadow fill. An authenticated Owner device and real
        # permission/reconciliation path are deliberately absent.
        return {**result, "state": "SIMULATED_SHADOW_READY",
                "reason": "SYNTHETIC_REVIEW_PASSED",
                "request_id": ident, "ticket_fingerprint": ticket["ticket_fingerprint"]}
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {**result, "reason": str(exc)[:120]}


def dispatch_synthetic_shadow_order(ticket: dict, pending: dict, decision: dict, *,
                                    now: datetime, quote_price: float, quote_asof: str,
                                    risk_decision: dict, simulated_broker_snapshot: dict,
                                    execution_policy: dict,
                                    known_shadow_orders: list[dict]) -> dict:
    """Exercise ORIGINAL execution Permission/Reconfirmation/Shadow core in memory.

    Strictly MOCK_ONLY. This function intentionally cannot authenticate an
    actual Owner/device, broker/account/source data, or persistent duplicate ledger.
    It has no broker adapter, I/O, network access or order submission.
    """
    result = {
        "schema_version": SCHEMA, "mode": "PAPER_ONLY", "state": "BLOCKED",
        "reason": "UNVERIFIED", "real_submit_allowed": False,
    }
    checked = evaluate_shadow_handoff(ticket, pending, decision, now=now,
                                      quote_price=quote_price, quote_asof=quote_asof)
    if checked.get("state") != "SIMULATED_SHADOW_READY":
        return {**result, "reason": checked.get("reason", "PAPER_REVIEW_BLOCKED")}
    try:
        now = _now(now)
        if not all(isinstance(x, dict) for x in
                   (ticket, risk_decision, simulated_broker_snapshot, execution_policy)):
            raise ValueError("synthetic required dictionaries missing")
        if simulated_broker_snapshot.get("simulation_only") is not True:
            raise ValueError("not a synthetic broker snapshot")
        if not isinstance(known_shadow_orders, list):
            raise ValueError("known shadow orders list required")
        if not _fresh(_timestamp(ticket["data_as_of"]), now, MAX_SOURCE_AGE_SECONDS):
            raise ValueError("original market source stale at shadow handoff")
        if execution_policy.get("policy_version") != "execution-safety-0.1.0":
            raise ValueError("unsupported execution policy")
        # Bind the Owner-reviewed proposal to the canonical Intent lineage.
        # Simulation alone is not an authenticated confirmation for real money.
        intent = execution_contract.build_intent(
            symbol=ticket["symbol"], side=ticket["side"],
            quantity=ticket["quantity"], order_type="LIMIT",
            limit_price=ticket["limit_price"], planned_entry=ticket["limit_price"],
            planned_stop=ticket["stop_price"], planned_target=None,
            strategy_id=ticket["strategy_key"], strategy_version=SCHEMA,
            decision_snapshot_id=ticket["ticket_fingerprint"],
            signal_known_at=ticket["data_as_of"],
            risk_policy_version=risk_decision.get("policy_version"),
            execution_policy_version=execution_policy["policy_version"],
            shadow_fill_model_version=shadow_fill_model.FILL_MODEL_VERSION,
            merge_hash=risk_decision.get("merge_hash"),
        )
        # Existing execution_contract creates a wall-clock created_at. This
        # timestamp injection is ONLY allowed inside this synthetic harness.
        intent["created_at"] = now.isoformat()
        permission = execution_permission.evaluate_permission(
            intent, risk_decision, simulated_broker_snapshot, execution_policy, now=now)
        if permission.get("permission_status") != "ORDER_TICKET_READY":
            return {**result, "reason": "PERMISSION_" +
                    str(permission.get("permission_status")),
                    "block_reasons": permission.get("block_reasons")}
        reconfirm = execution_permission.evaluate_reconfirmation(
            intent, risk_decision, permission, simulated_broker_snapshot,
            execution_policy, now=now)
        if reconfirm.get("reconfirm_status") != "CONFIRM_READY":
            return {**result, "reason": "RECONFIRM_" +
                    str(reconfirm.get("reconfirm_status")),
                    "block_reasons": reconfirm.get("block_reasons")}
        shadow = shadow_execution.submit_shadow_order(
            intent, risk_decision, permission, known_orders=known_shadow_orders,
            submitted_at=now, now=now)
        if shadow.get("status") != "NEW" or shadow.get("real_submit_allowed") is not False:
            return {**result, "reason": "SHADOW_" + str(shadow.get("status")),
                    "block_reasons": shadow.get("reject_reasons")}
        return {
            **result,
            "state": "SIMULATED_SHADOW_ORDER_NEW",
            "reason": "PURE_CORE_SHADOW_CREATED_NO_FILL",
            "shadow_order_id": shadow["shadow_order_id"],
            "intent_hash": intent["intent_hash"],
            "ticket_fingerprint": ticket["ticket_fingerprint"],
            "shadow_status": "NEW",
        }
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {**result, "reason": str(exc)[:120]}


def synthetic_demo() -> str:
    now = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    signals = {
        "updated_at": now.isoformat(),
        "prepared": [{"code": "285A", "name": "合成サンプル（実銘柄ではない）",
                      "action": "LONG", "strategy_key": "SYNTHETIC_OR15",
                      "signal_date": "2026-01-05", "trigger": 2000.0,
                      "stop": 1995.0, "data_freshness_sec": 0}],
    }
    calibration = {"groups": {"SYNTHETIC_OR15": {
        "risk_gate": "PASS", "risk_reason": "OK", "ev_score": 70.0,
        "sample_size": 120, "profit_factor": 1.5, "avg_pl_pct": 0.2,
    }}}
    proof = {"kind": "MS2_RSS_WORKBOOK",
             "source_authenticated": True,
             "machine_use_permitted": True,
             "rights_reference": "SYNTHETIC_FIXTURE_ONLY",
             "observed_at": now.isoformat(),
             "available_at": now.isoformat()}
    ticket, pending = create_paper_review(
        signals, calibration, proof, now=now, quantity=100)
    decision = simulate_owner_decision(
        pending, "APPROVE", decided_at=(now + timedelta(seconds=1)).isoformat())
    checked = evaluate_shadow_handoff(
        ticket, pending, decision, now=now + timedelta(seconds=2),
        quote_price=2000.0,
        quote_asof=(now + timedelta(seconds=1)).isoformat(),
        consumed_ids=set())
    if checked["state"] != "SIMULATED_SHADOW_READY" or checked["real_submit_allowed"] is not False:
        raise RuntimeError(checked["reason"])
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
        "allowed_qty": 100, "symbol": ticket["symbol"],
        "side": ticket["side"], "policy_version": "risk-gate-0.1.0",
        "horizon": "day",
    }
    fresh_at = (now + timedelta(seconds=1)).isoformat()
    snapshot = {
        "simulation_only": True,
        "kill_switch": {
            "status": "ARMED", "armed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=3600)).isoformat(),
        },
        "human_session_authorized": True,
        "authorization_issued_at": now.isoformat(),
        "authorization_expires_at": (now + timedelta(seconds=3600)).isoformat(),
        "authorization_session_id": "SYNTHETIC_NOT_AUTHENTICATED",
        "data_freshness": "OK", "market_session_allowed": True,
        "symbol_tradeable": True, "broker_link_health": "OK",
        "conflict_state": "CANDIDATE_READY",
        "expected_position_qty": 0, "broker_position_qty": 0,
        "buying_power_check": True, "short_availability_check": True,
        "realized_pnl_today_yen": 0.0, "open_positions_count": 0,
        "known_intents": [], "pending_orders": [],
        "price_tick_valid": True, "qty_lot_valid": True,
        "quote_price": 2000.0, "quote_asof": fresh_at,
        "broker_snapshot_fingerprint": "SYNTHETIC_NOT_BROKER",
    }
    shadow_result = dispatch_synthetic_shadow_order(
        ticket, pending, decision, now=now + timedelta(seconds=2),
        quote_price=2000.0, quote_asof=fresh_at,
        risk_decision=risk, simulated_broker_snapshot=snapshot,
        execution_policy=policy, known_shadow_orders=[])
    if shadow_result["state"] != "SIMULATED_SHADOW_ORDER_NEW" or shadow_result["real_submit_allowed"] is not False:
        raise RuntimeError(shadow_result["reason"])
    return "PASS: SYNTHETIC_OWNER_TO_SHADOW_CORE_NO_REAL_ORDER"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-demo", action="store_true")
    args = parser.parse_args()
    if not args.synthetic_demo:
        parser.error("This module is synthetic-only; use --synthetic-demo")
    print(synthetic_demo())
