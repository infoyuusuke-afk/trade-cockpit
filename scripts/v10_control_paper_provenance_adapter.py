"""Read-only V10 CONTROL adapter for independently observed PAPER roundtrips.

This is an inert, pure-function bridge to the existing Shadow EV evidence
contracts. It never reads/writes local files, publishes market/account data,
contacts brokers, modifies the UI, enables execution, or stamps missing times.
Only caller-provided timezone-aware availability evidence may authorize a row.

An eligible output is still a SIMULATED research trade, not broker P&L.
The caller remains responsible for independent readback and access-controlled
publication. DO NOT copy raw private evidence into the public repository.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
import math
import re

from scripts.shadow_ev_evidence_projection import project as project_observed
from scripts.export_ev_trades import review as review_ev

STRATEGY_TABS = frozenset((
    "scalp", "event-hot", "ms2-live", "overnight", "swing",
    "value", "kioxia-calendar",
))
_SAFE_SYMBOL = re.compile(r"^[0-9A-Z]{4}\.T$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_OFFSET_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

SCHEMA = "v10_control_paper_observed_v1"


def _date(value):
    """Reject naive, floating, ambiguous, malformed and unrealized timestamps."""
    if not isinstance(value, str) or not _OFFSET_TIMESTAMP.fullmatch(value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    return dt if dt.utcoffset() is not None else None


def _now(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        return None
    return value


def _safe_identifier(value):
    return type(value) is str and _SAFE_ID.fullmatch(value) is not None


def _rejected(reason):
    return None, reason


def project_control_row(intent, entry, exit_, cost, *, now):
    """Return (public-safe, UI-eligible PAPER row | None, reason | None).

    Strictly reuses the existing paper observed-fill and verified-cost
    validators. The further fields below are required because the EV source
    contract did not originally claim a UI tab, quote currency or available_at.
    This function never backfills or guesses these dimensions.
    """
    clock = _now(now)
    if clock is None:
        return _rejected("NOW_TIMEZONE_REQUIRED")
    if any(type(x) is not dict for x in (intent, entry, exit_, cost)):
        return _rejected("INVALID_EVIDENCE_TYPE")
    if any(x.get("real_submit_allowed") is True for x in (intent, entry, exit_, cost)):
        return _rejected("REAL_SUBMIT_EVIDENCE_REJECTED")

    tab = intent.get("cockpit_tab")
    if tab not in STRATEGY_TABS:
        return _rejected("STRATEGY_TAB_UNVERIFIED")
    if any(x.get("quote_currency") != "JPY" for x in (intent, entry, exit_)):
        return _rejected("JPY_QUOTE_PROVENANCE_MISSING")
    if cost.get("cost_basis") != "ENTRY_NOTIONAL_PCT":
        return _rejected("COST_BASIS_UNVERIFIED")
    if (not _safe_identifier(intent.get("intent_hash"))
            or not _SAFE_SYMBOL.fullmatch(str(intent.get("symbol", "")))):
        return _rejected("SYMBOL_OR_INTENT_IDENTITY_UNSAFE")

    paper, reason = project_observed(intent, entry, exit_, cost)
    if reason is not None:
        return _rejected("EVIDENCE_" + reason)
    ev, reason = review_ev(paper)
    if reason is not None:
        return _rejected("EV_" + reason)
    if ev["net_pnl_pct"] != ev["net_pnl_pct"]:  # preserve fail-closed even if upstream changes
        return _rejected("NET_EV_NOT_FINITE")

    intent_available = _date(intent.get("available_at"))
    entry_observed = _date(entry.get("observed_at"))
    entry_available = _date(entry.get("available_at"))
    exit_observed = _date(exit_.get("observed_at"))
    exit_available = _date(exit_.get("available_at"))
    cost_available = _date(cost.get("available_at"))
    times = (intent_available, entry_observed, entry_available,
             exit_observed, exit_available, cost_available)
    if any(x is None for x in times):
        return _rejected("AVAILABLE_AT_UNVERIFIED")
    if not (intent_available <= entry_observed <= entry_available
            <= exit_observed <= exit_available
            and exit_observed <= cost_available):
        return _rejected("POINT_IN_TIME_LEAKAGE_OR_ORDER")
    available_at = max(intent_available, entry_available,
                       exit_available, cost_available)
    if available_at > clock:
        return _rejected("FUTURE_SOURCE_EVIDENCE")
    if entry_observed >= exit_observed:
        return _rejected("INVALID_FILL_CHRONOLOGY")

    entry_px, exit_px = paper["entry_fill_price"], paper["exit_fill_price"]
    qty = entry["filled_qty"]
    if type(qty) not in (int, float) or not math.isfinite(qty) or qty <= 0:
        return _rejected("QUANTITY_INVALID")
    direction = 1 if paper["side"] == "LONG" else -1
    gross_yen = direction * (exit_px - entry_px) * qty
    expense_yen = entry_px * qty * paper["cost_pct"] / 100
    net_yen = gross_yen - expense_yen
    if not all(math.isfinite(v) for v in (gross_yen, expense_yen, net_yen)):
        return _rejected("NONFINITE_SIMULATED_PNL")
    if not (_safe_identifier(entry.get("fill_id"))
            and _safe_identifier(exit_.get("fill_id"))):
        return _rejected("FILL_IDENTIFIERS_UNSAFE")

    # Domain-separated deterministic digest: identities do not leave this pure
    # adapter; the hash is deduplication only, NOT authentication or readback.
    key = json.dumps(
        [SCHEMA, intent["intent_hash"], entry["fill_id"], exit_["fill_id"]],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    public_id = "paper-" + hashlib.sha256(key).hexdigest()
    return {
        "schema_version": SCHEMA,
        "trade_id": public_id,
        "strategy_id": paper["strategy_id"],
        "cockpit_tab": tab,
        "mode": "paper",
        "status": "CLOSED",
        "exit_reason": "OBSERVED_EXIT_FILL",
        "closed_at": exit_observed.isoformat(),
        "available_at": available_at.isoformat(),
        "pnl_yen": round(net_yen, 6),
        "pnl_basis": "SIMULATED_NET_JPY_VERIFIED_COST_PCT",
        "source": "PAPER_OBSERVED",
        "source_authenticated": False,
        "real_submit_allowed": False,
    }, None


def project_control_batch(events, *, now):
    """Return (eligible public-safe rows, anonymous aggregate-only audit).

    Duplicated intent hashes and trade IDs invalidate *all* occurrences,
    including bad members. Every input remains private in caller memory.
    No output/persistence is authorized by this function.
    """
    if _now(now) is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    if type(events) is not list:
        raise ValueError("EVENTS_LIST_REQUIRED")
    counts = Counter()
    for item in events:
        if type(item) is dict and type(item.get("intent")) is dict:
            intent_hash = item["intent"].get("intent_hash")
            if _safe_identifier(intent_hash):
                counts[intent_hash] += 1

    projected = []
    rejects = Counter()
    for item in events:
        if type(item) is not dict:
            rejects["INVALID_BATCH_ITEM"] += 1
            continue
        intent = item.get("intent")
        intent_hash = intent.get("intent_hash") if type(intent) is dict else None
        if _safe_identifier(intent_hash) and counts[intent_hash] != 1:
            rejects["DUPLICATE_INTENT"] += 1
            continue
        row, reason = project_control_row(
            item.get("intent"), item.get("entry"), item.get("exit"),
            item.get("cost"), now=now,
        )
        if reason:
            rejects[reason] += 1
        else:
            projected.append(row)
    ids = Counter(x["trade_id"] for x in projected)
    safe = sorted(
        (x for x in projected if ids[x["trade_id"]] == 1),
        key=lambda x: (x["closed_at"], x["trade_id"]),
    )
    if len(safe) < len(projected):
        rejects["DUPLICATE_TRADE_ID"] += len(projected) - len(safe)
    audit = {
        "schema_version": SCHEMA,
        "execution_lane": "PAPER_OBSERVED_ONLY",
        "records_examined": len(events),
        "eligible_records": len(safe),
        "quarantined_records": len(events) - len(safe),
        "exclusions": dict(sorted(rejects.items())),
        "real_submit_allowed": False,
        "source_authenticated": False,
        "private_evidence_published": False,
        "persistence_verified": False,
    }
    return safe, audit
