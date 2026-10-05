"""Control view that keeps a Brain candidate apart from a Shadow fill.

Brain does not decide the live entry. A fixed strategy still owns the virtual
order. This module does not submit, does not edit entry signals, and does not
invent a price, an EV, or a candidate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ai_brain_research as brain
import shadow_trade_ledger as trade_ledger

NOT_AVAILABLE = "NOT AVAILABLE"
INSUFFICIENT_SAMPLE = "INSUFFICIENT SAMPLE"
AUTHORITY = "RESEARCH ONLY / NOT EXECUTION AUTHORITY"
BRAIN_BADGE = "RESEARCH / CANDIDATE"
SHADOW_BANNER = "SHADOW / NO REAL ORDER"
FORBIDDEN_LABEL = "BRAIN ENTRY"

_SIDES = {"LONG", "SHORT", "NO-TRADE"}
_PHASES = ("brain_discovered", "entry_candidate", "shadow_entry", "shadow_exit", "result")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _text(value) -> str:
    if isinstance(value, str) and value.strip() and FORBIDDEN_LABEL not in value:
        return value.strip()
    return NOT_AVAILABLE


def _clock(value) -> str:
    if isinstance(value, str) and "T" in value and FORBIDDEN_LABEL not in value:
        return value
    return NOT_AVAILABLE


def _yen(value, *, signed=False, per_share=False) -> str:
    number = _number(value)
    if number is None:
        return NOT_AVAILABLE
    rendered = f"{number:,.0f}" if float(number) == int(number) else f"{number:,.2f}"
    if signed and number > 0:
        rendered = "+" + rendered
    suffix = "円/株" if per_share else "円"
    return rendered + suffix


def _brain_side(side) -> str:
    if side == "LONG":
        return "LONG CANDIDATE"
    if side == "SHORT":
        return "SHORT CANDIDATE"
    if side == "NO-TRADE":
        return "NO-TRADE"
    return NOT_AVAILABLE


def _research_line() -> str:
    summary = brain.research_lane_fetch_summary()
    return "FETCHED " + str(summary["fetched"]) + "/" + str(summary["registry"]) + " / trading_adoption=false"


def _sample_line(status: dict) -> str:
    count = status.get("BASELINE_N")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        return INSUFFICIENT_SAMPLE
    by_side = status.get("baseline_by_side")
    if not isinstance(by_side, dict):
        return NOT_AVAILABLE
    parts = []
    for side in ("LONG", "SHORT"):
        metrics = by_side.get(side)
        if not isinstance(metrics, dict) or not isinstance(metrics.get("n"), int) or metrics["n"] <= 0:
            continue
        ev = metrics.get("net_ev")
        pf = metrics.get("profit_factor")
        if _number(ev) is None or _number(pf) is None:
            continue
        parts.append(side + " EV " + str(ev) + " / PF " + str(pf) + " / N " + str(metrics["n"]))
    if not parts:
        return NOT_AVAILABLE
    return " / ".join(parts)


def _accuracy(status: dict) -> str:
    count = status.get("BASELINE_N")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        return INSUFFICIENT_SAMPLE
    return NOT_AVAILABLE


def _accept_candidate(raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("execution_authority") is True:
        return None
    if raw.get("real_submit_allowed") is True:
        return None
    side = raw.get("side")
    symbol = raw.get("symbol")
    candidate_id = raw.get("candidate_id")
    if side not in _SIDES or not isinstance(symbol, str) or not symbol:
        return None
    if not isinstance(candidate_id, str) or not candidate_id or FORBIDDEN_LABEL in candidate_id:
        return None
    price = _yen(raw.get("price")) if raw.get("price_fresh") is True else NOT_AVAILABLE
    return {
        "candidate_id": candidate_id,
        "symbol": symbol,
        "side": _brain_side(side),
        "discovered_at": _clock(raw.get("discovered_at")),
        "entry_candidate_at": _clock(raw.get("entry_candidate_at")),
        "entry_trigger": _text(raw.get("entry_trigger")),
        "price": price,
        "reason": _text(raw.get("reason")),
        "candidate_generator": _text(raw.get("candidate_generator")),
        "correlation": _text(raw.get("correlation")),
        "lead_lag": _text(raw.get("lead_lag")),
        "market_regime": _text(raw.get("market_regime")),
    }


def _latest_candidate(candidates) -> dict | None:
    accepted = [row for row in (_accept_candidate(item) for item in candidates or []) if row]
    if not accepted:
        return None
    dated = [row for row in accepted if row["discovered_at"] != NOT_AVAILABLE]
    pool = dated or accepted
    return max(pool, key=lambda row: row["discovered_at"] if row["discovered_at"] != NOT_AVAILABLE else "")


def _live_open(positions) -> dict | None:
    rows = []
    for item in positions or []:
        if not isinstance(item, dict):
            continue
        if item.get("acceptance_class") == "synthetic" or item.get("source_stage") == trade_ledger.SOURCE_SYNTHETIC:
            continue
        if item.get("event_type") not in {None, "virtual_entry"}:
            continue
        if item.get("real_submit_allowed") is True or item.get("quantity") is not None:
            continue
        ticker = item.get("ticker") or item.get("symbol")
        side = item.get("side")
        if not isinstance(ticker, str) or not ticker or side not in {"LONG", "SHORT"}:
            continue
        entry_at = _clock(item.get("at") or item.get("entry_fill_at"))
        marked = _clock(item.get("marked_at"))
        state = "IN POSITION" if marked != NOT_AVAILABLE and entry_at != NOT_AVAILABLE and marked > entry_at else "ENTRY"
        fill = _yen(item.get("fill_price") if item.get("fill_price") is not None else item.get("entry_price"))
        pnl = NOT_AVAILABLE
        if item.get("mark_fresh") is True:
            mark = _number(item.get("mark_price"))
            entry = _number(item.get("fill_price") if item.get("fill_price") is not None else item.get("entry_price"))
            if mark is not None and entry is not None:
                pnl = _yen(mark - entry if side == "LONG" else entry - mark, signed=True, per_share=True)
        rows.append({
            "state": state,
            "symbol": ticker,
            "side": side,
            "entry_at": entry_at,
            "fill": fill,
            "strategy": _text(item.get("strategy") or item.get("model_id")),
            "exit_at": NOT_AVAILABLE,
            "pnl": pnl,
            "trade_id": _text(item.get("trade_id")) if isinstance(item.get("trade_id"), str) else NOT_AVAILABLE,
            "candidate_id": item.get("candidate_id") if isinstance(item.get("candidate_id"), str) and item.get("candidate_id") else NOT_AVAILABLE,
        })
    if not rows:
        return None
    return max(rows, key=lambda row: row["entry_at"] if row["entry_at"] != NOT_AVAILABLE else "")


def _display_exit(record) -> dict | None:
    """Show a virtual exit even when the fee is still unknown.

    Research N stays on the ledger gate. A synthetic or stale row never
    becomes the live Shadow card.
    """
    if not isinstance(record, dict):
        return None
    if record.get("source_stage") != trade_ledger.SOURCE_LIVE or record.get("data_quality") != "OK":
        return None
    if record.get("real_submit_allowed") is not False or record.get("acceptance_class") == "synthetic":
        return None
    symbol = record.get("symbol")
    side = record.get("side")
    trade_id = record.get("trade_id")
    if not isinstance(symbol, str) or not symbol or side not in {"LONG", "SHORT"}:
        return None
    if trade_id != symbol + "|" + side + "|" + str(record.get("entry_seq")):
        return None
    if _number(record.get("entry_price")) is None or _clock(record.get("entry_fill_at")) == NOT_AVAILABLE:
        return None
    return {
        "state": "EXIT",
        "symbol": symbol,
        "side": side,
        "entry_at": _clock(record.get("entry_fill_at")),
        "fill": _yen(record.get("entry_price")),
        "strategy": _text(record.get("strategy") or record.get("model_id")),
        "exit_at": _clock(record.get("exit_fill_at")),
        "pnl": _yen(record.get("gross_pnl"), signed=True, per_share=True),
        "trade_id": trade_id,
        "candidate_id": record.get("candidate_id") if isinstance(record.get("candidate_id"), str) and record.get("candidate_id") else NOT_AVAILABLE,
    }


def _live_exit(trades) -> dict | None:
    live = [row for row in (_display_exit(record) for record in trades or []) if row]
    if not live:
        return None
    return max(live, key=lambda row: row["exit_at"] if row["exit_at"] != NOT_AVAILABLE else "")


def _empty_shadow() -> dict:
    return {
        "state": "WAITING",
        "symbol": NOT_AVAILABLE,
        "side": NOT_AVAILABLE,
        "entry_at": NOT_AVAILABLE,
        "fill": NOT_AVAILABLE,
        "strategy": NOT_AVAILABLE,
        "exit_at": NOT_AVAILABLE,
        "pnl": NOT_AVAILABLE,
        "trade_id": NOT_AVAILABLE,
        "candidate_id": NOT_AVAILABLE,
        "banner": SHADOW_BANNER,
        "real_submit_allowed": False,
    }


def _phases(candidate: dict | None, shadow: dict) -> list:
    discovered = candidate["discovered_at"] if candidate else NOT_AVAILABLE
    proposed = candidate["entry_candidate_at"] if candidate else NOT_AVAILABLE
    entered = shadow["entry_at"] if shadow["state"] in {"ENTRY", "IN POSITION", "EXIT"} else NOT_AVAILABLE
    exited = shadow["exit_at"] if shadow["state"] == "EXIT" else NOT_AVAILABLE
    result = shadow["pnl"] if shadow["state"] == "EXIT" else NOT_AVAILABLE
    values = {
        "brain_discovered": discovered,
        "entry_candidate": proposed,
        "shadow_entry": entered,
        "shadow_exit": exited,
        "result": result,
    }
    return [{"phase": name, "at": values[name]} for name in _PHASES]


def _same_link(candidate: dict | None, shadow: dict) -> bool:
    if not candidate or shadow["candidate_id"] == NOT_AVAILABLE:
        return False
    return candidate["candidate_id"] == shadow["candidate_id"]


def _timeline(candidate, shadow, linked: bool) -> list:
    """Join the clocks only when the candidate id is the same.

    An unrelated Brain row and Shadow fill stay on their own cards.
    """
    both = candidate is not None and shadow["state"] != "WAITING"
    if both and not linked:
        return _phases(None, _empty_shadow())
    if candidate is not None and shadow["state"] == "WAITING":
        return _phases(candidate, _empty_shadow())
    if candidate is None:
        return _phases(None, shadow)
    return _phases(candidate, shadow)


def live_view(candidates=None, shadow_trades=None, open_positions=None, research_status=None) -> dict:
    """One Brain card, one Shadow card, and the ids that can join them later."""
    status = research_status if isinstance(research_status, dict) else brain.evaluate_shadow_trade_ledger(shadow_trades or [])
    status["real_submit_allowed"] = False
    candidate = _latest_candidate(candidates)
    shadow = _live_open(open_positions) or _live_exit(shadow_trades) or _empty_shadow()
    shadow["banner"] = SHADOW_BANNER
    shadow["real_submit_allowed"] = False
    linked = _same_link(candidate, shadow)
    accuracy = _accuracy(status)
    brain_card = {
        "title": "AI BRAIN LIVE",
        "badge": BRAIN_BADGE,
        "authority": AUTHORITY,
        "execution_authority": False,
        "symbol": candidate["symbol"] if candidate else NOT_AVAILABLE,
        "side": candidate["side"] if candidate else NOT_AVAILABLE,
        "discovered_at": candidate["discovered_at"] if candidate else NOT_AVAILABLE,
        "entry_candidate_at": candidate["entry_candidate_at"] if candidate else NOT_AVAILABLE,
        "entry_trigger": candidate["entry_trigger"] if candidate else NOT_AVAILABLE,
        "price": candidate["price"] if candidate else NOT_AVAILABLE,
        "reason": candidate["reason"] if candidate else NOT_AVAILABLE,
        "candidate_generator": candidate["candidate_generator"] if candidate else NOT_AVAILABLE,
        "correlation": candidate["correlation"] if candidate else NOT_AVAILABLE,
        "lead_lag": candidate["lead_lag"] if candidate else NOT_AVAILABLE,
        "market_regime": candidate["market_regime"] if candidate else NOT_AVAILABLE,
        "research_status": _research_line(),
        "ev_pf_n": _sample_line(status),
        "candidate_id": candidate["candidate_id"] if candidate else NOT_AVAILABLE,
        "real_submit_allowed": False,
    }
    return {
        "brain": brain_card,
        "shadow": shadow,
        "timeline": _timeline(candidate, shadow, linked),
        "link": {
            "candidate_id": brain_card["candidate_id"],
            "shadow_candidate_id": shadow["candidate_id"],
            "trade_id": shadow["trade_id"],
            "linked": linked,
        },
        "accuracy": {
            "selection": accuracy,
            "entry_timing": accuracy,
            "exit": accuracy,
        },
        "real_submit_allowed": False,
        "live_signal_changed": False,
    }


def publish_live_view(root: Path, candidates=None, shadow_trades=None, open_positions=None) -> dict:
    payload = live_view(candidates, shadow_trades, open_positions)
    path = root / "brain_shadow_live.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
