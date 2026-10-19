"""V10 Brain private research bridge: live market integrity + virtual R research.

Read locally observed MS2/Shadow evidence without changing either producer.
Writes only a derived, strictly non-tradable status in the private Shadow
directory; never sends private evidence to GitHub, network, GPT or broker.
NOT a live execution strategy, a signal generator or a validated EV score.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from scripts.ai_brain_observer import analyze as observe_or15_vwap
from scripts.ai_shadow_supervisor import (
    assess_live_payload,
    board_row_freshness,
    assess_board_availability,
)
from scripts.v10_brain_virtual_outcome_audit import audit_local as audit_virtual_outcomes

SCHEMA = "v10-brain-private-research-context-1"
STATUS_NAME = "brain_research_context_v1.json"
LIVE_NAME = "live_ms2.json"
UNIVERSE_NAME = "watchlist_100.json"
LEDGER_NAME = "ledger.jsonl"
MAX_LIVE_BYTES = 8_000_000
MAX_WATCHLIST_BYTES = 1_000_000


def blocked(reason):
    return {
        "schema_version": SCHEMA, "state": "BLOCKED",
        "reasons": [reason],
        "market_data_gate": "BLOCKED",
        "virtual_outcome_gate": "BLOCKED",
        "market_quote_at": None,
        "verified_board_row_count": None,
        "strategy_statistics": [],
        "research_observation_counts": None,
        "data_lane": "LOCAL_MS2_OBSERVATION_AND_VIRTUAL_RESEARCH",
        "costs_verified": False,
        "broker_fills_verified": False,
        "tested_expectancy_available": False,
        "source_authenticated": False,
        "brain_trade_decision_eligible": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
    }


def evaluate_context(payload, file_mtime, universe, virtual, *, now):
    """Compose the existing *independent* source and research gates.

    A healthy payload writer does not prove a fresh exchange quote. Identity
    quote, all 100 row quotes, expected watchlist, OR15 observer and complete
    virtual ledger must independently pass. This gate never promotes trades.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        return blocked("DECISION_CLOCK_UNVERIFIED")
    if not isinstance(payload, dict) or not isinstance(virtual, dict):
        return blocked("INPUT_TYPE_INVALID")
    if payload.get("real_submit_allowed") is not False:
        return blocked("REAL_ORDER_FLAG_UNSAFE")
    try:
        live = assess_live_payload(payload, file_mtime=file_mtime, now=now)
        identity = live.get("quote_freshness")
        quote_at = identity.get("quote_at") if isinstance(identity, dict) else None
        row = board_row_freshness(payload, now=now, board_quote_at=quote_at)
        board = assess_board_availability(payload, identity, row, universe)
        observer = observe_or15_vwap(payload, now=now, file_modified_at=file_mtime)
    except (TypeError, KeyError, ValueError, AttributeError, ZeroDivisionError, OverflowError):
        return blocked("SOURCE_VALIDATOR_REJECTED")
    reasons = []
    if live.get("ok") is not True:
        reasons.append("LIVE_SOURCE_UNVERIFIED")
    if board.get("decision_available") is not True:
        reasons.append("BOARD_OR_UNIVERSE_UNVERIFIED")
    if observer.get("state") != "OBSERVATION_ONLY":
        reasons.append("BRAIN_OBSERVER_UNVERIFIED")
    virtual_ok = (virtual.get("state") == "RESEARCH_OBSERVATION_ONLY" and
                  virtual.get("real_submit_allowed") is False and
                  virtual.get("tested_expectancy_available") is False and
                  virtual.get("source_authenticated") is False and
                  virtual.get("promotion_eligible") is False and
                  virtual.get("data_lane") == "VIRTUAL_OBSERVATION_NOT_FILL" and
                  virtual.get("broker_fills_verified") is False and
                  virtual.get("costs_verified") is False)
    if not virtual_ok:
        reasons.append("VIRTUAL_LEDGER_UNVERIFIED")
    if reasons:
        result = blocked(reasons[0])
        result["reasons"] = sorted(set(reasons))
        result["market_data_gate"] = (
            "PASS" if live.get("ok") and board.get("decision_available")
            and observer.get("state") == "OBSERVATION_ONLY" else "BLOCKED"
        )
        result["virtual_outcome_gate"] = "PASS" if virtual_ok else "BLOCKED"
        return result

    # Export only aggregated research data. No ticker, quote, fill, account,
    # local path, owner identity, raw market events or signal entry is exported.
    stats = virtual.get("strategy_statistics")
    counts = observer.get("watch_counts")
    if (type(stats) is not list or type(counts) is not dict or
        type(board.get("row_count")) is not int or board["row_count"] != 100):
        return blocked("RESEARCH_AGGREGATE_INVALID")
    safe_stats = []
    for stat in stats:
        if type(stat) is not dict or set(stat) != {
            "strategy_id", "virtual_n", "virtual_win_rate", "virtual_mean_r",
            "virtual_r_profit_factor", "research_sample_n_at_least_20"
        }:
            return blocked("STRATEGY_STAT_SCHEMA_INVALID")
        if type(stat.get("virtual_n")) is not int or stat["virtual_n"] < 1:
            return blocked("STRATEGY_STAT_N_INVALID")
        safe_stats.append(dict(stat))
    if (set(counts) != {"OR15_ABOVE_VWAP_WATCH", "OR15_BELOW_VWAP_WATCH"} or
        any(type(x) is not int or x < 0 for x in counts.values())):
        return blocked("OR15_OBSERVATION_COUNTS_INVALID")
    return {
        "schema_version": SCHEMA,
        "state": "RESEARCH_OBSERVATION_ONLY",
        "reasons": [],
        "market_data_gate": "PASS",
        "virtual_outcome_gate": "PASS",
        "market_quote_at": quote_at,
        "verified_board_row_count": board["row_count"],
        "research_observation_counts": dict(sorted(counts.items())),
        "strategy_statistics": safe_stats,
        "virtual_closed_clean_n": virtual.get("virtual_closed_clean_n"),
        "virtual_closed_contaminated_n": virtual.get("virtual_closed_contaminated_n"),
        "virtual_open_n": virtual.get("virtual_open_n"),
        "data_lane": "LOCAL_MS2_OBSERVATION_AND_VIRTUAL_RESEARCH",
        "costs_verified": False,
        "broker_fills_verified": False,
        "tested_expectancy_available": False,
        "source_authenticated": False,
        "brain_trade_decision_eligible": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
    }


def _trusted_file(path, expected_name, max_bytes):
    """Reject symlinks and concurrent mutations before decoding local JSON."""
    path = Path(path)
    if path.name != expected_name or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("SOURCE_PATH_UNTRUSTED")
    before = path.stat()
    if not path.is_file() or not 2 <= before.st_size <= max_bytes:
        raise ValueError("SOURCE_SIZE_INVALID")
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    after = path.stat()
    if (len(raw) != before.st_size or
        (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) !=
        (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size)):
        raise ValueError("SOURCE_CHANGED_DURING_READ")
    data = json.loads(raw.decode("utf-8-sig"))
    if type(data) is not dict:
        raise ValueError("SOURCE_SCHEMA_INVALID")
    return data, datetime.fromtimestamp(before.st_mtime, timezone.utc)


def _universe(watch):
    """Match the already-pinned V10 expected-watchlist first-100 contract."""
    stocks = watch.get("stocks") if isinstance(watch, dict) else None
    if type(stocks) is not dict:
        return {"verified": False, "reason": "WATCHLIST_FORMAT_INVALID"}
    tickers = []
    for item in list(stocks.values())[:100]:
        ticker = item.get("ticker") if type(item) is dict else None
        if not isinstance(ticker, str) or not ticker.strip() or ticker.strip() in tickers:
            return {"verified": False, "reason": "WATCHLIST_ROW_INVALID"}
        tickers.append(ticker.strip())
    if len(tickers) != 100:
        return {"verified": False, "reason": "WATCHLIST_COUNT_INVALID"}
    return {"verified": True, "expected_count": 100, "tickers": tickers}


def _private_output_path(status, ledger):
    status, ledger = Path(status), Path(ledger)
    if status.name != STATUS_NAME or ledger.name != LEDGER_NAME:
        return False
    if os.path.abspath(status.parent) != os.path.abspath(ledger.parent):
        return False
    if any(p.is_symlink() for p in (status, *status.parents, ledger, *ledger.parents)):
        return False
    return status.parent.is_dir()


def _write_private_status(status, result):
    status = Path(status)
    if status.is_symlink() or not status.parent.is_dir():
        raise ValueError("STATUS_DESTINATION_UNTRUSTED")
    raw = (json.dumps(result, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    if len(raw) > 65_536:
        raise ValueError("STATUS_TOO_LARGE")
    temp = status.with_name(status.name + "." + str(os.getpid()) + ".tmp")
    try:
        with temp.open("xb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        if status.is_symlink():
            raise ValueError("STATUS_DESTINATION_UNTRUSTED")
        os.replace(temp, status)
    finally:
        temp.unlink(missing_ok=True)


def run_once(*, live_path, watchlist_path, ledger_path, status_path, now):
    """Explicit local one-shot bridge; no timer, background service or orders."""
    if not _private_output_path(status_path, ledger_path):
        return blocked("STATUS_PRIVATE_BOUNDARY_UNVERIFIED")
    try:
        live, mtime = _trusted_file(live_path, LIVE_NAME, MAX_LIVE_BYTES)
        watch, _ = _trusted_file(watchlist_path, UNIVERSE_NAME, MAX_WATCHLIST_BYTES)
        virtual = audit_virtual_outcomes(Path(ledger_path), now=now)
        result = evaluate_context(live, mtime, _universe(watch), virtual, now=now)
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        result = blocked("LOCAL_INPUT_UNAVAILABLE_OR_INVALID")
    try:
        _write_private_status(status_path, result)
    except (OSError, ValueError, TypeError):
        return blocked("PRIVATE_STATUS_WRITE_UNVERIFIED")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Private one-shot V10 Brain research bridge; NO orders")
    parser.add_argument("--live", required=True)
    parser.add_argument("--watchlist", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--status", required=True)
    args = parser.parse_args(argv)
    result = run_once(live_path=args.live, watchlist_path=args.watchlist,
                      ledger_path=args.ledger, status_path=args.status,
                      now=datetime.now(timezone.utc))
    # Only sanitized, aggregate-only status. Never print private source paths.
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["state"] == "RESEARCH_OBSERVATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
