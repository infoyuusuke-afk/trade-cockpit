"""Project immutable events into journal rows without modifying source events."""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

_FULL_CLOCK = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_ROW_KEYS = (
    "event_id",
    "timestamp",
    "symbol",
    "category",
    "event_type",
    "summary",
    "decision",
    "result",
    "lesson",
)


def journal_rows(events):
    out=[]
    for e in events:
        p=e.get("payload") or {}
        if e.get("domain") not in {"MARKET","STRATEGY","RISK","EXECUTION","JOURNAL","SYSTEM"}: continue
        out.append({"event_id":e["event_id"],"timestamp":e["timestamp"],"symbol":e.get("symbol"),"category":e["domain"],"event_type":e["event_type"],"summary":p.get("summary"),"decision":p.get("decision"),"result":p.get("result"),"lesson":p.get("lesson")})
    return sorted(out,key=lambda x:(x["timestamp"],x["event_id"]))


def _full_clock(value):
    if isinstance(value, str) and _FULL_CLOCK.match(value):
        return value
    return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def shadow_trade_journal_rows(trades):
    """Copy a shadow trade into a journal row. Do not price an unknown fee.

    SYNTHETIC/REPLAY is labeled so the row cannot count as live experience.
    Source dicts are left unchanged. A row that is not explicitly
    real_submit_allowed false is skipped. Confirmed live fee bases stay empty
    until a tariff exists, so result stays null in production.
    """
    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import shadow_trade_ledger as trade_ledger

    out = []
    seen = set()
    for trade in trades or []:
        if not isinstance(trade, dict) or trade.get("real_submit_allowed") is not False:
            continue
        trade_id = trade.get("trade_id")
        source = trade.get("source_stage")
        if not isinstance(trade_id, str) or not trade_id or not isinstance(source, str) or not source:
            continue
        timestamp = _full_clock(trade.get("exit_fill_at")) or _full_clock(trade.get("decision_at"))
        if timestamp is None:
            continue
        event_id = hashlib.sha256((trade_id + "\n" + source).encode("utf-8")).hexdigest()
        if event_id in seen:
            continue
        seen.add(event_id)
        side = trade.get("side") if trade.get("side") in {"LONG", "SHORT"} else None
        fee_basis = trade.get("fee_basis")
        fee_known = (
            source == trade_ledger.SOURCE_LIVE
            and isinstance(fee_basis, str)
            and fee_basis in trade_ledger.CONFIRMED_LIVE_FEE_BASES
            and _number(trade.get("commission")) is not None
            and _number(trade.get("net_pnl")) is not None
        )
        lesson = []
        if source == trade_ledger.SOURCE_SYNTHETIC:
            lesson.append("source_stage=SYNTHETIC/REPLAY")
            lesson.append("counts_as_live_experience=false")
        commission = trade.get("commission")
        net = trade.get("net_pnl")
        if not fee_known:
            lesson.append("net_pnl_not_recorded")
            if commission == trade_ledger.FEE_UNKNOWN or net == trade_ledger.FEE_UNKNOWN or _number(commission) is None or _number(net) is None:
                lesson.append("commission=FEE_UNKNOWN")
            else:
                lesson.append("fee_basis_unconfirmed")
        symbol = trade.get("symbol") if isinstance(trade.get("symbol"), str) else None
        row = {
            "event_id": event_id,
            "timestamp": timestamp,
            "symbol": symbol,
            "category": "JOURNAL",
            "event_type": "SHADOW_TRADE",
            "summary": "shadow " + (side or "UNSET") + " " + source + " real_submit_allowed=false",
            "decision": side,
            "result": format(_number(net), "g") if fee_known else None,
            "lesson": "; ".join(lesson) if lesson else None,
        }
        if tuple(row) != _ROW_KEYS:
            continue
        out.append(row)
    return sorted(out, key=lambda x: (x["timestamp"], x["event_id"]))
