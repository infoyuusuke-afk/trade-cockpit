"""V10 Brain research audit of existing *virtual observations*, never fills.

Source: private V10 AI Shadow supervisor ledger.jsonl. Read-only. Outputs
strategy-level statistics in R units, not JPY profit or validated EV. Entries
are published-intent prices, not executable prices. This code has no trading,
network, external publication, scheduling or broker capabilities.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

SCHEMA = "v10-brain-virtual-outcome-audit-1"
SOURCE_SCHEMA = "ai-shadow-supervisor-1"
SOURCE_PRICING = "collector_published_price_not_fill_model"
_MAX_FILE_BYTES = 12_000_000
_MAX_EVENTS = 100_000
_MAX_EVENT_BYTES = 32_768
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
def _safe_strategy(value):
    return (type(value) is str and 1 <= len(value) <= 100 and
            value.strip() == value and all(c.isprintable() and c not in ("/", "\\") for c in value))
_SAFE_SYMBOL = re.compile(r"^[A-Z0-9]{4}(?:\.T)?$")


def _ts(value):
    if not isinstance(value, str) or not _ISO.fullmatch(value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.utcoffset() is not None else None


def _num(value):
    return type(value) in (int, float) and math.isfinite(value)


def _blocked(reason):
    """Return only anonymous status; never reveal private price/ticker/path."""
    return {"schema_version": SCHEMA, "state": "BLOCKED", "reason": reason,
            "data_lane": "VIRTUAL_OBSERVATION_NOT_FILL", "strategy_statistics": [],
            "tested_expectancy_available": False, "source_authenticated": False,
            "promotion_eligible": False, "real_submit_allowed": False}


def audit(events, *, now):
    """Fail-closed audit of a whole immutable V10 Shadow event sequence.

    Any invalid event quarantines the entire dataset. This deliberately does
    not use virtual outcomes as broker fill or net-of-cost trading evidence.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        return _blocked("DECISION_TIME_UNVERIFIED")
    if type(events) is not list or not 0 < len(events) <= _MAX_EVENTS:
        return _blocked("LEDGER_EMPTY_OR_INVALID")
    open_by_key = {}
    completed = []
    contaminated = 0
    previous_time = None
    for index, event in enumerate(events, 1):
        if type(event) is not dict:
            return _blocked("LEDGER_RECORD_INVALID")
        if (type(event.get("seq")) is not int or event["seq"] != index or
            event.get("schema_version") != SOURCE_SCHEMA or
            event.get("record_class") != "shadow_observation" or
            event.get("pricing") != SOURCE_PRICING or
            event.get("real_submit_allowed") is not False or
            "quantity" not in event or event["quantity"] is not None):
            return _blocked("LEDGER_LINEAGE_OR_ORDER_UNVERIFIED")
        at = _ts(event.get("at"))
        if at is None or at > now or (previous_time is not None and at < previous_time):
            return _blocked("EVENT_TIME_INVALID_OR_FUTURE")
        previous_time = at
        kind = event.get("event_type")
        if kind == "board_judgment":
            continue
        if kind not in ("virtual_entry", "virtual_exit"):
            return _blocked("EVENT_TYPE_INVALID")
        key = event.get("position_key")
        ticker = event.get("ticker")
        side = event.get("side")
        strategy = event.get("strategy")
        if (not isinstance(ticker, str) or not _SAFE_SYMBOL.fullmatch(ticker) or
            side not in ("LONG", "SHORT") or key != ticker + "|" + side or
            not _safe_strategy(strategy)):
            return _blocked("STRATEGY_OR_POSITION_IDENTITY_INVALID")
        if kind == "virtual_entry":
            if key in open_by_key:
                return _blocked("DUPLICATE_OPEN_POSITION")
            entry_px, stop_px = event.get("entry_price"), event.get("stop_price")
            quote_at = _ts(event.get("source_timestamp_at"))
            if (not _num(entry_px) or not _num(stop_px) or entry_px <= 0 or stop_px <= 0 or
                (stop_px >= entry_px if side == "LONG" else stop_px <= entry_px) or
                quote_at is None or not 0 <= (at - quote_at).total_seconds() <= 120 or
                event.get("performance_bucket") != "open_unrealized_not_marked"):
                return _blocked("ENTRY_PRICE_OR_SOURCE_TIME_UNVERIFIED")
            open_by_key[key] = event
            continue
        entry = open_by_key.pop(key, None)
        if entry is None or event.get("related_entry_seq") != entry["seq"]:
            return _blocked("UNMATCHED_EXIT")
        if strategy != entry["strategy"] or at <= _ts(entry["at"]):
            return _blocked("EXIT_STRATEGY_OR_TIME_DISAGREEMENT")
        exit_px = event.get("exit_price")
        entry_px = entry["entry_price"]
        stop_px = entry["stop_price"]
        if (not _num(exit_px) or exit_px <= 0 or
            not _num(event.get("entry_price")) or event["entry_price"] != entry_px):
            return _blocked("EXIT_PRICE_OR_ENTRY_LINEAGE_INVALID")
        signed_change = (exit_px - entry_px) * (1 if side == "LONG" else -1)
        computed_r = signed_change / abs(entry_px - stop_px)
        if not math.isfinite(signed_change) or not math.isfinite(computed_r):
            return _blocked("VIRTUAL_OUTCOME_NOT_FINITE")
        if (not _num(event.get("pnl_per_share_yen")) or
            not math.isclose(event["pnl_per_share_yen"], signed_change, abs_tol=1e-7) or
            not _num(event.get("r_multiple")) or
            not math.isclose(event["r_multiple"], computed_r, abs_tol=1e-7)):
            return _blocked("VIRTUAL_PNL_RECONCILIATION_FAILED")
        bucket = event.get("performance_bucket")
        if bucket == "contaminated_by_data_outage":
            contaminated += 1
        elif bucket == "clean_strategy":
            completed.append((strategy, computed_r))
        else:
            return _blocked("OUTCOME_QUALITY_UNKNOWN")

    by_strategy = defaultdict(list)
    for strategy, r in completed:
        by_strategy[strategy].append(r)
    statistics = []
    for strategy, values in sorted(by_strategy.items()):
        wins = sum(x > 0 for x in values)
        positives = sum(x for x in values if x > 0)
        losses = -sum(x for x in values if x < 0)
        statistics.append({
            "strategy_id": strategy, "virtual_n": len(values),
            "virtual_win_rate": round(wins / len(values), 6),
            "virtual_mean_r": round(sum(values) / len(values), 6),
            "virtual_r_profit_factor": round(positives / losses, 6) if losses > 0 else None,
            "research_sample_n_at_least_20": len(values) >= 20,
        })
    return {
        "schema_version": SCHEMA, "state": "RESEARCH_OBSERVATION_ONLY",
        "data_lane": "VIRTUAL_OBSERVATION_NOT_FILL",
        "events_examined": len(events), "virtual_closed_clean_n": len(completed),
        "virtual_closed_contaminated_n": contaminated,
        "virtual_open_n": len(open_by_key),
        "strategy_statistics": statistics,
        "costs_verified": False, "broker_fills_verified": False,
        "tested_expectancy_available": False, "source_authenticated": False,
        "promotion_eligible": False, "real_submit_allowed": False,
    }


def audit_local(ledger: Path, *, now):
    """Opt-in read of one bounded, non-symlinked private local ledger.

    No path, market values or account records are returned in status.
    Reading during a concurrent writer modification yields BLOCKED.
    """
    try:
        ledger = Path(ledger)
        if ledger.name != "ledger.jsonl" or any(p.is_symlink() for p in (ledger, *ledger.parents)):
            return _blocked("LEDGER_PATH_UNTRUSTED")
        before = ledger.stat()
        if not ledger.is_file() or not 0 < before.st_size <= _MAX_FILE_BYTES:
            return _blocked("LEDGER_SIZE_OR_TYPE_INVALID")
        with ledger.open("rb") as f:
            contents = f.read(_MAX_FILE_BYTES + 1)
        after = ledger.stat()
        if (len(contents) != before.st_size or before.st_size != after.st_size or
            before.st_mtime_ns != after.st_mtime_ns or before.st_ino != after.st_ino):
            return _blocked("LEDGER_CONCURRENT_CHANGE")
        text = contents.decode("utf-8-sig")
        lines = text.splitlines()
        if not 0 < len(lines) <= _MAX_EVENTS or any(not line or len(line.encode("utf-8")) > _MAX_EVENT_BYTES for line in lines):
            return _blocked("LEDGER_LINES_INVALID")
        events = [json.loads(line) for line in lines]
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, TypeError):
        return _blocked("LEDGER_INACCESSIBLE_OR_MALFORMED")
    return audit(events, now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description="V10 private virtual-outcome research audit; no orders, no publication")
    parser.add_argument("--ledger", required=True, help="private V10 AI SHADOW ledger.jsonl")
    args = parser.parse_args(argv)
    result = audit_local(Path(args.ledger), now=datetime.now(timezone.utc))
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["state"] == "RESEARCH_OBSERVATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
