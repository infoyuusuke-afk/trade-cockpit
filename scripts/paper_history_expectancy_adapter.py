"""Read-only handoff from virtual-trade history to the expectancy ledger.

``morning_review.py`` remains the writer of ``paper_trade_history.json``.
This module only reads records and projects fields the ledger already
requires. It does not invent an evidence lane, strategy id, strategy
version, sample role, trade id, timestamp, window, or universe flag.
It does not treat a missing fee or slippage as zero.

Morning review stores ``fees`` and ``slippage`` as 0 because no cost model
is connected. Those placeholder zeros are withheld unless
``cost_model_status`` is exactly ``VERIFIED``. Uppercase ``MFE`` / ``MAE``
and ``signal_time`` display strings are not rewritten into ledger fields.

The handoff never writes the history, never changes a signal or a strategy
parameter, and never enables promotion or live submission.
``statistical_edge_confirmed`` stays false: meeting N=30 is only the
measurement contract, not evidence of an edge.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

CONTRACT = "paper-history-expectancy-adapter-1"
DEFAULT_HISTORY = Path(__file__).resolve().parents[1] / "paper_trade_history.json"

# Ledger integrity that means the cohort must not be published as measured.
# INSUFFICIENT_SAMPLE, NO_LOSING_TRADES, and SEQUENCE_NOT_MONOTONIC stay
# MEASURED with expectancy_demonstrated false: the sample was readable, and
# the missing claim is statistical or a single metric, not a broken record.
_HARD_INTEGRITY = frozenset({
    "INCOMPLETE_COST_OR_PNL",
    "LOOKAHEAD",
    "LOOKAHEAD_UNVERIFIED",
    "DUPLICATE_FILL",
    "MISSING_TRADE_ID",
    "SURVIVORSHIP_UNDECLARED",
    "EVALUATION_WINDOW_UNDECLARED",
    "SEQUENCE_UNVERIFIED",
    "WINDOW_VIOLATION",
    "MFE_INCOMPLETE",
    "MAE_INCOMPLETE",
    "SIDE_INCOMPLETE",
    "SYMBOL_INCOMPLETE",
    "TIME_BUCKET_INCOMPLETE",
})
_PASSTHROUGH = (
    "evidence_lane",
    "sample_role",
    "trade_id",
    "side",
    "signal_known_at",
    "entry_time",
    "exit_known_at",
    "pnl_yen",
    "mfe",
    "mae",
    "window_start",
    "window_end",
    "universe_fixed_before_outcome",
    "sequence_time",
)


def _load_ledger():
    name = "strategy_expectancy_ledger"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).with_name("strategy_expectancy_ledger.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_LEDGER = _load_ledger()


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _fingerprint(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _project(record):
    """Copy only values the source record already carries."""
    row = {}
    notes = []
    for key in _PASSTHROUGH:
        if key in record:
            row[key] = record[key]

    strategy_id = record.get("strategy_id") if "strategy_id" in record else None
    strategy_key = record.get("strategy_key") if "strategy_key" in record else None
    if (
        isinstance(strategy_id, str) and strategy_id.strip()
        and isinstance(strategy_key, str) and strategy_key.strip()
        and strategy_id != strategy_key
    ):
        notes.append("STRATEGY_ID_DISAGREEMENT")
    elif "strategy_id" in record:
        row["strategy_id"] = record["strategy_id"]

    if "strategy_version" in record:
        if record.get("strategy_version") == "unknown":
            notes.append("STRATEGY_VERSION_UNKNOWN")
        else:
            row["strategy_version"] = record["strategy_version"]

    has_symbol = "symbol" in record
    has_ticker = "ticker" in record
    symbol = record.get("symbol") if has_symbol else None
    ticker = record.get("ticker") if has_ticker else None
    if (
        isinstance(symbol, str) and symbol
        and isinstance(ticker, str) and ticker
        and symbol != ticker
    ):
        notes.append("SYMBOL_DISAGREEMENT")
    elif has_symbol:
        row["symbol"] = record["symbol"]
    elif has_ticker:
        row["symbol"] = record["ticker"]

    _copy_costs(record, row, notes)
    return row, sorted(set(notes))


def _copy_costs(record, row, notes):
    status_present = "cost_model_status" in record
    verified = record.get("cost_model_status") == "VERIFIED"
    if status_present and not verified:
        notes.append("COST_UNVERIFIED")
        return
    for key, absent_note, zero_note in (
        ("fees", "FEES_ABSENT", "FEES_UNVERIFIED_ZERO"),
        ("slippage", "SLIPPAGE_ABSENT", "SLIPPAGE_UNVERIFIED_ZERO"),
    ):
        if key not in record or record[key] is None:
            notes.append(absent_note)
            continue
        number = _num(record[key])
        if verified:
            row[key] = record[key]
            continue
        if number is None or number < 0:
            row[key] = record[key]
            continue
        if number == 0:
            notes.append(zero_note)
            continue
        row[key] = record[key]


def _shell(*, status, reason, records_examined, projected, notes, ledger):
    integrity = []
    included_n = 0
    excluded_n = 0
    if isinstance(ledger, dict):
        if isinstance(ledger.get("integrity"), list):
            integrity = list(ledger["integrity"])
        included_n = ledger.get("included_n") or 0
        excluded_n = ledger.get("excluded_n") or 0
    demonstrated = (
        status == "MEASURED"
        and isinstance(ledger, dict)
        and ledger.get("expectancy_demonstrated") is True
    )
    metrics = ledger.get("metrics") if status == "MEASURED" and isinstance(ledger, dict) else None
    withheld = sum(
        1 for note in notes
        if any(code.startswith("FEES_") or code.startswith("SLIPPAGE_") or code.startswith("COST_")
               for code in note["reasons"])
    )
    return {
        "contract": CONTRACT,
        "status": status,
        "reason": reason,
        "expectancy_demonstrated": demonstrated,
        "statistical_edge_confirmed": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
        "source_mutated": False,
        "records_examined": records_examined,
        "included_n": included_n,
        "excluded_n": excluded_n,
        "integrity": integrity,
        "metrics": metrics,
        "cost_zero_filled": False,
        "withheld_cost_rows": withheld,
        "projection_notes": notes,
        "projected": projected,
        "ledger": ledger,
    }


def connect(records):
    """Project ``records`` and measure one cohort. Does not mutate ``records``."""
    if not isinstance(records, list):
        return _shell(
            status="BLOCKED",
            reason="RECORDS_NOT_A_LIST",
            records_examined=0,
            projected=[],
            notes=[],
            ledger=None,
        )

    before = _fingerprint(records)
    projected = []
    notes = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            projected.append(record)
            notes.append({"index": index, "reasons": ["RECORD_NOT_AN_OBJECT"]})
            continue
        row, reasons = _project(record)
        projected.append(row)
        if reasons:
            notes.append({"index": index, "reasons": reasons})

    ledger = _LEDGER.measure(projected)
    status = ledger.get("status")
    reason = ledger.get("reason")
    if status == "MEASURED":
        hard = [code for code in ledger.get("integrity") or [] if code in _HARD_INTEGRITY]
        if hard:
            status = "BLOCKED"
            reason = hard[0]
        else:
            reason = None
    mutated = _fingerprint(records) != before
    result = _shell(
        status="BLOCKED" if mutated else status,
        reason="SOURCE_MUTATED" if mutated else reason,
        records_examined=len(records),
        projected=projected,
        notes=notes,
        ledger=ledger,
    )
    if mutated:
        result["source_mutated"] = True
        result["expectancy_demonstrated"] = False
        result["metrics"] = None
        result["promotion_eligible"] = False
        result["real_submit_allowed"] = False
        result["statistical_edge_confirmed"] = False
    return result


def connect_file(path=DEFAULT_HISTORY):
    """Read a history file and connect it. Never writes the file."""
    path = Path(path)
    blob = path.read_bytes()
    records = json.loads(blob.decode("utf-8-sig"))
    result = connect(records)
    result["source_sha256_before"] = _sha256(blob)
    result["source_unchanged"] = path.read_bytes() == blob
    result["source_bytes"] = len(blob)
    if not result["source_unchanged"]:
        result["status"] = "BLOCKED"
        result["reason"] = "SOURCE_MUTATED"
        result["source_mutated"] = True
        result["expectancy_demonstrated"] = False
        result["metrics"] = None
        result["promotion_eligible"] = False
        result["real_submit_allowed"] = False
        result["statistical_edge_confirmed"] = False
    return result


def _sha256(blob):
    return hashlib.sha256(blob).hexdigest()
