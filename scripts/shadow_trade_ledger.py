"""Shadow trade ledger. Recording only.

The supervisor writes one row when a virtual exit already happened. This
module does not decide entries, does not send orders, and does not invent a
commission. Rakuten MarketSpeed II RSS is the quote source. RssOrder is not
implemented. strategy_schema and the collector hold snapshot name 0 yen and
10 bps only as placeholders for a missing model. Those numbers are not a
broker tariff, so commission stays FEE_UNKNOWN until a confirmed schedule
exists.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import research_cost_model as cost_model

FEE_UNKNOWN = "FEE_UNKNOWN"
SOURCE_LIVE = "LIVE_SHADOW"
SOURCE_SYNTHETIC = "SYNTHETIC/REPLAY"
SYNTHETIC_FIXTURE_BASIS = "SYNTHETIC_FIXTURE_NOT_A_BROKER_TARIFF"
CONFIRMED_LIVE_FEE_BASES = frozenset()
BASELINE_MODEL = "BASELINE"

LEDGER_FIELDS = (
    "trade_id",
    "symbol",
    "strategy",
    "model_id",
    "decision_at",
    "available_at",
    "entry_signal_at",
    "entry_order_at",
    "entry_fill_at",
    "entry_price",
    "entry_slippage",
    "exit_signal_at",
    "exit_fill_at",
    "exit_price",
    "exit_slippage",
    "quantity",
    "gross_pnl",
    "commission",
    "other_cost",
    "net_pnl",
    "mae",
    "mfe",
    "regime",
    "data_quality",
    "source_stage",
)

FEE_AUDIT = {
    "broker": "Rakuten MarketSpeed II RSS",
    "order_method": "RssOrder is unimplemented. Shadow uses collector quote simulation and does not send an order.",
    "confirmed_commission_schedule": False,
    "rejected_placeholders": (
        "strategy_schema fixes fees at 0 because no fee model exists",
        "collector overnight hold labels fee_bps=0 and round_trip cost_bps=10 as assumptions",
        "private_ledger fee is a hand-entered real fill and is not a shadow tariff",
    ),
    "recorded_commission": FEE_UNKNOWN,
    "real_submit_allowed": False,
}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def _clock(value):
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _text(value) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def build_shadow_trade(entry: dict, exit_event: dict, *, exit_signal_at, source_stage: str, data_quality: str, entry_bid=None, entry_ask=None, exit_bid=None, exit_ask=None) -> dict:
    """Copy clocks and fills that already exist. Commission stays unknown."""
    symbol = exit_event.get("ticker") if isinstance(exit_event.get("ticker"), str) else ""
    side = exit_event.get("side") if exit_event.get("side") in {"LONG", "SHORT"} else ""
    entry_seq = entry.get("seq")
    signal_at = _text(entry.get("source_timestamp"))
    costs = cost_model.cost_components(
        entry_bid=entry.get("bid") if entry_bid is None else entry_bid,
        entry_ask=entry.get("ask") if entry_ask is None else entry_ask,
        exit_bid=exit_bid,
        exit_ask=exit_ask,
        entry_slippage=exit_event.get("entry_slippage_yen"),
        exit_slippage=exit_event.get("exit_slippage_yen"),
    )
    record = {
        "record_class": "shadow_trade",
        "trade_id": symbol + "|" + side + "|" + str(entry_seq),
        "symbol": symbol,
        "side": side,
        "strategy": exit_event.get("strategy") if isinstance(exit_event.get("strategy"), str) else "",
        "model_id": BASELINE_MODEL,
        "decision_at": entry.get("at"),
        "available_at": signal_at,
        "entry_signal_at": signal_at,
        "entry_order_at": None,
        "entry_fill_at": entry.get("at"),
        "entry_price": exit_event.get("fill_entry_price"),
        "entry_slippage": exit_event.get("entry_slippage_yen"),
        "exit_signal_at": _text(exit_signal_at),
        "exit_fill_at": exit_event.get("at"),
        "exit_price": exit_event.get("fill_exit_price"),
        "exit_slippage": exit_event.get("exit_slippage_yen"),
        "quantity": None,
        "gross_pnl": exit_event.get("fill_pnl_per_share_yen"),
        "commission": FEE_UNKNOWN,
        "other_cost": FEE_UNKNOWN,
        "net_pnl": FEE_UNKNOWN,
        "mae": exit_event.get("mae_yen"),
        "mfe": exit_event.get("mfe_yen"),
        "regime": "UNKNOWN",
        "data_quality": data_quality,
        "source_stage": source_stage,
        "entry_seq": entry_seq,
        "order_status": "NOT_SENT",
        "fill_model": "collector_quote_simulation",
        "fee_basis": "UNCONFIRMED",
        "fee_audit": "NO_CONFIRMED_BROKER_TARIFF",
        "broker": FEE_AUDIT["broker"],
        "order_method": FEE_AUDIT["order_method"],
        "unit": "yen_per_share",
        "entry_spread": costs["entry_spread"],
        "exit_spread": costs["exit_spread"],
        "spread_status": costs["spread_status"],
        "cost_evidence_url": costs["evidence_url"],
        "cost_tariff_version": costs["tariff_version"],
        "cost_effective_from": costs["effective_from"],
        "cost_fetched_at": costs["fetched_at"],
        "cost_applied_to_shadow_net": False,
        "real_submit_allowed": False,
    }
    candidate_id = entry.get("candidate_id")
    if isinstance(candidate_id, str) and candidate_id:
        record["candidate_id"] = candidate_id
    record["quantity"] = None
    record["commission"] = FEE_UNKNOWN
    record["other_cost"] = FEE_UNKNOWN
    record["net_pnl"] = FEE_UNKNOWN
    record["real_submit_allowed"] = False
    record["cost_applied_to_shadow_net"] = False
    return record


def apply_synthetic_fixture_fee(record: dict, commission: float, other_cost: float = 0.0) -> dict:
    """Label a replay cost. This is not a broker tariff and cannot mark a live row."""
    if not isinstance(record, dict) or record.get("source_stage") != SOURCE_SYNTHETIC:
        raise ValueError("synthetic fixture fee is not a live tariff")
    gross = _number(record.get("gross_pnl"))
    fee = _number(commission)
    other = _number(other_cost)
    if gross is None or fee is None or other is None or fee < 0 or other < 0:
        raise ValueError("fixture cost is incomplete")
    updated = dict(record)
    updated["commission"] = fee
    updated["other_cost"] = other
    updated["net_pnl"] = gross - fee - other
    updated["fee_basis"] = SYNTHETIC_FIXTURE_BASIS
    updated["fee_audit"] = "NOT_A_BROKER_TARIFF"
    updated["real_submit_allowed"] = False
    updated["quantity"] = None
    return updated


def _identity_ok(record: dict) -> bool:
    symbol = record.get("symbol")
    side = record.get("side")
    trade_id = record.get("trade_id")
    if not isinstance(symbol, str) or not symbol or side not in {"LONG", "SHORT"}:
        return False
    if not isinstance(trade_id, str) or not trade_id:
        return False
    return trade_id == symbol + "|" + side + "|" + str(record.get("entry_seq"))


def _costs_match(record: dict) -> bool:
    gross = _number(record.get("gross_pnl"))
    commission = _number(record.get("commission"))
    other = _number(record.get("other_cost"))
    net = _number(record.get("net_pnl"))
    if gross is None or commission is None or other is None or net is None:
        return False
    if commission < 0 or other < 0:
        return False
    return abs(net - (gross - commission - other)) < 1e-9


def _fee_known(record: dict) -> bool:
    if not _costs_match(record):
        return False
    basis = record.get("fee_basis")
    source = record.get("source_stage")
    if source == SOURCE_SYNTHETIC:
        return basis == SYNTHETIC_FIXTURE_BASIS
    if source == SOURCE_LIVE:
        return isinstance(basis, str) and basis in CONFIRMED_LIVE_FEE_BASES
    return False


def classify_shadow_trade(record, seen: set) -> tuple[str, str]:
    """Return live, pipe, or excluded, plus a reason. Seen grows only on acceptance."""
    if not isinstance(record, dict) or record.get("record_class") != "shadow_trade":
        return "excluded", "INCOMPLETE"
    if record.get("source_stage") not in {SOURCE_LIVE, SOURCE_SYNTHETIC}:
        return "excluded", "INCOMPLETE"
    if record.get("real_submit_allowed") is not False or record.get("quantity") is not None:
        return "excluded", "INCOMPLETE"
    if not _identity_ok(record) or record.get("model_id") != BASELINE_MODEL:
        return "excluded", "IDENTITY_UNKNOWN"
    if record.get("data_quality") == "STALE" or record.get("stale") is True:
        return "excluded", "STALE_PRICE"
    if record.get("data_quality") != "OK":
        return "excluded", "INCOMPLETE"
    decision = _clock(record.get("decision_at"))
    entry_fill = _clock(record.get("entry_fill_at"))
    exit_fill = _clock(record.get("exit_fill_at"))
    if decision is None or entry_fill is None or exit_fill is None:
        return "excluded", "INCOMPLETE"
    if exit_fill < entry_fill or decision > entry_fill or decision > exit_fill:
        return "excluded", "TIMESTAMP_INCONSISTENT"
    available = _clock(record.get("available_at"))
    if available is not None and available > decision:
        return "excluded", "TIMESTAMP_INCONSISTENT"
    required = ("entry_price", "exit_price", "entry_slippage", "exit_slippage", "gross_pnl", "mae", "mfe")
    numbers = [_number(record.get(key)) for key in required]
    if any(value is None for value in numbers) or numbers[0] <= 0 or numbers[1] <= 0:
        return "excluded", "INCOMPLETE"
    if not _fee_known(record):
        return "excluded", "FEE_UNKNOWN"
    trade_id = record.get("trade_id")
    if trade_id in seen:
        return "excluded", "DUPLICATE"
    seen.add(trade_id)
    if record.get("source_stage") == SOURCE_SYNTHETIC:
        return "pipe", ""
    return "live", ""


def split_shadow_trades(records) -> dict:
    live = []
    pipe = []
    excluded = []
    seen: set = set()
    for record in records or []:
        destination, reason = classify_shadow_trade(record, seen)
        if destination == "live":
            live.append(record)
            continue
        if destination == "pipe":
            pipe.append(record)
            continue
        excluded.append({
            "trade_id": None if not isinstance(record, dict) else record.get("trade_id"),
            "reason": reason,
            "source_stage": None if not isinstance(record, dict) else record.get("source_stage"),
            "counts_as_live_sample": False,
        })
    return {"live": live, "pipe": pipe, "excluded": excluded}


def read_shadow_trades(path: Path) -> tuple[list, str]:
    if not path.exists():
        return [], ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], "LEDGER_UNREADABLE"
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return [], "LEDGER_CORRUPT"
        if not isinstance(item, dict):
            return [], "LEDGER_CORRUPT"
        rows.append(item)
    return rows, ""


def append_shadow_trade(data_dir: Path, record: dict) -> bool:
    """Append one trade. A second copy of the same trade_id is not written."""
    path = data_dir / "shadow_trades.jsonl"
    existing, error = read_shadow_trades(path)
    if error:
        return False
    if record.get("trade_id") in {row.get("trade_id") for row in existing}:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def publish_shadow_research(data_dir: Path) -> dict:
    """Score the ledger. An empty or unknown-fee ledger does not invent an EV."""
    try:
        import ai_brain_research as brain
        records, error = read_shadow_trades(data_dir / "shadow_trades.jsonl")
        if error:
            status = brain.evaluate_shadow_trade_ledger([])
            status["ledger_error"] = error
        else:
            status = brain.evaluate_shadow_trade_ledger(records)
    except Exception:
        status = {
            "CLEAN_SHADOW_TRADE_N": 0,
            "BASELINE_N": 0,
            "FEATURE_DELTA_EV": "NOT_AVAILABLE",
            "PROMOTION_CANDIDATE": "NONE",
            "ledger_error": "RESEARCH_STATUS_FAILED",
            "real_submit_allowed": False,
        }
    status["real_submit_allowed"] = False
    _write_status(data_dir / "shadow_research_status.json", status)
    return status
