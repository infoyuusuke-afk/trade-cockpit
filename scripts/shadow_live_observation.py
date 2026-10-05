"""Read-only view of a running AI SHADOW supervisor.

This module does not write the ledger, does not create a virtual trade, and
does not relax entry rules. A live round trip is not marked PASS here.
No entry on the collector board is NOT_RUN/LIVE_CONDITION_NOT_MET.
real_submit_allowed stays false.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ai_shadow_supervisor as shadow

HEARTBEAT_MAX_AGE_SECONDS = shadow.STATUS_STALE_SECONDS


def _age_seconds(value, now: datetime):
    parsed = shadow.parse_timestamp(value, now.tzinfo)
    if parsed is None:
        return None
    return (now - parsed).total_seconds()


def _load_json(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_ledger(path: Path) -> list[dict] | None:
    if not path.exists():
        return []
    rows, error = shadow._read_jsonl(path)
    if error:
        return None
    return rows or []


def _identity_price(live: dict):
    diag = live.get("live_price_diagnostics") if isinstance(live, dict) else None
    if isinstance(diag, dict) and diag.get("symbol") == shadow.IDENTITY_SYMBOL:
        price = diag.get("current_price")
        if shadow._finite(price) and price > 0:
            return price
    rows = live.get("all_targets") if isinstance(live, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("ticker") == shadow.IDENTITY_SYMBOL or row.get("symbol") == shadow.IDENTITY_SYMBOL:
            price = row.get("price")
            if shadow._finite(price) and price > 0:
                return price
    return None


def _entry_counts(live: dict) -> tuple[int, int]:
    rows = live.get("all_targets") if isinstance(live, dict) else None
    identity = 0
    other = 0
    if not isinstance(rows, list):
        return identity, other
    for row in rows:
        candidate = shadow.entry_candidate(row) if isinstance(row, dict) else None
        if candidate is None:
            continue
        if candidate.get("ticker") == shadow.IDENTITY_SYMBOL:
            identity += 1
        else:
            other += 1
    return identity, other


def _reason_key(row: dict) -> str:
    stored = row.get("no_trade_reason")
    if isinstance(stored, str) and stored:
        if stored == "SIGNAL_NOT_ENTRY":
            signal = row.get("signal") if isinstance(row.get("signal"), str) and row.get("signal") else "MISSING_SIGNAL"
            return "SIGNAL_NOT_ENTRY/" + signal
        return stored
    if row.get("entry_candidate") is True:
        return "ENTRY_CANDIDATE"
    signal = row.get("signal")
    if not isinstance(signal, str) or signal not in shadow.ENTRY_SIGNALS:
        label = signal if isinstance(signal, str) and signal else "MISSING_SIGNAL"
        return "SIGNAL_NOT_ENTRY/" + label
    return "ENTRY_SIGNAL_NOT_CANDIDATE"


def _format_counts(counts: dict) -> str:
    parts = []
    for key in sorted(counts):
        parts.append(key + ":" + str(counts[key]))
    return "|".join(parts)


def summarize_no_trade(ledger) -> dict:
    """Count why recorded board cycles did not open a virtual trade.

    Tickers are not included. Older rows have only the collector signal.
    """
    cycles = 0
    entry_cycles = 0
    missing_rows = 0
    totals: dict[str, int] = {}
    latest: dict[str, int] = {}
    if isinstance(ledger, list):
        for event in ledger:
            if not isinstance(event, dict) or event.get("event_type") != "board_judgment":
                continue
            cycles += 1
            opened = event.get("entry_seqs")
            if isinstance(opened, list) and opened:
                entry_cycles += 1
            rows = event.get("judgments")
            latest = {}
            if not isinstance(rows, list) or not rows:
                missing_rows += 1
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if row.get("entry_candidate") is True:
                    continue
                key = _reason_key(row)
                totals[key] = totals.get(key, 0) + 1
                latest[key] = latest.get(key, 0) + 1
    return {
        "no_trade_cycles": cycles - entry_cycles,
        "entry_cycles": entry_cycles,
        "judgment_rows_absent": missing_rows,
        "no_trade_reasons": _format_counts(totals),
        "latest_no_trade_reasons": _format_counts(latest),
    }


def _synthetic_ledger(ledger) -> bool:
    if not isinstance(ledger, list):
        return False
    for event in ledger:
        if isinstance(event, dict) and event.get("acceptance_class") == "synthetic":
            return True
    return False


def _live_roundtrip_complete(ledger) -> bool:
    """A live PASS needs one clean collector-quote round trip.

    Synthetic rows are not complete for this check. real_submit_allowed stays false.
    """
    if not isinstance(ledger, list) or _synthetic_ledger(ledger):
        return False
    exits = [
        event for event in ledger
        if isinstance(event, dict) and event.get("event_type") == "virtual_exit"
    ]
    complete = False
    for event in exits:
        if event.get("performance_bucket") != "clean_strategy":
            continue
        if event.get("fill_model") != "collector_quote_simulation":
            continue
        if event.get("quantity") is not None or event.get("real_submit_allowed") is not False:
            continue
        rationale = event.get("decision_rationale")
        if not isinstance(rationale, str) or not rationale:
            continue
        numbers = (
            "fill_entry_price",
            "fill_exit_price",
            "fill_pnl_per_share_yen",
            "slippage_yen",
            "mae_yen",
            "mfe_yen",
        )
        if all(shadow._finite(event.get(key)) for key in numbers):
            complete = True
    if not complete:
        return False
    stats = shadow.summarize_trade_performance(ledger)
    return stats.get("real_submit_allowed") is False and shadow._finite(stats.get("expectancy_yen_per_share")) and int(stats.get("closed_trade_count") or 0) >= 1


def classify_observation(status, lock, live, ledger, *, now: datetime) -> dict:
    """Classify supervisor observation. This does not create a trade."""
    heartbeat_age = _age_seconds(lock.get("heartbeat_at") if isinstance(lock, dict) else None, now)
    status_age = _age_seconds(status.get("updated_at") if isinstance(status, dict) else None, now)
    live_age = _age_seconds(live.get("updated_at") if isinstance(live, dict) else None, now)
    state = status.get("state") if isinstance(status, dict) else ""
    real_submit = None
    if isinstance(status, dict):
        real_submit = status.get("real_submit_allowed")
    if isinstance(lock, dict) and lock.get("real_submit_allowed") is not False:
        real_submit = lock.get("real_submit_allowed")
    if isinstance(live, dict) and live.get("real_submit_allowed") is not False:
        real_submit = live.get("real_submit_allowed")
    judgments = []
    entries = 0
    exits = 0
    if isinstance(ledger, list):
        for event in ledger:
            if not isinstance(event, dict):
                continue
            kind = event.get("event_type")
            if kind == "board_judgment":
                judgments.append(event)
            elif kind == "virtual_entry":
                entries += 1
            elif kind == "virtual_exit":
                exits += 1
    last_judgment = judgments[-1].get("at") if judgments else ""
    identity_entries, other_entries = _entry_counts(live if isinstance(live, dict) else {})
    fresh = (
        heartbeat_age is not None
        and status_age is not None
        and 0 <= heartbeat_age <= HEARTBEAT_MAX_AGE_SECONDS
        and 0 <= status_age <= HEARTBEAT_MAX_AGE_SECONDS
        and state == "RUNNING"
        and real_submit is False
    )
    if real_submit is not False:
        observation = "REAL_SUBMIT_NOT_FALSE"
        roundtrip = "NOT_RUN/REAL_SUBMIT_NOT_FALSE"
    elif not fresh:
        observation = "STALE"
        roundtrip = "NOT_RUN/HEARTBEAT_STALE"
    elif exits > 0 and _synthetic_ledger(ledger):
        observation = "FRESH"
        roundtrip = "NOT_RUN/SYNTHETIC_LEDGER"
    elif exits > 0 and _live_roundtrip_complete(ledger):
        observation = "FRESH"
        roundtrip = "PASS"
    elif exits > 0:
        observation = "FRESH"
        roundtrip = "LEDGER_INCOMPLETE"
    elif entries > 0:
        observation = "FRESH"
        roundtrip = "IN_PROGRESS"
    elif identity_entries + other_entries > 0:
        observation = "FRESH"
        roundtrip = "NOT_RUN/ENTRY_VISIBLE_NOT_RECORDED"
    else:
        observation = "FRESH"
        roundtrip = "NOT_RUN/LIVE_CONDITION_NOT_MET"
    return {
        "observation": observation,
        "live_roundtrip": roundtrip,
        "heartbeat_age_seconds": None if heartbeat_age is None else int(heartbeat_age),
        "status_age_seconds": None if status_age is None else int(status_age),
        "live_age_seconds": None if live_age is None else int(live_age),
        "shadow_state": state or "",
        "symbol": shadow.IDENTITY_SYMBOL,
        "price": _identity_price(live if isinstance(live, dict) else {}),
        "identity_entry_candidate_count": identity_entries,
        "other_entry_candidate_count": other_entries,
        "board_judgment_count": len(judgments),
        "last_board_judgment_at": last_judgment or "",
        "virtual_entry": entries,
        "virtual_exit": exits,
        "real_submit_allowed": False,
        **summarize_no_trade(ledger),
    }


def format_report(report: dict) -> str:
    lines = [
        "OBSERVATION=" + str(report["observation"]),
        "HEARTBEAT_AGE_SECONDS=" + str(report["heartbeat_age_seconds"]),
        "STATUS_AGE_SECONDS=" + str(report["status_age_seconds"]),
        "LIVE_AGE_SECONDS=" + str(report["live_age_seconds"]),
        "SHADOW_STATE=" + str(report["shadow_state"]),
        "SYMBOL=" + str(report["symbol"]),
        "PRICE=" + str(report["price"]),
        "IDENTITY_ENTRY_CANDIDATE_COUNT=" + str(report["identity_entry_candidate_count"]),
        "OTHER_ENTRY_CANDIDATE_COUNT=" + str(report["other_entry_candidate_count"]),
        "BOARD_JUDGMENT_COUNT=" + str(report["board_judgment_count"]),
        "LAST_BOARD_JUDGMENT_AT=" + str(report["last_board_judgment_at"]),
        "VIRTUAL_ENTRY=" + str(report["virtual_entry"]),
        "VIRTUAL_EXIT=" + str(report["virtual_exit"]),
        "LIVE_ROUNDTRIP=" + str(report["live_roundtrip"]),
        "NO_TRADE_CYCLES=" + str(report["no_trade_cycles"]),
        "ENTRY_CYCLES=" + str(report["entry_cycles"]),
        "JUDGMENT_ROWS_ABSENT=" + str(report["judgment_rows_absent"]),
        "NO_TRADE_REASONS=" + str(report["no_trade_reasons"]),
        "LATEST_NO_TRADE_REASONS=" + str(report["latest_no_trade_reasons"]),
        "REAL_SUBMIT_ALLOWED=0",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read AI SHADOW observation evidence")
    parser.add_argument("--status", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--live", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args(argv)
    now = datetime.now().astimezone()
    ledger = _load_ledger(Path(args.ledger))
    report = classify_observation(
        _load_json(Path(args.status)),
        _load_json(Path(args.lock)),
        _load_json(Path(args.live)),
        ledger,
        now=now,
    )
    print(format_report(report))
    if report["observation"] != "FRESH":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
