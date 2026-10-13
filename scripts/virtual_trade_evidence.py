"""Point-in-time evidence for newly generated virtual trades.

``morning_review.py`` writes ``paper_trade_history.json``. A current row has
no evidence lane, no trade id, display-only timestamps, uppercase excursion
labels, and placeholder fees/slippage of 0. PR #337 reads that history and
leaves it BLOCKED. This module does not rewrite those 263 rows and does not
alias missing fields into the ledger contract.

New virtual trades enter through ``ingest`` / ``ingest_cohort``. A row is
saved only after SOURCE → VALIDATED → MEASURED. Incomplete, future-looking,
duplicate, unverified-cost, or inconsistent rows stop at SOURCE → BLOCKED.
A record that reaches the ledger and is still rejected stops at
SOURCE → VALIDATED → BLOCKED. Nothing is filled in to make it pass.

The handoff is ``paper_history_expectancy_adapter.connect`` (PR #337) into
``strategy_expectancy_ledger.measure`` (PR #336). ``promotion_eligible`` and
``real_submit_allowed`` stay false. This module does not submit orders.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CONTRACT = "virtual-trade-evidence-1"
TOKYO = ZoneInfo("Asia/Tokyo")
LEGACY_HISTORY_NAME = "paper_trade_history.json"
DEFAULT_LEGACY = Path(__file__).resolve().parents[1] / LEGACY_HISTORY_NAME

LANES_VIRTUAL = "VIRTUAL_SIGNAL"
ROLES_VIRTUAL = frozenset({"TRAIN", "TEST", "SHADOW"})
SIDES = frozenset({"LONG", "SHORT"})
SAFETY_FLAGS = ("real_submit_allowed", "promotion_eligible", "statistical_edge_confirmed")
PRIVATE_KEYS = frozenset({
    "account_number",
    "password",
    "api_key",
    "secret",
    "rss_order",
    "RssOrder",
    "broker_password",
})
REFUSED_ALIASES = ("signal_time", "MFE", "MAE", "ticker", "date", "strategy_key")
BASIS_REJECTED = frozenset({"", "unknown", "placeholder", "assumed", "unverified", "none"})

# Same named JP session clocks as strategy_expectancy_ledger._BUCKETS.
SESSION_BUCKETS = (
    ("OPEN_0900", 9 * 60, 9 * 60 + 15),
    ("AM_0915", 9 * 60 + 15, 9 * 60 + 30),
    ("AM_0930", 9 * 60 + 30, 10 * 60),
    ("AM_1000", 10 * 60, 10 * 60 + 30),
    ("AM_1030", 10 * 60 + 30, 11 * 60),
    ("AM_1100", 11 * 60, 11 * 60 + 30),
    ("OPEN_1230", 12 * 60 + 30, 13 * 60),
    ("PM_1300", 13 * 60, 14 * 60),
    ("PM_1400", 14 * 60, 14 * 60 + 30),
    ("PM_1430", 14 * 60 + 30, 15 * 60),
    ("CLOSE_1500", 15 * 60, 15 * 60 + 30),
)

SIGNAL_FIELDS = (
    "evidence_lane",
    "strategy_id",
    "strategy_version",
    "sample_role",
    "trade_id",
    "symbol",
    "side",
    "signal_known_at",
    "window_start",
    "window_end",
    "universe_fixed_before_outcome",
    "source",
)
EXIT_FIELDS = (
    "exit_known_at",
    "pnl_yen",
    "fees",
    "slippage",
    "cost_model_status",
    "mfe",
    "mae",
)

REQUIRED = (
    "evidence_lane",
    "strategy_id",
    "strategy_version",
    "sample_role",
    "sample_role_basis",
    "trade_id",
    "symbol",
    "side",
    "signal_known_at",
    "entry_time",
    "exit_known_at",
    "sequence_time",
    "window_start",
    "window_end",
    "universe_fixed_before_outcome",
    "universe_fixed_at",
    "pnl_yen",
    "fees",
    "slippage",
    "cost_model_status",
    "cost_basis",
    "mfe",
    "mae",
    "mfe_mae_units",
    "mfe_mae_timeframe",
    "source",
    "inputs",
    "field_observed_at",
)

# source, observed_at rule, and confirmation condition for every saved item.
FIELD_CONTRACT = (
    {"field": "evidence_lane", "source": "observation.evidence_lane", "observed_at": "field_observed_at.evidence_lane <= signal_known_at", "confirmed_when": "exactly VIRTUAL_SIGNAL"},
    {"field": "strategy_id", "source": "observation.strategy_id", "observed_at": "field_observed_at.strategy_id <= signal_known_at", "confirmed_when": "non-empty string, agreeing with strategy_key when both exist"},
    {"field": "strategy_version", "source": "observation.strategy_version", "observed_at": "field_observed_at.strategy_version <= signal_known_at", "confirmed_when": "non-empty string other than unknown"},
    {"field": "sample_role", "source": "observation.sample_role plus sample_role_basis", "observed_at": "field_observed_at.sample_role <= signal_known_at", "confirmed_when": "TRAIN, TEST, or SHADOW for VIRTUAL_SIGNAL"},
    {"field": "trade_id", "source": "observation.trade_id", "observed_at": "field_observed_at.trade_id <= signal_known_at", "confirmed_when": "unique non-empty string"},
    {"field": "symbol", "source": "observation.symbol", "observed_at": "field_observed_at.symbol <= signal_known_at", "confirmed_when": "non-empty string, agreeing with ticker when both exist"},
    {"field": "side", "source": "observation.side", "observed_at": "field_observed_at.side <= signal_known_at", "confirmed_when": "LONG or SHORT"},
    {"field": "signal_known_at", "source": "observation.signal_known_at", "observed_at": "field_observed_at.signal_known_at <= signal_known_at", "confirmed_when": "timezone-aware instant at or after universe_fixed_at"},
    {"field": "entry_time", "source": "observation.entry_time", "observed_at": "field_observed_at.entry_time <= entry_time", "confirmed_when": "timezone-aware instant at or after signal_known_at; session clock is Asia/Tokyo"},
    {"field": "exit_known_at", "source": "observation.exit_known_at", "observed_at": "entry_time <= field_observed_at.exit_known_at <= exit_known_at", "confirmed_when": "timezone-aware instant at or after entry_time"},
    {"field": "sequence_time", "source": "observation.sequence_time", "observed_at": "exit_known_at <= field_observed_at.sequence_time <= sequence_time", "confirmed_when": "timezone-aware instant at or after exit_known_at and inside the precommitted window"},
    {"field": "window_start", "source": "observation.window_start", "observed_at": "field_observed_at.window_start <= signal_known_at", "confirmed_when": "timezone-aware instant strictly before window_end, known by signal time"},
    {"field": "window_end", "source": "observation.window_end", "observed_at": "field_observed_at.window_end <= signal_known_at", "confirmed_when": "timezone-aware instant strictly after window_start, known by signal time"},
    {"field": "universe_fixed_before_outcome", "source": "observation.universe_fixed_before_outcome and universe_fixed_at", "observed_at": "field_observed_at.universe_fixed_before_outcome <= signal_known_at", "confirmed_when": "True and universe_fixed_at <= signal_known_at < exit_known_at"},
    {"field": "pnl_yen", "source": "observation.pnl_yen", "observed_at": "entry_time <= field_observed_at.pnl_yen <= exit_known_at", "confirmed_when": "finite number observed at or before exit_known_at"},
    {"field": "fees", "source": "observation.fees and cost_basis.fees_source", "observed_at": "entry_time <= field_observed_at.fees <= exit_known_at", "confirmed_when": "finite number >= 0 with a non-placeholder basis; unverified 0 is not a measurement"},
    {"field": "slippage", "source": "observation.slippage and cost_basis.slippage_source", "observed_at": "entry_time <= field_observed_at.slippage <= exit_known_at", "confirmed_when": "finite number >= 0 with a non-placeholder basis; unverified 0 is not a measurement"},
    {"field": "cost_model_status", "source": "observation.cost_model_status", "observed_at": "entry_time <= field_observed_at.cost_model_status <= exit_known_at", "confirmed_when": "VERIFIED only when both cost basis sources are present"},
    {"field": "mfe", "source": "observation.mfe", "observed_at": "entry_time <= field_observed_at.mfe <= exit_known_at", "confirmed_when": "finite number with mfe_mae_units and mfe_mae_timeframe; uppercase MFE is not copied"},
    {"field": "mae", "source": "observation.mae", "observed_at": "entry_time <= field_observed_at.mae <= exit_known_at", "confirmed_when": "finite number with mfe_mae_units and mfe_mae_timeframe; uppercase MAE is not copied"},
    {"field": "source", "source": "observation.source", "observed_at": "field_observed_at.source <= signal_known_at", "confirmed_when": "non-empty producer name"},
    {"field": "provenance", "source": "FIELD_CONTRACT plus field_observed_at and the original caller values", "observed_at": "per-field observed_at above", "confirmed_when": "every saved field has source, observed_at, and confirmed_when"},
)

REASON_PRIORITY = (
    "RECORDS_NOT_A_LIST",
    "RECORD_NOT_AN_OBJECT",
    "PRIVATE_DATA_REJECTED",
    "SAFETY_FLAG_REJECTED",
    "KNOWN_IDS_INVALID",
    "LANE_NOT_VIRTUAL",
    "EVIDENCE_LANE_INVALID",
    "MIXED_EVIDENCE_LANES",
    "MIXED_STRATEGY_IDS",
    "MIXED_STRATEGY_VERSIONS",
    "MIXED_SAMPLE_ROLES",
    "SAMPLE_ROLE_INVALID",
    "LANE_ROLE_MISMATCH",
    "STRATEGY_ID_INVALID",
    "STRATEGY_ID_DISAGREEMENT",
    "STRATEGY_VERSION_INVALID",
    "STRATEGY_VERSION_UNKNOWN",
    "SYMBOL_INVALID",
    "SYMBOL_DISAGREEMENT",
    "SIDE_INVALID",
    "TRADE_ID_INVALID",
    "DUPLICATE_TRADE_ID",
    "UNOBSERVED",
    "INPUTS_UNDECLARED",
    "INPUT_INVALID",
    "FIELD_OBSERVED_AT_INVALID",
    "TIMESTAMP_NAIVE",
    "TIMESTAMP_INVALID",
    "LOOKAHEAD",
    "ENTRY_BEFORE_SIGNAL",
    "SEQUENCE_BEFORE_EXIT",
    "UNIVERSE_AFTER_SIGNAL",
    "UNIVERSE_AFTER_OUTCOME",
    "SURVIVORSHIP_UNDECLARED",
    "WINDOW_INVALID",
    "WINDOW_VIOLATION",
    "COST_UNVERIFIED",
    "COST_BASIS_ABSENT",
    "FEES_ABSENT",
    "SLIPPAGE_ABSENT",
    "FEES_UNVERIFIED_ZERO",
    "SLIPPAGE_UNVERIFIED_ZERO",
    "COST_NEGATIVE",
    "INCOMPLETE_COST_OR_PNL",
    "EXCURSION_NOT_POINT_IN_TIME",
    "EXCURSION_UNITS_ABSENT",
    "EVIDENCE_MISMATCH",
    "DUPLICATE_FILL",
    "EVALUATION_WINDOW_UNDECLARED",
    "LEDGER_REJECTED",
    "REFUSED_LEGACY_WRITE",
    "LEGACY_UNREADABLE",
    "LEGACY_MUTATED",
    "JOURNAL_UNREADABLE",
    "CORRUPT_JSON",
    "EMPTY_INPUT",
    "SOURCE_MUTATED",
)


def _load_adapter():
    name = "paper_history_expectancy_adapter"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).with_name("paper_history_expectancy_adapter.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_ADAPTER = _load_adapter()


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return value


def _order(reasons):
    rank = {name: index for index, name in enumerate(REASON_PRIORITY)}
    return sorted(set(reasons), key=lambda item: (rank.get(item, len(REASON_PRIORITY)), item))


def _parse_aware(value):
    """Return a timezone-aware datetime, or (None, reason)."""
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        return None, "TIMESTAMP_INVALID"
    text = value
    if " " in text or text.endswith("JST"):
        return None, "TIMESTAMP_INVALID"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, "TIMESTAMP_INVALID"
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None, "TIMESTAMP_NAIVE"
    return parsed, None


def _tokyo_iso(parsed):
    tokyo = parsed.astimezone(TOKYO).replace(microsecond=0)
    return tokyo.isoformat(timespec="seconds")


def tokyo_session_bucket(value):
    """Classify a timezone-aware timestamp on the Asia/Tokyo clock."""
    parsed, reason = _parse_aware(value)
    if reason:
        return None
    tokyo = parsed.astimezone(TOKYO)
    minutes = tokyo.hour * 60 + tokyo.minute
    for name, start, end in SESSION_BUCKETS:
        if start <= minutes < end:
            return name
    return "OUT_OF_NAMED_SESSION"


def _text(value):
    return isinstance(value, str) and bool(value) and value.strip() == value


def _basis_ok(value):
    return _text(value) and value.strip().lower() not in BASIS_REJECTED


def _sha256(blob):
    return hashlib.sha256(blob).hexdigest()


def _fingerprint(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _safety():
    return {
        "statistical_edge_confirmed": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
        "blended": False,
        "legacy_rewritten": False,
        "source_mutated": False,
    }


def _envelope(*, state, transition, reason, reasons, missing, evidence_records, submitted_records,
              metrics, integrity, included_n, excluded_n, expectancy_demonstrated, handoff,
              rows, separated):
    accepted = state == "MEASURED"
    keep_records = state in {"MEASURED", "VALIDATED"} and evidence_records
    out = {
        "contract": CONTRACT,
        "state": state,
        "transition": list(transition),
        "reason": reason,
        "reasons": list(reasons),
        "missing": list(missing),
        "accepted": accepted,
        "evidence": evidence_records[0] if accepted and evidence_records and len(evidence_records) == 1 else None,
        "evidence_records": list(evidence_records) if keep_records else None,
        "submitted_records": submitted_records,
        "metrics": metrics if state in {"MEASURED", "EMPTY"} else None,
        "integrity": list(integrity),
        "included_n": included_n,
        "excluded_n": excluded_n,
        "expectancy_demonstrated": bool(expectancy_demonstrated) if accepted else False,
        "handoff_status": None if handoff is None else handoff.get("status"),
        "handoff_reason": None if handoff is None else handoff.get("reason"),
        "rows": rows,
        "separated": separated,
    }
    out.update(_safety())
    if state == "BLOCKED":
        out["expectancy_demonstrated"] = False
        out["metrics"] = None
        out["evidence"] = None
        out["evidence_records"] = None
        out["accepted"] = False
    return out


def _blocked(reasons, *, missing=(), transition=("SOURCE", "BLOCKED")):
    ordered = _order(reasons)
    return _envelope(
        state="BLOCKED",
        transition=transition,
        reason=ordered[0],
        reasons=ordered,
        missing=missing,
        evidence_records=None,
        submitted_records=None,
        metrics=None,
        integrity=[],
        included_n=0,
        excluded_n=0,
        expectancy_demonstrated=False,
        handoff=None,
        rows=None,
        separated=None,
    )


def _provenance(field, original, observed_at):
    spec = next(item for item in FIELD_CONTRACT if item["field"] == field)
    return {
        "source": spec["source"],
        "observed_at": observed_at,
        "confirmed_when": spec["confirmed_when"],
        "original": original,
    }


def _validate(observation, known_trade_ids):
    if not isinstance(observation, dict):
        return ["RECORD_NOT_AN_OBJECT"], [], None
    reasons = []
    missing = []
    if any(key in observation for key in PRIVATE_KEYS):
        return ["PRIVATE_DATA_REJECTED"], [], None
    for flag in SAFETY_FLAGS:
        if flag in observation and observation[flag] is not False:
            reasons.append("SAFETY_FLAG_REJECTED")
    if "MFE" in observation or "MAE" in observation:
        reasons.append("EXCURSION_NOT_POINT_IN_TIME")

    for key in REQUIRED:
        if key not in observation or observation[key] is None:
            missing.append(key)
    if missing:
        reasons.append("UNOBSERVED")
    if "inputs" not in observation:
        reasons.append("INPUTS_UNDECLARED")

    lane = observation.get("evidence_lane")
    if "evidence_lane" in observation and observation.get("evidence_lane") is not None:
        if lane == "REAL_FILL":
            reasons.append("LANE_NOT_VIRTUAL")
        elif lane != LANES_VIRTUAL:
            reasons.append("EVIDENCE_LANE_INVALID")

    role = observation.get("sample_role")
    if "sample_role" in observation and role is not None:
        if not _text(role) or role not in ROLES_VIRTUAL | {"REAL"}:
            reasons.append("SAMPLE_ROLE_INVALID")
        elif lane == LANES_VIRTUAL and role not in ROLES_VIRTUAL:
            reasons.append("LANE_ROLE_MISMATCH")

    strategy_id = observation.get("strategy_id")
    if "strategy_id" in observation and not _text(strategy_id):
        reasons.append("STRATEGY_ID_INVALID")
    strategy_key = observation.get("strategy_key")
    if _text(strategy_id) and _text(strategy_key) and strategy_id != strategy_key:
        reasons.append("STRATEGY_ID_DISAGREEMENT")

    version = observation.get("strategy_version")
    if "strategy_version" in observation and version is not None:
        if not _text(version):
            reasons.append("STRATEGY_VERSION_INVALID")
        elif version == "unknown":
            reasons.append("STRATEGY_VERSION_UNKNOWN")

    symbol = observation.get("symbol")
    if "symbol" in observation and not _text(symbol):
        reasons.append("SYMBOL_INVALID")
    ticker = observation.get("ticker")
    if _text(symbol) and _text(ticker) and symbol != ticker:
        reasons.append("SYMBOL_DISAGREEMENT")

    if "side" in observation and observation.get("side") not in SIDES:
        reasons.append("SIDE_INVALID")

    trade_id = observation.get("trade_id")
    if "trade_id" in observation and not _text(trade_id):
        reasons.append("TRADE_ID_INVALID")
    elif _text(trade_id) and trade_id in known_trade_ids:
        reasons.append("DUPLICATE_TRADE_ID")

    if "sample_role_basis" in observation and not _text(observation.get("sample_role_basis")):
        reasons.append("UNOBSERVED")
        missing.append("sample_role_basis")
    if "source" in observation and not _text(observation.get("source")):
        reasons.append("UNOBSERVED")
        missing.append("source")
    if "mfe_mae_units" in observation and not _text(observation.get("mfe_mae_units")):
        reasons.append("EXCURSION_UNITS_ABSENT")
    if "mfe_mae_timeframe" in observation and not _text(observation.get("mfe_mae_timeframe")):
        reasons.append("EXCURSION_UNITS_ABSENT")
    if observation.get("universe_fixed_before_outcome") is False:
        reasons.append("SURVIVORSHIP_UNDECLARED")
    elif (
        "universe_fixed_before_outcome" in observation
        and observation.get("universe_fixed_before_outcome") is not True
        and observation.get("universe_fixed_before_outcome") is not None
    ):
        reasons.append("SURVIVORSHIP_UNDECLARED")

    times = {}
    naive = False
    invalid_time = False
    for key in (
        "signal_known_at", "entry_time", "exit_known_at", "sequence_time",
        "window_start", "window_end", "universe_fixed_at",
    ):
        if key not in observation or observation[key] is None:
            continue
        parsed, reason = _parse_aware(observation[key])
        if reason == "TIMESTAMP_NAIVE":
            naive = True
        elif reason:
            invalid_time = True
        else:
            times[key] = parsed
    if naive:
        reasons.append("TIMESTAMP_NAIVE")
    if invalid_time:
        reasons.append("TIMESTAMP_INVALID")

    observed = observation.get("field_observed_at")
    observed_times = {}
    if "field_observed_at" in observation and observed is not None:
        if not isinstance(observed, dict):
            reasons.append("FIELD_OBSERVED_AT_INVALID")
        else:
            for key in list(SIGNAL_FIELDS) + ["entry_time", "sequence_time"] + list(EXIT_FIELDS):
                if key not in observed:
                    missing.append("field_observed_at." + key)
                    reasons.append("UNOBSERVED")
                    continue
                parsed, reason = _parse_aware(observed[key])
                if reason == "TIMESTAMP_NAIVE":
                    reasons.append("TIMESTAMP_NAIVE")
                elif reason:
                    reasons.append("TIMESTAMP_INVALID")
                else:
                    observed_times[key] = parsed

    inputs = observation.get("inputs")
    normalized_inputs = []
    if "inputs" in observation and inputs is not None:
        if not isinstance(inputs, list):
            reasons.append("INPUT_INVALID")
        else:
            signal = times.get("signal_known_at")
            for item in inputs:
                if not isinstance(item, dict) or not _text(item.get("name")):
                    reasons.append("INPUT_INVALID")
                    continue
                parsed, reason = _parse_aware(item.get("observed_at"))
                if reason:
                    reasons.append(reason)
                    continue
                if signal is not None and parsed > signal:
                    reasons.append("LOOKAHEAD")
                normalized_inputs.append({
                    "name": item["name"],
                    "observed_at": _tokyo_iso(parsed),
                    "original_observed_at": item.get("observed_at"),
                })

    signal = times.get("signal_known_at")
    entry = times.get("entry_time")
    exit_at = times.get("exit_known_at")
    sequence = times.get("sequence_time")
    window_start = times.get("window_start")
    window_end = times.get("window_end")
    universe_at = times.get("universe_fixed_at")
    if signal and entry and entry < signal:
        reasons.append("ENTRY_BEFORE_SIGNAL")
    if signal and exit_at and exit_at < signal:
        reasons.append("LOOKAHEAD")
    if entry and exit_at and exit_at < entry:
        reasons.append("LOOKAHEAD")
    if exit_at and sequence and sequence < exit_at:
        reasons.append("SEQUENCE_BEFORE_EXIT")
    if universe_at and signal and universe_at > signal:
        reasons.append("UNIVERSE_AFTER_SIGNAL")
    if universe_at and exit_at and universe_at >= exit_at:
        reasons.append("UNIVERSE_AFTER_OUTCOME")
    if window_start and window_end and not (window_start < window_end):
        reasons.append("WINDOW_INVALID")
    if window_start and window_end and sequence and not (window_start <= sequence <= window_end):
        reasons.append("WINDOW_VIOLATION")
    if window_start and signal and signal < window_start:
        reasons.append("WINDOW_VIOLATION")
    if window_end and exit_at and exit_at > window_end:
        reasons.append("WINDOW_VIOLATION")

    if signal and observed_times:
        for key in SIGNAL_FIELDS:
            seen = observed_times.get(key)
            if seen is not None and seen > signal:
                reasons.append("LOOKAHEAD")
        entry_seen = observed_times.get("entry_time")
        if entry is not None and entry_seen is not None and entry_seen > entry:
            reasons.append("LOOKAHEAD")
        for key in EXIT_FIELDS:
            seen = observed_times.get(key)
            if seen is None or entry is None or exit_at is None:
                continue
            if seen < entry or seen > exit_at:
                reasons.append("LOOKAHEAD")
        sequence_seen = observed_times.get("sequence_time")
        if sequence_seen is not None and exit_at is not None and sequence is not None:
            if sequence_seen < exit_at or sequence_seen > sequence:
                reasons.append("LOOKAHEAD")

    fees = observation.get("fees") if "fees" in observation else None
    slippage = observation.get("slippage") if "slippage" in observation else None
    status = observation.get("cost_model_status") if "cost_model_status" in observation else None
    verified = status == "VERIFIED"
    if "cost_model_status" in observation and status is not None and not verified:
        reasons.append("COST_UNVERIFIED")
    for key, absent, zero_name in (
        ("fees", "FEES_ABSENT", "FEES_UNVERIFIED_ZERO"),
        ("slippage", "SLIPPAGE_ABSENT", "SLIPPAGE_UNVERIFIED_ZERO"),
    ):
        if key not in observation or observation[key] is None:
            if key not in missing:
                reasons.append(absent)
            continue
        number = _num(observation[key])
        if number is None:
            reasons.append("INCOMPLETE_COST_OR_PNL")
        elif number < 0:
            reasons.append("COST_NEGATIVE")
        elif number == 0 and not verified:
            reasons.append(zero_name)
        elif not verified:
            reasons.append("COST_UNVERIFIED")
    if "pnl_yen" in observation and observation.get("pnl_yen") is not None and _num(observation.get("pnl_yen")) is None:
        reasons.append("INCOMPLETE_COST_OR_PNL")
    for key in ("mfe", "mae"):
        if key in observation and observation.get(key) is not None and _num(observation.get(key)) is None:
            reasons.append("INCOMPLETE_COST_OR_PNL")

    basis = observation.get("cost_basis")
    fees_source = slippage_source = None
    if verified:
        if not isinstance(basis, dict):
            reasons.append("COST_BASIS_ABSENT")
        else:
            fees_source = basis.get("fees_source")
            slippage_source = basis.get("slippage_source")
            if not _basis_ok(fees_source) or not _basis_ok(slippage_source):
                reasons.append("COST_BASIS_ABSENT")
    elif "cost_basis" in observation and basis is not None and not isinstance(basis, dict):
        reasons.append("COST_BASIS_ABSENT")

    ordered = _order(reasons)
    if ordered:
        return ordered, sorted(set(missing)), None

    canonical_times = {key: _tokyo_iso(value) for key, value in times.items()}
    provenance = {}
    for field in (
        "evidence_lane", "strategy_id", "strategy_version", "sample_role", "trade_id",
        "symbol", "side", "signal_known_at", "entry_time", "exit_known_at",
        "sequence_time", "window_start", "window_end", "universe_fixed_before_outcome",
        "pnl_yen", "fees", "slippage", "cost_model_status", "mfe", "mae", "source",
    ):
        original = observation[field]
        if field in times:
            original = observation[field]
        observed_at = _tokyo_iso(observed_times[field])
        provenance[field] = _provenance(field, original, observed_at)
    provenance["sample_role"]["basis"] = observation["sample_role_basis"]
    provenance["provenance"] = _provenance("provenance", None, canonical_times["signal_known_at"])

    evidence = {
        "contract": CONTRACT,
        "evidence_lane": lane,
        "strategy_id": strategy_id,
        "strategy_version": version,
        "sample_role": role,
        "sample_role_basis": observation["sample_role_basis"],
        "trade_id": trade_id,
        "symbol": symbol,
        "side": observation["side"],
        "signal_known_at": canonical_times["signal_known_at"],
        "entry_time": canonical_times["entry_time"],
        "exit_known_at": canonical_times["exit_known_at"],
        "sequence_time": canonical_times["sequence_time"],
        "window_start": canonical_times["window_start"],
        "window_end": canonical_times["window_end"],
        "universe_fixed_before_outcome": True,
        "universe_fixed_at": canonical_times["universe_fixed_at"],
        "pnl_yen": pnl_yen_value(observation["pnl_yen"]),
        "fees": pnl_yen_value(fees),
        "slippage": pnl_yen_value(slippage),
        "cost_model_status": "VERIFIED",
        "cost_basis": {
            "fees_source": fees_source,
            "slippage_source": slippage_source,
        },
        "mfe": pnl_yen_value(observation["mfe"]),
        "mae": pnl_yen_value(observation["mae"]),
        "mfe_mae_units": observation["mfe_mae_units"],
        "mfe_mae_timeframe": observation["mfe_mae_timeframe"],
        "source": observation["source"],
        "inputs": normalized_inputs,
        "session_bucket_tokyo": tokyo_session_bucket(canonical_times["entry_time"]),
        "provenance": provenance,
        "promotion_eligible": False,
        "real_submit_allowed": False,
        "statistical_edge_confirmed": False,
    }
    return [], [], evidence


def pnl_yen_value(value):
    number = _num(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return number


def validate_observation(observation, *, known_trade_ids=()):
    """Return SOURCE → VALIDATED, or SOURCE → BLOCKED. Does not measure."""
    known = _known(known_trade_ids)
    if not isinstance(known, set):
        return _blocked(["KNOWN_IDS_INVALID"])
    reasons, missing, evidence = _validate(observation, known)
    if reasons:
        return _blocked(reasons, missing=missing)
    return _envelope(
        state="VALIDATED",
        transition=("SOURCE", "VALIDATED"),
        reason=None,
        reasons=[],
        missing=[],
        evidence_records=[evidence],
        submitted_records=None,
        metrics=None,
        integrity=[],
        included_n=0,
        excluded_n=0,
        expectancy_demonstrated=False,
        handoff=None,
        rows=None,
        separated=None,
    )


def _known(known_trade_ids):
    if isinstance(known_trade_ids, str) or not isinstance(known_trade_ids, (set, list, tuple)):
        return None
    known = set()
    for item in known_trade_ids:
        if not isinstance(item, str) or not item:
            return None
        known.add(item)
    return known


def measure_validated_cohort(evidence_records):
    """Ledger handoff for records that already passed validation.

    Does not add fees, timestamps, or ids. A ledger rejection is
    SOURCE → VALIDATED → BLOCKED.
    """
    if not isinstance(evidence_records, list):
        return _blocked(["RECORDS_NOT_A_LIST"])
    if any(not isinstance(record, dict) for record in evidence_records):
        return _blocked(["RECORD_NOT_AN_OBJECT"])
    if not evidence_records:
        empty = _ADAPTER.connect([])
        return _envelope(
            state="EMPTY",
            transition=("SOURCE",),
            reason=None,
            reasons=[],
            missing=[],
            evidence_records=None,
            submitted_records=[],
            metrics=empty.get("metrics"),
            integrity=empty.get("integrity") or [],
            included_n=0,
            excluded_n=0,
            expectancy_demonstrated=False,
            handoff=empty,
            rows=[],
            separated=None,
        )
    before = _fingerprint(evidence_records)
    handoff = _ADAPTER.connect(evidence_records)
    mutated = _fingerprint(evidence_records) != before
    submitted = json.loads(before)
    if mutated or handoff.get("source_mutated"):
        blocked = _blocked(["SOURCE_MUTATED"], transition=("SOURCE", "VALIDATED", "BLOCKED"))
        blocked["submitted_records"] = submitted
        blocked["source_mutated"] = True
        return blocked
    accepted = (
        handoff.get("status") == "MEASURED"
        and handoff.get("included_n") == len(evidence_records)
        and handoff.get("excluded_n") == 0
    )
    reason = None if accepted else (handoff.get("reason") or "LEDGER_REJECTED")
    transition = ("SOURCE", "VALIDATED", "MEASURED") if accepted else ("SOURCE", "VALIDATED", "BLOCKED")
    envelope = _envelope(
        state="MEASURED" if accepted else "BLOCKED",
        transition=transition,
        reason=reason,
        reasons=[] if accepted else _order([reason]),
        missing=[],
        evidence_records=evidence_records if accepted else None,
        submitted_records=submitted,
        metrics=handoff.get("metrics"),
        integrity=handoff.get("integrity") or [],
        included_n=handoff.get("included_n") or 0,
        excluded_n=handoff.get("excluded_n") or 0,
        expectancy_demonstrated=bool(handoff.get("expectancy_demonstrated")),
        handoff=handoff,
        rows=None,
        separated=None,
    )
    if not accepted:
        envelope["metrics"] = None
        envelope["expectancy_demonstrated"] = False
        envelope["evidence_records"] = None
        envelope["evidence"] = None
        envelope["accepted"] = False
    return envelope


def ingest(observation, *, known_trade_ids=()):
    """Record one new virtual trade. Does not mutate ``observation``."""
    known = _known(known_trade_ids)
    if not isinstance(known, set):
        return _blocked(["KNOWN_IDS_INVALID"])
    before = _fingerprint(observation)
    validated = validate_observation(observation, known_trade_ids=known)
    if _fingerprint(observation) != before:
        blocked = _blocked(["SOURCE_MUTATED"])
        blocked["source_mutated"] = True
        return blocked
    if validated["state"] != "VALIDATED":
        return validated
    return measure_validated_cohort(validated["evidence_records"])


def _group_key(observation):
    if not isinstance(observation, dict):
        return None
    return (
        observation.get("evidence_lane"),
        observation.get("strategy_id"),
        observation.get("strategy_version"),
        observation.get("sample_role"),
    )


def _mix_reason(observations):
    lanes = set()
    strategies = set()
    versions = set()
    roles = set()
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        lanes.add(observation.get("evidence_lane"))
        strategies.add(observation.get("strategy_id"))
        versions.add(observation.get("strategy_version"))
        roles.add(observation.get("sample_role"))
    if "REAL_FILL" in lanes and LANES_VIRTUAL in lanes:
        return "MIXED_EVIDENCE_LANES"
    if len({item for item in strategies if item is not None}) > 1:
        return "MIXED_STRATEGY_IDS"
    if len({item for item in versions if item is not None}) > 1:
        return "MIXED_STRATEGY_VERSIONS"
    if len({item for item in roles if item is not None}) > 1:
        return "MIXED_SAMPLE_ROLES"
    return None


def ingest_cohort(observations, *, known_trade_ids=()):
    """Validate a batch and measure it only when it is one pure cohort.

    REAL and VIRTUAL are not blended. TRAIN, TEST, and SHADOW are not blended.
    A failed row is not dropped so the rest can pass.
    """
    if not isinstance(observations, list):
        return _blocked(["RECORDS_NOT_A_LIST"])
    known = _known(known_trade_ids)
    if not isinstance(known, set):
        return _blocked(["KNOWN_IDS_INVALID"])
    if not observations:
        blocked = _blocked(["EMPTY_INPUT"])
        return blocked

    before = _fingerprint(observations)
    counts = {}
    for observation in observations:
        if isinstance(observation, dict) and _text(observation.get("trade_id")):
            trade_id = observation["trade_id"]
            counts[trade_id] = counts.get(trade_id, 0) + 1
    duplicate_ids = {trade_id for trade_id, count in counts.items() if count > 1 or trade_id in known}

    rows = []
    groups = {}
    for observation in observations:
        if not isinstance(observation, dict):
            row = _blocked(["RECORD_NOT_AN_OBJECT"])
        elif _text(observation.get("trade_id")) and observation["trade_id"] in duplicate_ids:
            row = _blocked(["DUPLICATE_TRADE_ID"])
        else:
            row = validate_observation(observation, known_trade_ids=known)
        rows.append(row)
        key = _group_key(observation)
        groups.setdefault(key, []).append(row)

    if _fingerprint(observations) != before:
        blocked = _blocked(["SOURCE_MUTATED"])
        blocked["source_mutated"] = True
        return blocked

    mix = _mix_reason(observations)
    blocked_rows = [row for row in rows if row["state"] != "VALIDATED"]
    if mix is None and not blocked_rows:
        measured = measure_validated_cohort([row["evidence_records"][0] for row in rows])
        measured["rows"] = rows
        return measured

    separated = {}
    if mix is not None:
        for key, grouped in groups.items():
            if key is None or any(row["state"] != "VALIDATED" for row in grouped):
                continue
            if key[0] != LANES_VIRTUAL:
                continue
            label = key[3] if mix == "MIXED_SAMPLE_ROLES" else key[0]
            if mix == "MIXED_STRATEGY_IDS":
                label = key[1]
            elif mix == "MIXED_STRATEGY_VERSIONS":
                label = key[2]
            separated[str(label)] = measure_validated_cohort(
                [row["evidence_records"][0] for row in grouped]
            )
    reason = mix or blocked_rows[0]["reason"]
    reasons = [reason]
    for row in blocked_rows:
        reasons.extend(row["reasons"])
    envelope = _blocked(_order(reasons))
    envelope["reason"] = reason
    envelope["rows"] = rows
    envelope["separated"] = separated or None
    envelope["submitted_records"] = None
    return envelope


def from_morning_review_row(row):
    """Project a morning-review row without aliasing missing evidence.

    ``signal_time``, uppercase ``MFE``/``MAE``, ``ticker``, and placeholder
    costs are not rewritten into ledger fields.
    """
    if not isinstance(row, dict):
        blocked = _blocked(["RECORD_NOT_AN_OBJECT"])
        blocked["aliased"] = False
        blocked["refused_aliases"] = []
        return blocked
    observation = {}
    for key in REQUIRED:
        if key in row:
            observation[key] = row[key]
    if "strategy_key" in row and "strategy_id" in row:
        observation["strategy_key"] = row["strategy_key"]
    if "ticker" in row and "symbol" in row:
        observation["ticker"] = row["ticker"]
    result = ingest(observation)
    result["aliased"] = False
    result["refused_aliases"] = [name for name in REFUSED_ALIASES if name in row]
    return result


def load_journal(path):
    """Read an evidence journal. Corrupt input is BLOCKED and never repaired."""
    path = Path(path)
    try:
        blob = path.read_bytes()
    except OSError:
        blocked = _blocked(["JOURNAL_UNREADABLE"])
        blocked["records"] = None
        return blocked
    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        blocked = _blocked(["CORRUPT_JSON"])
        blocked["records"] = None
        return blocked
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        blocked = _blocked(["CORRUPT_JSON"])
        blocked["records"] = None
        return blocked
    if not isinstance(data, list):
        blocked = _blocked(["RECORDS_NOT_A_LIST"])
        blocked["records"] = None
        return blocked
    if any(not isinstance(row, dict) for row in data):
        blocked = _blocked(["RECORD_NOT_AN_OBJECT"])
        blocked["records"] = None
        return blocked
    envelope = _envelope(
        state="EMPTY" if not data else "READY",
        transition=("SOURCE",),
        reason=None,
        reasons=[],
        missing=[],
        evidence_records=None,
        submitted_records=None,
        metrics=None,
        integrity=[],
        included_n=len(data),
        excluded_n=0,
        expectancy_demonstrated=False,
        handoff=None,
        rows=None,
        separated=None,
    )
    envelope["records"] = data
    envelope["accepted"] = False
    return envelope


def append_measured(journal_path, observations, *, legacy_path=DEFAULT_LEGACY):
    """Append only a fully MEASURED cohort. Never writes the legacy history."""
    journal = Path(journal_path)
    legacy = Path(legacy_path)
    try:
        same_file = journal.resolve() == legacy.resolve()
    except OSError:
        same_file = False
    if same_file or journal.name == LEGACY_HISTORY_NAME:
        blocked = _blocked(["REFUSED_LEGACY_WRITE"])
        blocked["journal_written"] = False
        if legacy.is_file():
            blob = legacy.read_bytes()
            blocked["legacy_sha256"] = _sha256(blob)
            blocked["legacy_bytes_unchanged"] = True
        return blocked
    if not legacy.is_file():
        blocked = _blocked(["LEGACY_UNREADABLE"])
        blocked["journal_written"] = False
        return blocked
    legacy_before = legacy.read_bytes()
    journal_before = journal.read_bytes() if journal.exists() else None
    existing = []
    if journal.exists():
        loaded = load_journal(journal)
        if loaded["state"] == "BLOCKED":
            loaded["journal_written"] = False
            loaded["legacy_bytes_unchanged"] = legacy.read_bytes() == legacy_before
            loaded["legacy_sha256"] = _sha256(legacy_before)
            return loaded
        existing = loaded["records"]
    known = [row.get("trade_id") for row in existing if isinstance(row, dict) and isinstance(row.get("trade_id"), str)]
    result = ingest_cohort(observations, known_trade_ids=known)
    result["legacy_sha256"] = _sha256(legacy_before)
    if result["state"] != "MEASURED":
        result["journal_written"] = False
        result["legacy_bytes_unchanged"] = legacy.read_bytes() == legacy_before
        if journal_before is None:
            result["journal_unchanged"] = not journal.exists()
        else:
            result["journal_unchanged"] = journal.exists() and journal.read_bytes() == journal_before
        return result
    payload = existing + result["evidence_records"]
    if not journal.parent.is_dir():
        blocked = _blocked(["JOURNAL_UNREADABLE"])
        blocked["journal_written"] = False
        blocked["legacy_bytes_unchanged"] = legacy.read_bytes() == legacy_before
        return blocked
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    journal.write_text(text, encoding="utf-8")
    legacy_after = legacy.read_bytes()
    result["journal_written"] = True
    result["legacy_bytes_unchanged"] = legacy_after == legacy_before
    result["legacy_rewritten"] = legacy_after != legacy_before
    if legacy_after != legacy_before:
        result["state"] = "BLOCKED"
        result["reason"] = "LEGACY_MUTATED"
        result["accepted"] = False
        result["expectancy_demonstrated"] = False
    return result


def audit_legacy_history(path=DEFAULT_LEGACY):
    """Read the legacy history through the adapter. Does not write it."""
    path = Path(path)
    try:
        before = path.read_bytes()
    except OSError:
        return _blocked(["LEGACY_UNREADABLE"])
    try:
        records = json.loads(before.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        blocked = _blocked(["CORRUPT_JSON"])
        blocked["bytes_unchanged"] = path.read_bytes() == before
        return blocked
    count = len(records) if isinstance(records, list) else None
    handoff = _ADAPTER.connect_file(path)
    after = path.read_bytes()
    return {
        "contract": CONTRACT,
        "count": count,
        "sha256_before": _sha256(before),
        "sha256_after": _sha256(after),
        "bytes_unchanged": before == after,
        "legacy_rewritten": before != after,
        "status": handoff.get("status"),
        "reason": handoff.get("reason"),
        "included_n": handoff.get("included_n"),
        "excluded_n": handoff.get("excluded_n"),
        "expectancy_demonstrated": handoff.get("expectancy_demonstrated"),
        "statistical_edge_confirmed": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
        "metrics": handoff.get("metrics"),
    }
