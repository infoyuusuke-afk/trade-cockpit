"""Background AI SHADOW supervisor.

The cockpit page does not own this process. The V9 controller starts one
Python process; the browser only reads the status the process publishes.

This module does not call scripts/shadow_execution.py. Collector rows do not
carry an Intent, RiskDecision, or PermissionTicket, and fabricating that
lineage would violate the existing fail-closed contract. Virtual entries use
only prices and signals the collector already published. They are not broker
fills and not Fill Model v0.1 fills.

real_submit_allowed is always false on every record this module writes.
An unresolved excel_identity, workbook_open, or excel_process_exit incident
blocks new virtual entries and exits. A fresh price file does not clear it.
An unreadable manual_recovery.json does the same. Two rows for one ticker
are a data conflict and open or close nothing. A ledger row that carries a
quantity is not replayed. state.json last_seq must equal the ledger length;
a short or long ledger is not healed into a resume.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = "ai-shadow-supervisor-1"
CANONICAL_SOURCE = "MarketSpeed II RSS / local PC"
CANONICAL_WORKBOOK = "Kioxia_MS2_RSS_Live_Signals.xlsx"
MAX_AGE_SECONDS = 60
STATUS_STALE_SECONDS = 30

LONG_ENTRY_SIGNALS = frozenset({"初動買い候補", "買いサイン", "持ち越しロング確定"})
SHORT_ENTRY_SIGNALS = frozenset({"初動ショート候補", "空売りサイン", "持ち越しショート確定"})
ENTRY_SIGNALS = LONG_ENTRY_SIGNALS | SHORT_ENTRY_SIGNALS

STATES = ("RUNNING", "PAUSED_FAIL_CLOSED", "RECOVERING", "STOPPED")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and value not in (float("inf"), float("-inf"))


def parse_timestamp(value, tz) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("JST"):
        text = text[:-3].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=tz)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


# --- Quote freshness (P0-V10-ACCEPTANCE-FIX-20261019) ----------------------
# Writer time is not quote time. updated_at, observed_at_offset and the file
# mtime only prove that the Collector rewrote live_ms2.json. They say nothing
# about when the market produced the price. The 2026-10-19 Windows acceptance
# found a Friday 15:30 quote republished every 2 seconds and reported as fresh
# at Monday 02:14 JST.
#
# The functions below judge the quote itself and keep four times apart:
#   occurrence  source_timestamp (MS2 RSS 現在値詳細時刻, time of day only)
#   quote_at    source_timestamp_at, the occurrence with an explicit date and
#               offset, plus source_timestamp_basis saying how the date was
#               found
#   observed    source_timestamp_observed_at, when the Collector saw it change
#   written     updated_at / file mtime (checked in assess_live_payload,
#               necessary but never sufficient)
# A time of day without a date is never assumed to be today. No date, no
# offset, a future quote, a quote older than the last accepted one, or two
# trading dates in one payload is not fresh. A closed market is reported
# separately and never makes an old quote fresh. Every verdict carries
# real_submit_allowed False and order_allowed False. Clock arithmetic uses JST
# (UTC+09:00, no DST) explicitly, never the local time zone of the PC.

FRESHNESS_SCHEMA_VERSION = "price-freshness-1"
JST = timezone(timedelta(hours=9), "JST")
MAX_QUOTE_AGE_SECONDS = 120
FUTURE_SKEW_SECONDS = 5

FRESH = "FRESH"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
INVALID = "INVALID"

# Bases that carry real date evidence. Anything else is not a dated quote.
DATED_BASES = frozenset({"MS2_RSS_DATE_ITEM", "COLLECTOR_OBSERVED_CHANGE"})

# TSE cash equity continuous sessions (JST). Holidays are not modelled, so a
# weekday holiday reports OPEN_BY_CLOCK; quote age still decides freshness.
SESSIONS = ((clock_time(9, 0), clock_time(11, 30)), (clock_time(12, 30), clock_time(15, 30)))

_TIME_ONLY = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_OFFSET_SUFFIX = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def now_jst() -> datetime:
    return datetime.now(timezone.utc).astimezone(JST)


def parse_offset_timestamp(value) -> datetime | None:
    """ISO 8601 with an explicit offset only. Naive text is rejected."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not _OFFSET_SUFFIX.search(text):
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(JST)


def market_session(moment: datetime) -> str:
    local = moment.astimezone(JST)
    if local.weekday() >= 5:
        return "CLOSED_WEEKEND"
    clock = local.time()
    for start, end in SESSIONS:
        if start <= clock <= end:
            return "OPEN_BY_CLOCK"
    return "CLOSED_OUTSIDE_HOURS"


def _quote_diagnostics(payload) -> dict:
    diag = payload.get("live_price_diagnostics") if isinstance(payload, dict) else None
    return diag if isinstance(diag, dict) else {}


def _row_quote_dates(payload) -> set:
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    dates = set()
    if not isinstance(rows, list):
        return dates
    for row in rows:
        if not isinstance(row, dict) or row.get("source_timestamp_at") in (None, ""):
            continue
        parsed = parse_offset_timestamp(row.get("source_timestamp_at"))
        dates.add(parsed.date() if parsed is not None else None)
    return dates


def _freshness_verdict(state: str, reasons: list[str], *, now: datetime,
                       quote_at: datetime | None, basis, max_age: int) -> dict:
    unique = sorted(set(reasons))
    return {
        "schema_version": FRESHNESS_SCHEMA_VERSION,
        "state": state,
        "fresh": state == FRESH and not unique,
        "reasons": unique,
        "quote_at": quote_at.isoformat(timespec="seconds") if quote_at is not None else None,
        "quote_basis": basis if isinstance(basis, str) else None,
        "quote_age_seconds": round((now - quote_at).total_seconds(), 3) if quote_at is not None else None,
        "evaluated_at": now.isoformat(timespec="seconds"),
        "max_quote_age_seconds": max_age,
        "market_session": market_session(now),
        "timezone": "Asia/Tokyo",
        "order_allowed": False,
        "real_submit_allowed": False,
    }


def assess_quote_freshness(payload, *, now: datetime, previous_quote_at=None,
                           max_quote_age_seconds: int = MAX_QUOTE_AGE_SECONDS,
                           future_skew_seconds: int = FUTURE_SKEW_SECONDS) -> dict:
    """Freshness verdict for the identity quote of a live payload."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        epoch = datetime(1970, 1, 1, tzinfo=JST)
        return _freshness_verdict(INVALID, ["NOW_NOT_TIMEZONE_AWARE"], now=epoch, quote_at=None,
                                  basis=None, max_age=max_quote_age_seconds)
    now = now.astimezone(JST)
    if not isinstance(payload, dict):
        return _freshness_verdict(UNKNOWN, ["MISSING_PAYLOAD"], now=now, quote_at=None,
                                  basis=None, max_age=max_quote_age_seconds)

    diag = _quote_diagnostics(payload)
    raw_time = diag.get("source_timestamp")
    raw_at = diag.get("source_timestamp_at")
    basis = diag.get("source_timestamp_basis")

    if raw_at in (None, ""):
        if raw_time in (None, ""):
            reason = "SOURCE_TIMESTAMP_MISSING"
        elif isinstance(raw_time, str) and _TIME_ONLY.match(raw_time.strip()):
            reason = "SOURCE_DATE_UNKNOWN"
        else:
            reason = "SOURCE_TIMESTAMP_UNPARSEABLE"
        return _freshness_verdict(UNKNOWN, [reason], now=now, quote_at=None, basis=basis,
                                  max_age=max_quote_age_seconds)

    quote_at = parse_offset_timestamp(raw_at)
    if quote_at is None:
        return _freshness_verdict(UNKNOWN, ["SOURCE_TIMESTAMP_NO_OFFSET"], now=now, quote_at=None,
                                  basis=basis, max_age=max_quote_age_seconds)
    if not isinstance(basis, str) or basis not in DATED_BASES:
        return _freshness_verdict(UNKNOWN, ["SOURCE_DATE_BASIS_UNVERIFIED"], now=now,
                                  quote_at=quote_at, basis=basis, max_age=max_quote_age_seconds)

    invalid: list[str] = []
    if isinstance(raw_time, str) and _TIME_ONLY.match(raw_time.strip()):
        if quote_at.strftime("%H:%M:%S") != raw_time.strip():
            invalid.append("SOURCE_TIMESTAMP_INCONSISTENT")
    elif raw_time not in (None, ""):
        invalid.append("SOURCE_TIMESTAMP_UNPARSEABLE")

    age = (now - quote_at).total_seconds()
    if age < -future_skew_seconds:
        invalid.append("SOURCE_TIMESTAMP_IN_FUTURE")

    if basis == "COLLECTOR_OBSERVED_CHANGE":
        observed = parse_offset_timestamp(diag.get("source_timestamp_observed_at"))
        if observed is None:
            return _freshness_verdict(UNKNOWN, ["SOURCE_OBSERVATION_MISSING"], now=now,
                                      quote_at=quote_at, basis=basis, max_age=max_quote_age_seconds)
        if (observed - now).total_seconds() > future_skew_seconds:
            invalid.append("SOURCE_OBSERVATION_IN_FUTURE")
        if (quote_at - observed).total_seconds() > future_skew_seconds:
            invalid.append("SOURCE_TIMESTAMP_AFTER_OBSERVATION")

    previous = previous_quote_at
    if isinstance(previous, str):
        previous = parse_offset_timestamp(previous)
    if isinstance(previous, datetime) and previous.tzinfo is not None and quote_at < previous.astimezone(JST):
        invalid.append("SOURCE_TIMESTAMP_REGRESSION")

    dates = _row_quote_dates(payload)
    if None in dates or (dates and dates != {quote_at.date()}):
        invalid.append("MIXED_SOURCE_DATES")

    if invalid:
        return _freshness_verdict(INVALID, invalid, now=now, quote_at=quote_at, basis=basis,
                                  max_age=max_quote_age_seconds)
    if age > max_quote_age_seconds:
        return _freshness_verdict(STALE, ["STALE_SOURCE_QUOTE"], now=now, quote_at=quote_at,
                                  basis=basis, max_age=max_quote_age_seconds)
    return _freshness_verdict(FRESH, [], now=now, quote_at=quote_at, basis=basis,
                              max_age=max_quote_age_seconds)


ROW_QUOTE_FIELDS = ("source_timestamp", "source_timestamp_at", "source_timestamp_basis", "source_timestamp_observed_at")


def row_quote_freshness(row, *, now: datetime, board_quote_at=None, previous_quote_at=None) -> dict:
    """The same quote rules applied to one board row.

    A fresh board (the identity quote just traded) says nothing about another
    row's price. A row is usable for a virtual entry or exit only if its own
    quote is dated, within the age limit, not in the future, and on the same
    JST trading date as the board's identity quote.
    """
    fields = {key: row.get(key) for key in ROW_QUOTE_FIELDS} if isinstance(row, dict) else {}
    verdict = assess_quote_freshness({"live_price_diagnostics": fields, "all_targets": []}, now=now,
                                     previous_quote_at=previous_quote_at)
    board = parse_offset_timestamp(board_quote_at) if isinstance(board_quote_at, str) else None
    row_at = parse_offset_timestamp(verdict.get("quote_at")) if verdict.get("quote_at") else None
    if verdict.get("fresh") and (board is None or row_at is None or row_at.date() != board.date()):
        reason = "BOARD_QUOTE_DATE_UNKNOWN" if board is None else "MIXED_SOURCE_DATES"
        verdict = dict(verdict, state=INVALID, fresh=False, reasons=sorted(set(verdict["reasons"]) | {reason}))
    return verdict


# Board availability: the same identity, per-row and universe gate as
# Get-BoardRowFreshness / Get-ExpectedUniverse / Get-BoardAvailability in
# downloads/AI_COCKPIT_GATEWAY_V10.ps1. The source being healthy (identity
# checks pass) is kept apart from whether the board may be used for any
# decision. tests/test_v10_row_gate_operability.py compares the two sides.
EXPECTED_UNIVERSE_COUNT = 100
AVAILABILITY_SCHEMA_VERSION = "board-availability-1"
OBSERVATION_SCHEMA_VERSION = "v10-board-observation-1"


def board_row_freshness(payload, *, now: datetime, board_quote_at=None, previous_row_quotes=None) -> dict:
    """Every all_targets row judged by its own quote; unknown is not fresh."""
    reasons: list[str] = []
    accepted: dict[str, str] = {}
    not_fresh: list[dict] = []
    verdict_rows: list[dict] = []
    counts = {FRESH: 0, STALE: 0, UNKNOWN: 0, INVALID: 0}
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    fresh_count = 0
    row_count = 0
    if not isinstance(rows, list) or not rows:
        reasons.append("BOARD_ROWS_MISSING")
    else:
        seen: set[str] = set()
        for row in rows:
            row_count += 1
            ticker = row.get("ticker") if isinstance(row, dict) else None
            if not isinstance(ticker, str) or not ticker.strip():
                reasons.append("ROW_TICKER_MISSING")
                counts[UNKNOWN] += 1
                verdict_rows.append({"ticker": None, "state": UNKNOWN, "reasons": ["ROW_TICKER_MISSING"],
                                     "quote_at": None, "quote_age_seconds": None})
                if len(not_fresh) < 10:
                    not_fresh.append({"ticker": None, "state": UNKNOWN, "reasons": ["ROW_TICKER_MISSING"]})
                continue
            if ticker in seen:
                reasons.append("ROW_TICKER_DUPLICATE")
                counts[INVALID] += 1
                verdict_rows.append({"ticker": ticker, "state": INVALID, "reasons": ["ROW_TICKER_DUPLICATE"],
                                     "quote_at": None, "quote_age_seconds": None})
                if len(not_fresh) < 10:
                    not_fresh.append({"ticker": ticker, "state": INVALID, "reasons": ["ROW_TICKER_DUPLICATE"]})
                continue
            seen.add(ticker)
            previous = previous_row_quotes.get(ticker) if isinstance(previous_row_quotes, dict) else None
            verdict = row_quote_freshness(row, now=now, board_quote_at=board_quote_at, previous_quote_at=previous)
            state = verdict.get("state")
            counts[state if state in counts else INVALID] += 1
            verdict_rows.append({"ticker": ticker, "state": state, "reasons": list(verdict.get("reasons") or []),
                                 "quote_at": verdict.get("quote_at"),
                                 "quote_age_seconds": verdict.get("quote_age_seconds")})
            if verdict.get("fresh") is True:
                fresh_count += 1
                accepted[ticker] = verdict.get("quote_at")
                continue
            own = [r for r in (verdict.get("reasons") or []) if r] or ["FRESHNESS_NOT_FRESH"]
            reasons.extend("ROW_" + r for r in own)
            if len(not_fresh) < 10:
                not_fresh.append({"ticker": ticker, "state": state, "reasons": own})
    if reasons:
        reasons.append("ROW_QUOTE_NOT_FRESH")
    unique = sorted(set(reasons))
    return {
        "schema_version": "board-row-freshness-1",
        "fresh": not unique,
        "reasons": unique,
        "row_count": row_count,
        "fresh_row_count": fresh_count,
        "not_fresh_row_count": row_count - fresh_count,
        "not_fresh_sample": not_fresh,
        "state_counts": counts,
        "row_verdicts": verdict_rows,
        "accepted_quote_at": accepted,
        "board_quote_at": board_quote_at if isinstance(board_quote_at, str) else None,
        "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
        "order_allowed": False,
        "real_submit_allowed": False,
    }


def load_expected_universe(directory: Path | None) -> dict:
    """The first 100 tickers of watchlist_100.json, or an unverified result."""
    result = {"verified": False, "reason": "UNIVERSE_WATCHLIST_MISSING",
              "expected_count": EXPECTED_UNIVERSE_COUNT, "tickers": []}
    if directory is None:
        return result
    path = Path(directory) / "watchlist_100.json"
    if not path.exists():
        return result
    try:
        watch = json.loads(path.read_text(encoding="utf-8-sig"))
        stocks = watch.get("stocks") if isinstance(watch, dict) else None
        if not isinstance(stocks, dict):
            return dict(result, reason="UNIVERSE_WATCHLIST_INVALID")
        tickers: list[str] = []
        for value in stocks.values():
            if len(tickers) >= EXPECTED_UNIVERSE_COUNT:
                break
            ticker = value.get("ticker") if isinstance(value, dict) else None
            if not isinstance(ticker, str) or not ticker.strip():
                return dict(result, reason="UNIVERSE_WATCHLIST_INVALID")
            ticker = ticker.strip()
            if ticker in tickers:
                return dict(result, reason="UNIVERSE_WATCHLIST_DUPLICATE")
            tickers.append(ticker)
        if len(tickers) != EXPECTED_UNIVERSE_COUNT:
            return dict(result, reason="UNIVERSE_WATCHLIST_COUNT")
        return {"verified": True, "reason": None, "expected_count": EXPECTED_UNIVERSE_COUNT, "tickers": tickers}
    except (OSError, ValueError):
        return dict(result, reason="UNIVERSE_WATCHLIST_UNREADABLE")


def _plain_positive_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


PARTIAL_MIN_FRESH_PCT = 95.0


def assess_board_availability(payload, quote_freshness: dict | None, row_freshness: dict | None,
                              universe: dict | None) -> dict:
    """Whether this board may be used for any decision (entry, exit, ranking).

    99 present rows of 100 are an incomplete board, never a 99-symbol board.
    The Collector's valid>=90 quality count is reported and grants nothing.
    """
    reasons: list[str] = []
    identity_fresh = isinstance(quote_freshness, dict) and quote_freshness.get("fresh") is True
    if not identity_fresh:
        reasons.append("IDENTITY_QUOTE_NOT_FRESH")
    rows_fresh = isinstance(row_freshness, dict) and row_freshness.get("fresh") is True
    if not isinstance(row_freshness, dict):
        reasons.append("ROW_QUOTE_NOT_FRESH")
    elif not rows_fresh:
        reasons.extend(r for r in (row_freshness.get("reasons") or []) if r)
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    present: list[str] = []
    row_count = 0
    if isinstance(rows, list):
        for row in rows:
            row_count += 1
            ticker = row.get("ticker") if isinstance(row, dict) else None
            if isinstance(ticker, str) and ticker.strip():
                present.append(ticker.strip())
    declared = _plain_positive_int(payload.get("universe")) if isinstance(payload, dict) else None
    if declared is None:
        reasons.append("UNIVERSE_DECLARED_MISSING")
    elif declared != row_count:
        reasons.append("UNIVERSE_DECLARED_MISMATCH")
    missing: list[str] = []
    unexpected: list[str] = []
    expected_count = None
    verified = isinstance(universe, dict) and universe.get("verified") is True
    if not verified:
        reasons.append("UNIVERSE_UNVERIFIED")
        if isinstance(universe, dict) and universe.get("reason"):
            reasons.append(str(universe["reason"]))
    else:
        expected = [str(t) for t in universe.get("tickers") or []]
        expected_count = len(expected)
        present_set = list(dict.fromkeys(present))
        missing = [t for t in expected if t not in set(present_set)]
        unexpected = [t for t in present_set if t not in set(expected)]
        if missing:
            reasons.append("UNIVERSE_ROW_MISSING")
        if unexpected:
            reasons.append("UNIVERSE_ROW_UNEXPECTED")
        if declared is not None and declared != expected_count:
            reasons.append("UNIVERSE_DECLARED_MISMATCH")
    unique = sorted(set(reasons))
    if not identity_fresh:
        status = "BLOCKED_IDENTITY_QUOTE"
    elif any(r.startswith("UNIVERSE_") for r in unique):
        status = "BLOCKED_UNIVERSE_INCOMPLETE"
    elif not rows_fresh:
        status = "BLOCKED_ROW_QUOTES"
    else:
        status = "AVAILABLE"
    # Fresh-rows-only use (P0-V10-INTEGRATION-AND-LIVE-START-20261020), the
    # same rule as Get-BoardAvailability: STALE/UNKNOWN rows only, identity
    # fresh, universe complete, no INVALID row, >= 95% of expected rows FRESH,
    # and the Collector computed every aggregate from FRESH rows only.
    partial_rows = False
    partial_reasons: list[str] = []
    aggregate_basis = payload.get("aggregate_basis") if isinstance(payload, dict) else None
    if (status == "BLOCKED_ROW_QUOTES" and aggregate_basis == "FRESH_ROWS_ONLY"
            and isinstance(row_freshness, dict) and isinstance(row_freshness.get("state_counts"), dict)
            and isinstance(expected_count, int) and expected_count > 0):
        partial_fresh = int(row_freshness["state_counts"].get(FRESH) or 0)
        partial_invalid = int(row_freshness["state_counts"].get(INVALID) or 0)
        other = [r for r in unique if not r.startswith("ROW_") or r.startswith("ROW_TICKER_")]
        if partial_invalid == 0 and not other and 100.0 * partial_fresh / expected_count >= PARTIAL_MIN_FRESH_PCT:
            partial_rows = True
            partial_reasons = unique
            unique = []
            status = "AVAILABLE_PARTIAL"
    counts = {FRESH: 0, STALE: 0, UNKNOWN: 0, INVALID: 0, "MISSING": len(missing)}
    if isinstance(row_freshness, dict) and isinstance(row_freshness.get("state_counts"), dict):
        for key in (FRESH, STALE, UNKNOWN, INVALID):
            counts[key] = int(row_freshness["state_counts"].get(key) or 0)
    base = expected_count if expected_count is not None else (declared if declared is not None else row_count)
    coverage = round(100.0 * counts[FRESH] / base, 1) if base else None
    valid = payload.get("valid") if isinstance(payload, dict) else None
    valid = valid if isinstance(valid, int) and not isinstance(valid, bool) else None
    return {
        "schema_version": AVAILABILITY_SCHEMA_VERSION,
        "decision_available": not unique,
        "availability_status": status,
        "reasons": unique,
        "identity_quote_fresh": identity_fresh,
        "universe_verified": verified,
        "universe_expected_count": expected_count,
        "universe_declared": declared,
        "row_count": row_count,
        "state_counts": counts,
        "fresh_coverage_pct": coverage,
        "missing_count": len(missing),
        "missing_sample": missing[:10],
        "unexpected_count": len(unexpected),
        "unexpected_sample": unexpected[:10],
        "collector_valid_count": valid,
        "collector_valid_quality_pass": valid is not None and valid >= 90,
        "partial_rows": partial_rows,
        "partial_reasons": partial_reasons,
        "partial_min_fresh_pct": PARTIAL_MIN_FRESH_PCT,
        "order_allowed": False,
        "real_submit_allowed": False,
    }


def _last_jsonl_record(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        if line.strip():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                return None
            return item if isinstance(item, dict) else None
    return None


# P0-V10-MARKET-OPERABILITY-20261019 (D-026 plan A, staged): an evaluation of
# what a fresh-rows-only decision layer would have allowed. SHADOW ONLY: it is
# recorded beside each observation and never changes decision_available, the
# Risk Gate, the Permission Gate or the Kill Switch. The threshold is a
# proposal for the development lead, not an approved rule.
SHADOW_FRESH_ONLY_MIN_FRESH_PCT = 95.0


def shadow_fresh_only_evaluation(payload, rows: dict, availability: dict, *,
                                 min_fresh_pct: float = SHADOW_FRESH_ONLY_MIN_FRESH_PCT) -> dict:
    """Would a decision from FRESH rows only be representative, and which
    published candidates would survive? Market aggregates (top5 ranking,
    market state, sector strength, breadth) are not recomputed here; they
    stay withheld until a recomputation is proven."""
    verdicts = {r.get("ticker"): r for r in rows.get("row_verdicts") or [] if isinstance(r, dict)}
    expected = availability.get("universe_expected_count")
    counts = availability.get("state_counts") or {}
    fresh = int(counts.get(FRESH) or 0)
    invalid = int(counts.get(INVALID) or 0)
    fresh_pct = round(100.0 * fresh / expected, 1) if isinstance(expected, int) and expected > 0 else None
    reasons: list[str] = []
    if availability.get("identity_quote_fresh") is not True:
        reasons.append("IDENTITY_QUOTE_NOT_FRESH")
    if availability.get("universe_verified") is not True:
        reasons.append("UNIVERSE_UNVERIFIED")
    if fresh_pct is None or fresh_pct < min_fresh_pct:
        reasons.append("FRESH_ROWS_NOT_REPRESENTATIVE")
    if invalid:
        reasons.append("INVALID_ROWS_PRESENT")
    if int(availability.get("unexpected_count") or 0):
        reasons.append("UNEXPECTED_ROWS_PRESENT")
    published = payload.get("top5") if isinstance(payload, dict) and isinstance(payload.get("top5"), list) else []
    kept = 0
    dropped: dict[str, int] = {}
    for candidate in published:
        ticker = candidate.get("ticker") if isinstance(candidate, dict) else None
        verdict = verdicts.get(ticker)
        if verdict is None:
            reason = "CANDIDATE_ROW_MISSING"
        elif verdict.get("state") != FRESH:
            reason = "CANDIDATE_ROW_NOT_FRESH"
        elif not verdict.get("quote_at"):
            reason = "CANDIDATE_INPUT_TIME_UNKNOWN"
        else:
            kept += 1
            continue
        dropped[reason] = dropped.get(reason, 0) + 1
    return {
        "mode": "SHADOW_ONLY",
        "applied_to_decision": False,
        "min_fresh_pct": min_fresh_pct,
        "expected_count": expected,
        "fresh_count": fresh,
        "fresh_pct": fresh_pct,
        "would_be_decidable": not reasons,
        "reasons": sorted(set(reasons)),
        "candidates_published": len(published),
        "candidates_with_fresh_inputs": kept,
        "candidates_invalidated": sum(dropped.values()),
        "candidate_invalidation_reasons": dict(sorted(dropped.items())),
        "aggregates": "WITHHELD_NOT_RECOMPUTED",
        "order_allowed": False,
        "real_submit_allowed": False,
    }


def record_board_observation(data_dir: Path, *, now: datetime, payload, verdict: dict, availability: dict,
                             rows: dict, missing_tickers: list[str], engine_state: str | None) -> dict:
    """Observation layer: one record per cycle, whatever the decision state.

    Fresh rows keep being counted; STALE, UNKNOWN, INVALID and missing rows
    are written down as missing data, never dropped. seq is contiguous, so a
    gap in the saved records is visible.
    """
    path = data_dir / "board_availability.jsonl"
    last = _last_jsonl_record(path)
    last_seq = _plain_int(last.get("seq")) if isinstance(last, dict) else None
    previous_at = parse_offset_timestamp(last.get("at")) if isinstance(last, dict) else None
    non_fresh = [{"ticker": r.get("ticker"), "state": r.get("state"), "reasons": r.get("reasons")}
                 for r in rows.get("row_verdicts") or [] if r.get("state") != FRESH]
    freshness = verdict.get("quote_freshness") if isinstance(verdict.get("quote_freshness"), dict) else {}
    record = {
        "record_class": "board_observation",
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "seq": (last_seq or 0) + 1,
        "previous_record_readable": last is None or last_seq is not None,
        "at": now.isoformat(timespec="seconds"),
        "seconds_since_previous": round((now - previous_at).total_seconds(), 3) if previous_at else None,
        "collector_updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "source_checks_pass": verdict.get("ok") is True,
        "source_reasons": sorted(set(r for r in verdict.get("reasons") or [] if r)),
        "identity_quote_state": freshness.get("state"),
        "identity_quote_at": freshness.get("quote_at"),
        "decision_available": availability.get("decision_available") is True,
        "availability_status": availability.get("availability_status"),
        "availability_reasons": availability.get("reasons"),
        "state_counts": availability.get("state_counts"),
        "fresh_coverage_pct": availability.get("fresh_coverage_pct"),
        "missing_count": availability.get("missing_count"),
        "missing_tickers": list(missing_tickers),
        "non_fresh_rows": non_fresh,
        # Observation PASS: source checks pass and every expected ticker is
        # accounted for (a row or a named missing ticker). Decision PASS:
        # source checks pass and the board is available for decisions.
        "decision_pass": verdict.get("ok") is True and availability.get("decision_available") is True,
        "observation_pass": verdict.get("ok") is True and isinstance(availability.get("universe_expected_count"), int)
        and len({r.get("ticker") for r in rows.get("row_verdicts") or []} | set(missing_tickers))
        >= availability.get("universe_expected_count"),
        "collector_missing_rows": _collector_missing_rows(payload),
        "shadow_fresh_only": shadow_fresh_only_evaluation(payload, rows, availability),
        "shadow_state": engine_state,
        "order_allowed": False,
        "real_submit_allowed": False,
    }
    _append_jsonl(path, record)
    return record


def _collector_missing_rows(payload) -> dict:
    """The Collector's own list of rows with no price (ticker and mapping only)."""
    items = payload.get("missing_rows") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {"published": False, "count": None, "sheet_code_mismatch": None}
    entries = [i for i in items if isinstance(i, dict)]
    return {"published": True, "count": len(entries),
            "sheet_code_mismatch": sum(1 for i in entries if i.get("sheet_code_matches") is not True)}


def freshness_verdicts_agree(*verdicts) -> bool:
    """Components agree when they reach the same state and the same fresh bit.

    They evaluate at slightly different instants (Shadow every 5 seconds,
    /health per request), so two FRESH verdicts may name different quotes.
    One component calling a quote fresh while another does not is a mismatch.
    """
    if len(verdicts) < 2:
        return False
    keys = set()
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            return False
        keys.add((verdict.get("state"), verdict.get("fresh") is True))
    return len(keys) == 1


def combined_freshness(*verdicts) -> tuple[bool, list[str]]:
    """Fresh only if every verdict is fresh and all of them agree."""
    reasons: list[str] = []
    if not freshness_verdicts_agree(*verdicts):
        reasons.append("FRESHNESS_VERDICT_MISMATCH")
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            reasons.append("FRESHNESS_VERDICT_MISSING")
            continue
        if verdict.get("fresh") is not True or verdict.get("state") != FRESH:
            reasons.extend(verdict.get("reasons") or ["FRESHNESS_NOT_FRESH"])
        if verdict.get("real_submit_allowed") is not False:
            reasons.append("REAL_SUBMIT_NOT_FALSE")
    unique = sorted(set(reasons))
    return (not unique, unique)


def assess_live_payload(payload, *, file_mtime: datetime | None, now: datetime, max_age_seconds: int = MAX_AGE_SECONDS,
                        previous_quote_at=None) -> dict:
    """Same fail-closed idea as the gateway/collector price gate.

    Unknown, stale, sample, conflicting, or non-canonical input is not tradable.
    A recent write (updated_at, mtime) is required but does not make the quote
    fresh: assess_quote_freshness must also pass. A passing verdict still
    forces real_submit_allowed false.
    """
    reasons: list[str] = []
    if now.tzinfo is None or now.utcoffset() is None:
        reasons.append("NOW_NOT_TIMEZONE_AWARE")
    if not isinstance(payload, dict):
        reasons.append("MISSING_PAYLOAD")
        return _verdict(reasons, assess_quote_freshness(payload, now=now))

    if payload.get("real_submit_allowed") is not False:
        reasons.append("REAL_SUBMIT_NOT_FALSE")
    if payload.get("live_values_available") is not True:
        reasons.append("LIVE_VALUES_UNAVAILABLE")
    status = payload.get("price_source_status")
    if status != "OK":
        if isinstance(status, str) and status and status != "OK":
            reasons.append(status)
        else:
            reasons.append("MISSING_PRICE_DIAGNOSTICS")
    if payload.get("source") != CANONICAL_SOURCE:
        reasons.append("CACHED_OR_SAMPLE_PAYLOAD")
    if payload.get("source_mode") != "MS2_RSS_WORKBOOK":
        reasons.append("WRONG_SOURCE_WORKBOOK")
    if payload.get("data_conflict") is True:
        reasons.append("DATA_CONFLICT")
    if payload.get("stale") is not False:
        reasons.append("STALE_OR_MISSING_TIMESTAMP")

    diag = payload.get("live_price_diagnostics")
    if not isinstance(diag, dict):
        reasons.append("MISSING_PRICE_DIAGNOSTICS")
    else:
        if diag.get("price_source_status") != "OK":
            reasons.append("MISSING_PRICE_DIAGNOSTICS")
        if diag.get("source_mode") != "MS2_RSS_WORKBOOK":
            reasons.append("WRONG_SOURCE_WORKBOOK")
        if diag.get("workbook_name") != CANONICAL_WORKBOOK:
            reasons.append("WRONG_SOURCE_WORKBOOK")
        if diag.get("data_conflict") is True:
            reasons.append("DATA_CONFLICT")
        if diag.get("duplicate_collector") is True:
            reasons.append("DUPLICATE_COLLECTOR")
        if diag.get("duplicate_watcher") is True:
            reasons.append("DUPLICATE_WATCHER")
        collector_count = diag.get("collector_count")
        if collector_count is None:
            reasons.append("COLLECTOR_PROCESS_UNVERIFIED")
        elif not isinstance(collector_count, int) or isinstance(collector_count, bool) or collector_count != 1:
            reasons.append("DUPLICATE_COLLECTOR" if isinstance(collector_count, int) and collector_count > 1 else "COLLECTOR_PROCESS_UNVERIFIED")
        watcher_count = diag.get("watcher_count")
        if watcher_count is None:
            reasons.append("DUPLICATE_PROCESS_CHECK_UNAVAILABLE")
        elif not isinstance(watcher_count, int) or isinstance(watcher_count, bool) or watcher_count < 0 or watcher_count > 1:
            reasons.append("DUPLICATE_WATCHER")
        if isinstance(diag.get("stale_reason"), str) and diag.get("stale_reason"):
            reasons.extend(part for part in str(diag.get("stale_reason")).split(",") if part)

    if not isinstance(payload.get("all_targets"), list):
        reasons.append("MISSING_BOARD")

    tz = now.tzinfo if now.tzinfo is not None and now.utcoffset() is not None else timezone.utc
    updated = parse_timestamp(payload.get("updated_at"), tz)
    if updated is None:
        reasons.append("STALE_OR_MISSING_TIMESTAMP")
    else:
        age = (now - updated).total_seconds()
        if age < 0 or age > max_age_seconds:
            reasons.append("STALE_OR_MISSING_TIMESTAMP")
    if file_mtime is None or file_mtime.tzinfo is None or file_mtime.utcoffset() is None:
        reasons.append("STALE_OR_MISSING_TIMESTAMP")
    else:
        mage = (now - file_mtime.astimezone(tz)).total_seconds()
        if mage < 0 or mage > max_age_seconds:
            reasons.append("STALE_OR_MISSING_TIMESTAMP")
    freshness = assess_quote_freshness(payload, now=now, previous_quote_at=previous_quote_at)
    if not freshness["fresh"]:
        reasons.extend(freshness["reasons"] or ["FRESHNESS_NOT_FRESH"])
        # The Collector's own stale flag said fresh while the quote is not:
        # the two judgements disagree, which is itself a fail-closed reason.
        if isinstance(payload, dict) and payload.get("stale") is False:
            reasons.append("FRESHNESS_VERDICT_MISMATCH")
    return _verdict(reasons, freshness)


def _verdict(reasons: list[str], freshness: dict | None = None) -> dict:
    unique = sorted(set(reasons))
    return {"ok": not unique, "reasons": unique, "real_submit_allowed": False, "quote_freshness": freshness}


def board_fingerprint(payload: dict) -> str:
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    compact = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                compact.append(None)
                continue
            compact.append({
                "ticker": row.get("ticker"),
                "signal": row.get("signal"),
                "strategy": row.get("strategy"),
                "price": row.get("price"),
                "entry_price": row.get("entry_price"),
                "stop_price": row.get("stop_price"),
                "target1": row.get("target1"),
                "target2": row.get("target2"),
                "source_timestamp": row.get("source_timestamp"),
                "data": row.get("data"),
            })
    encoded = json.dumps({
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "rows": compact,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _side_of(signal: str) -> str | None:
    if signal in LONG_ENTRY_SIGNALS:
        return "LONG"
    if signal in SHORT_ENTRY_SIGNALS:
        return "SHORT"
    return None


def _geometry_ok(side: str, entry, stop) -> bool:
    if not (_finite(entry) and _finite(stop) and entry > 0 and stop > 0):
        return False
    if side == "LONG":
        return stop < entry
    return stop > entry


def _row_price_ok(row: dict) -> bool:
    return _finite(row.get("price")) and row.get("price") > 0 and row.get("data") == "LIVE"


def entry_candidate(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    signal = row.get("signal")
    side = _side_of(signal) if isinstance(signal, str) else None
    if side is None or not _row_price_ok(row) or not _geometry_ok(side, row.get("entry_price"), row.get("stop_price")):
        return None
    ticker = row.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None
    return {
        "ticker": ticker,
        "side": side,
        "signal": signal,
        "strategy": row.get("strategy") if isinstance(row.get("strategy"), str) else "",
        "price": row.get("price"),
        "entry_price": row.get("entry_price"),
        "stop_price": row.get("stop_price"),
        "target1": row.get("target1") if _finite(row.get("target1")) else None,
        "target2": row.get("target2") if _finite(row.get("target2")) else None,
        "source_timestamp": row.get("source_timestamp"),
    }


def position_key(ticker: str, side: str) -> str:
    return ticker + "|" + side


def _entry_board_conflict(payload) -> bool:
    """Two rows for one ticker are not one observation.

    That includes two entry rows, both sides, or an entry row beside a
    non-entry row. The payload-level data_conflict flag can still be false.
    Any of these shapes is unverified, so the cycle must not open or close.
    """
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return False
    seen_tickers: set[str] = set()
    seen_keys: set[str] = set()
    sides: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker")
        if isinstance(ticker, str) and ticker:
            if ticker in seen_tickers:
                return True
            seen_tickers.add(ticker)
        candidate = entry_candidate(row)
        if candidate is None:
            continue
        key = position_key(candidate["ticker"], candidate["side"])
        if key in seen_keys:
            return True
        seen_keys.add(key)
        held = sides.setdefault(candidate["ticker"], set())
        held.add(candidate["side"])
        if len(held) > 1:
            return True
    return False


def _rationale(row_like: dict) -> str:
    parts = [str(row_like.get("signal") or ""), str(row_like.get("strategy") or "")]
    parts.append("entry " + str(row_like.get("entry_price")))
    parts.append("stop " + str(row_like.get("stop_price")))
    if row_like.get("target1") is not None:
        parts.append("target1 " + str(row_like.get("target1")))
    parts.append("price " + str(row_like.get("price")))
    if row_like.get("source_timestamp"):
        parts.append("source_timestamp " + str(row_like.get("source_timestamp")))
    return " / ".join(p for p in parts if p)


def _pnl_per_share(side: str, entry, exit_price):
    if not (_finite(entry) and _finite(exit_price)):
        return None
    if side == "LONG":
        return exit_price - entry
    if side == "SHORT":
        return entry - exit_price
    return None


def _r_multiple(side: str, entry, stop, exit_price):
    pnl = _pnl_per_share(side, entry, exit_price)
    if pnl is None or not _finite(stop) or not _finite(entry) or entry == stop:
        return None
    risk = abs(entry - stop)
    if risk == 0:
        return None
    return pnl / risk


def count_invalidated_entries(payload) -> int:
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return 0
    count = 0
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("signal"), str) and row.get("signal") in ENTRY_SIGNALS:
            count += 1
    return count


def fresh_state(*, now: datetime) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "STOPPED",
        "reason": "",
        "resume_blocked": False,
        "block_reason": "",
        "last_seq": 0,
        "seen_board_fingerprints": [],
        "open_incident_id": None,
        "engine_started_at": now.isoformat(),
        "real_submit_allowed": False,
        "pid": os.getpid(),
    }


def _read_jsonl(path: Path) -> tuple[list[dict] | None, str]:
    if not path.exists():
        return [], ""
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, "LEDGER_UNREADABLE"
    if text == "":
        return [], ""
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return None, "LEDGER_CORRUPT"
        if not isinstance(item, dict):
            return None, "LEDGER_CORRUPT"
        rows.append(item)
    return rows, ""


def replay_ledger(events: list[dict]) -> tuple[dict, str]:
    open_positions: dict[str, dict] = {}
    for index, event in enumerate(events, start=1):
        if event.get("seq") != index or event.get("real_submit_allowed") is not False or event.get("quantity") is not None:
            return {}, "LEDGER_CORRUPT"
        kind = event.get("record_class")
        if kind != "shadow_observation":
            return {}, "LEDGER_CORRUPT"
        event_type = event.get("event_type")
        if event_type == "board_judgment":
            continue
        if event_type == "virtual_entry":
            key = event.get("position_key")
            if not isinstance(key, str) or key in open_positions:
                return {}, "LEDGER_CORRUPT"
            open_positions[key] = event
            continue
        if event_type == "virtual_exit":
            key = event.get("position_key")
            if not isinstance(key, str) or key not in open_positions:
                return {}, "LEDGER_CORRUPT"
            del open_positions[key]
            continue
        return {}, "LEDGER_CORRUPT"
    return open_positions, ""


def _operations_incidents_only(incidents: list[dict] | None) -> bool:
    """A diary of operations incidents is not a shadow trade ledger.

    Missing trade state still blocks when any observation ledger exists.
    Incident rows alone must be readable operations records, or the engine
    stays fail-closed.
    """
    if not incidents:
        return False
    for item in incidents:
        if not isinstance(item, dict) or item.get("record_class") != "operations_incident":
            return False
        if item.get("real_submit_allowed") is not False or item.get("fail_closed") is not True:
            return False
    return True


def load_engine(data_dir: Path, *, now: datetime) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / "state.json"
    ledger_path = data_dir / "ledger.jsonl"
    incident_path = data_dir / "incidents.jsonl"
    state = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {"resume_blocked": True, "block_reason": "STATE_UNREADABLE", "last_seq": -1}
        if not isinstance(state, dict):
            state = {"resume_blocked": True, "block_reason": "STATE_UNREADABLE", "last_seq": -1}
    ledger, ledger_error = _read_jsonl(ledger_path)
    incidents, incident_error = _read_jsonl(incident_path)
    engine = {
        "state": fresh_state(now=now) if state is None and not ledger_path.exists() and not incident_path.exists() else (state or fresh_state(now=now)),
        "ledger": ledger or [],
        "incidents": incidents or [],
        "open_positions": {},
        "clean_boot": state is None and not ledger_path.exists() and not incident_path.exists(),
        "incident_history_only": False,
    }
    engine["state"]["real_submit_allowed"] = False
    if ledger_error or incident_error:
        _block(engine, ledger_error or incident_error)
        return engine
    if incidents and not _operations_incidents_only(incidents):
        _block(engine, "INCIDENT_LOG_UNSAFE")
        return engine
    if state is None and ledger_path.exists():
        _block(engine, "STATE_MISSING")
        return engine
    if state is None and incident_path.exists():
        if not _operations_incidents_only(incidents):
            _block(engine, "STATE_MISSING")
            return engine
        engine["incident_history_only"] = True
        engine["state"] = fresh_state(now=now)
        engine["state"]["real_submit_allowed"] = False
        engine["incidents"] = incidents or []
    recorded_seq = _plain_int(state.get("last_seq")) if isinstance(state, dict) else None
    if state is not None and not ledger_path.exists() and recorded_seq is not None and recorded_seq > 0:
        _block(engine, "LEDGER_MISSING")
        return engine
    if state is not None and not incident_path.exists() and state.get("open_incident_id"):
        _block(engine, "INCIDENT_LOG_MISSING")
        return engine
    if ledger is None:
        _block(engine, "LEDGER_MISSING")
        return engine
    open_positions, replay_error = replay_ledger(ledger)
    if replay_error:
        _block(engine, replay_error)
        return engine
    if engine["state"].get("resume_blocked") is True:
        engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
        engine["state"]["reason"] = engine["state"].get("block_reason") or engine["state"].get("reason") or "UNKNOWN_STATE"
        engine["state"]["real_submit_allowed"] = False
        engine["open_positions"] = {}
        return engine
    last_seq = _plain_int(engine["state"].get("last_seq"))
    if last_seq is None or last_seq != len(ledger):
        _block(engine, "LEDGER_STATE_MISMATCH")
        return engine
    engine["open_positions"] = open_positions
    previous = engine["state"].get("state")
    if previous not in STATES:
        _block(engine, "UNKNOWN_STATE")
        return engine
    if not engine["clean_boot"]:
        engine["state"]["state"] = "RECOVERING"
        engine["state"]["reason"] = "PROCESS_RESTART"
    return engine


def _block(engine: dict, reason: str) -> None:
    engine["state"]["resume_blocked"] = True
    engine["state"]["block_reason"] = reason
    engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
    engine["state"]["reason"] = reason
    engine["state"]["real_submit_allowed"] = False
    engine["open_positions"] = {}


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _primary_reason(reasons: list[str]) -> str:
    if not reasons:
        return "UNKNOWN"
    # The identity ticker has not traded yet: the Collector also reports
    # PRICE_SOURCE_MISMATCH for it, so name the specific cause. A real symbol
    # mismatch elsewhere on the board still takes precedence.
    if "IDENTITY_UNTRADED" in reasons:
        return "WRONG_SYMBOL_MAPPING" if "WRONG_SYMBOL_MAPPING" in reasons else "IDENTITY_UNTRADED"
    preferred = (
        "PRICE_SOURCE_MISMATCH", "DATA_CONFLICT", "STALE_OR_MISSING_TIMESTAMP",
        "FRESHNESS_VERDICT_MISMATCH", "STALE_SOURCE_QUOTE", "SOURCE_DATE_UNKNOWN",
        "SOURCE_TIMESTAMP_MISSING", "SOURCE_TIMESTAMP_IN_FUTURE", "SOURCE_TIMESTAMP_REGRESSION",
        "MIXED_SOURCE_DATES",
        "CACHED_OR_SAMPLE_PAYLOAD", "WRONG_SOURCE_WORKBOOK", "WRONG_SYMBOL_MAPPING",
        "DUPLICATE_COLLECTOR", "DUPLICATE_WATCHER", "LIVE_VALUES_UNAVAILABLE",
        "MISSING_PAYLOAD", "REAL_SUBMIT_NOT_FALSE",
    )
    for code in preferred:
        if code in reasons:
            return code
    return reasons[0]


FRESHNESS_REASONS = frozenset({
    "STALE_SOURCE_QUOTE", "SOURCE_DATE_UNKNOWN", "SOURCE_TIMESTAMP_MISSING", "SOURCE_TIMESTAMP_UNPARSEABLE",
    "SOURCE_TIMESTAMP_NO_OFFSET", "SOURCE_DATE_BASIS_UNVERIFIED", "SOURCE_TIMESTAMP_INCONSISTENT",
    "SOURCE_TIMESTAMP_IN_FUTURE", "SOURCE_OBSERVATION_MISSING", "SOURCE_OBSERVATION_IN_FUTURE",
    "SOURCE_TIMESTAMP_AFTER_OBSERVATION", "SOURCE_TIMESTAMP_REGRESSION", "MIXED_SOURCE_DATES",
    "FRESHNESS_VERDICT_MISMATCH", "FRESHNESS_NOT_FRESH",
})


def _component_for(reason: str) -> str:
    if reason in {"DUPLICATE_COLLECTOR", "COLLECTOR_PROCESS_UNVERIFIED"}:
        return "collector"
    if reason == "DUPLICATE_WATCHER":
        return "watcher"
    if reason in {"STALE_OR_MISSING_TIMESTAMP", "MISSING_PAYLOAD", "INSUFFICIENT_COVERAGE"} or reason in FRESHNESS_REASONS:
        return "live_ms2"
    if reason in {"PRICE_SOURCE_MISMATCH", "WRONG_SOURCE_WORKBOOK", "WRONG_SYMBOL_MAPPING", "IDENTITY_UNTRADED", "EXCEL_COM_BUSY", "EXCEL_COM_READ_FAILED", "CACHED_OR_SAMPLE_PAYLOAD", "DATA_CONFLICT"}:
        return "price_source"
    return "ai_shadow"


def _open_incident(engine: dict, data_dir: Path, *, now: datetime, reasons: list[str], invalidated: int) -> None:
    if engine["state"].get("open_incident_id"):
        for incident in engine["incidents"]:
            if incident.get("incident_id") == engine["state"]["open_incident_id"] and incident.get("recovery_at") is None:
                incident["invalidated_signal_count"] = int(incident.get("invalidated_signal_count") or 0) + invalidated
                incident["symptom"] = ",".join(reasons)
                _rewrite_incidents(data_dir, engine["incidents"])
                return
    reason = _primary_reason(reasons)
    recurrence_key = _component_for(reason) + "|" + reason
    prior = sum(1 for item in engine["incidents"] if item.get("recurrence_key") == recurrence_key)
    incident = {
        "record_class": "operations_incident",
        "incident_id": "inc-" + hashlib.sha256((now.isoformat() + "|" + recurrence_key).encode("utf-8")).hexdigest()[:16],
        "occurrence_at": now.isoformat(),
        "recovery_at": None,
        "duration_seconds": None,
        "component": _component_for(reason),
        "error_code": reason,
        "symptom": ",".join(reasons),
        "suspected_cause": reason,
        "confirmed_cause": None,
        "impact_scope": "ai_shadow_observations",
        "real_trade_impact": "NONE_REAL_SUBMIT_REMAINS_FALSE",
        "shadow_impact": "PAUSED_FAIL_CLOSED",
        "fail_closed": True,
        "invalidated_signal_count": invalidated,
        "recovery_mode": None,
        "actions": ["new shadow signals invalidated", "virtual entry and exit suspended"],
        "recurrence_key": recurrence_key,
        "recurrence_count": prior + 1,
        "log_refs": ["ledger.jsonl", "incidents.jsonl", "live_ms2.json"],
        "real_submit_allowed": False,
    }
    engine["incidents"].append(incident)
    engine["state"]["open_incident_id"] = incident["incident_id"]
    _append_jsonl(data_dir / "incidents.jsonl", incident)


def _rewrite_incidents(data_dir: Path, incidents: list[dict]) -> None:
    path = data_dir / "incidents.jsonl"
    temporary = path.with_suffix(".jsonl.tmp")
    body = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for item in incidents)
    temporary.write_text(body, encoding="utf-8")
    os.replace(temporary, path)


def _close_incident(engine: dict, data_dir: Path, *, now: datetime, recovery_mode: str) -> None:
    incident_id = engine["state"].get("open_incident_id")
    if not incident_id:
        return
    for incident in engine["incidents"]:
        if incident.get("incident_id") != incident_id or incident.get("recovery_at"):
            continue
        started = parse_timestamp(incident.get("occurrence_at"), now.tzinfo)
        incident["recovery_at"] = now.isoformat()
        incident["duration_seconds"] = None if started is None else max(0, int((now - started).total_seconds()))
        incident["recovery_mode"] = recovery_mode
        incident["shadow_impact"] = "AUTO_RESUMED" if recovery_mode == "AUTO" else "MANUAL_RESUMED"
        incident["actions"] = list(incident.get("actions") or []) + ["safety check PASS", "AI SHADOW resumed without duplicating open observations"]
        incident["confirmed_cause"] = None
        break
    engine["state"]["open_incident_id"] = None
    _rewrite_incidents(data_dir, engine["incidents"])


def _next_event(engine: dict, *, now: datetime, event_type: str, payload: dict) -> dict:
    engine["state"]["last_seq"] = int(engine["state"].get("last_seq") or 0) + 1
    record = {
        "record_class": "shadow_observation",
        "schema_version": SCHEMA_VERSION,
        "seq": engine["state"]["last_seq"],
        "event_type": event_type,
        "at": now.isoformat(),
        "real_submit_allowed": False,
        "pricing": "collector_published_price_not_fill_model",
    }
    record.update(payload)
    record["real_submit_allowed"] = False
    record["quantity"] = None
    return record


def _contaminated(engine: dict, opened_at: str, now: datetime) -> bool:
    opened = parse_timestamp(opened_at, now.tzinfo)
    if opened is None:
        return True
    for incident in engine["incidents"]:
        start = parse_timestamp(incident.get("occurrence_at"), now.tzinfo)
        if start is None:
            return True
        end = parse_timestamp(incident.get("recovery_at"), now.tzinfo) if incident.get("recovery_at") else now
        if end is None:
            return True
        if start < now and end > opened:
            return True
    return False


_EXCEL_OPEN_COMPONENTS = frozenset({"excel_identity", "workbook_open", "excel_process_exit"})


def unresolved_excel_open_incident(engine: dict) -> dict | None:
    """The workbook open is unverified while one of these incidents is unresolved.

    The controller writes them into the same incidents log. A later payload
    that looks fresh must not open or close a virtual observation, and must
    not set recovery_at. real_submit_allowed stays false.
    """
    found = None
    for incident in engine.get("incidents") or []:
        if not isinstance(incident, dict):
            continue
        if incident.get("recovery_at"):
            continue
        if incident.get("component") not in _EXCEL_OPEN_COMPONENTS:
            continue
        found = incident
    return found


def apply_cycle(engine: dict, payload, verdict: dict, *, now: datetime, data_dir: Path, recovery_mode: str = "AUTO",
                availability: dict | None = None) -> dict:
    """One supervisor cycle. Fail-closed input never creates or closes a virtual trade.

    A board that passes the source checks but is not decision-available
    (identity quote, any row, or the 100-symbol universe not fresh and
    complete) is observed and judged, but opens and closes nothing: signals,
    market state and rankings were computed over every row.
    """
    engine["state"]["real_submit_allowed"] = False
    if engine["state"].get("resume_blocked") is True:
        engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
        engine["state"]["reason"] = engine["state"].get("block_reason") or "UNKNOWN_STATE"
        _persist(engine, data_dir)
        return engine
    if unresolved_excel_open_incident(engine) is not None:
        engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
        engine["state"]["reason"] = "EXCEL_OPEN_UNVERIFIED"
        engine["state"]["real_submit_allowed"] = False
        _persist(engine, data_dir)
        return engine
    if recovery_mode == "UNREADABLE":
        engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
        engine["state"]["reason"] = "RECOVERY_FILE_UNREADABLE"
        engine["state"]["real_submit_allowed"] = False
        if not engine["state"].get("open_incident_id"):
            _open_incident(engine, data_dir, now=now, reasons=["RECOVERY_FILE_UNREADABLE"], invalidated=0)
        _persist(engine, data_dir)
        return engine
    if verdict.get("ok") and _entry_board_conflict(payload):
        verdict = {"ok": False, "reasons": ["DATA_CONFLICT"], "real_submit_allowed": False}

    fingerprint = board_fingerprint(payload) if isinstance(payload, dict) else "missing-payload"
    seen = set(engine["state"].get("seen_board_fingerprints") or [])

    if not verdict.get("ok"):
        engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
        engine["state"]["reason"] = _primary_reason(list(verdict.get("reasons") or ["UNKNOWN"]))
        if fingerprint not in seen:
            invalidated = count_invalidated_entries(payload)
            _open_incident(engine, data_dir, now=now, reasons=list(verdict.get("reasons") or ["UNKNOWN"]), invalidated=invalidated)
            seen.add(fingerprint)
            engine["state"]["seen_board_fingerprints"] = sorted(seen)
        _persist(engine, data_dir)
        return engine

    if engine["state"].get("state") in {"PAUSED_FAIL_CLOSED", "STOPPED", "RECOVERING"}:
        mode = recovery_mode if engine["state"].get("state") == "PAUSED_FAIL_CLOSED" and engine["state"].get("open_incident_id") else "AUTO"
        if engine["state"].get("open_incident_id"):
            _close_incident(engine, data_dir, now=now, recovery_mode=mode)
        engine["state"]["state"] = "RECOVERING"
        engine["state"]["reason"] = "SAFETY_CHECK_PASS"

    if fingerprint in seen:
        engine["state"]["state"] = "RUNNING"
        engine["state"]["reason"] = ""
        _persist(engine, data_dir)
        return engine

    rows = payload.get("all_targets") if isinstance(payload, dict) else []
    decision_available = isinstance(availability, dict) and availability.get("decision_available") is True
    decision_reasons = [] if decision_available else list(
        (availability or {}).get("reasons") or ["BOARD_AVAILABILITY_MISSING"])
    board_freshness = verdict.get("quote_freshness") if isinstance(verdict.get("quote_freshness"), dict) else {}
    board_quote_at = board_freshness.get("quote_at") if board_freshness.get("fresh") is True else None
    row_fresh: dict[str, dict] = {}
    by_key = {}
    judgments = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = row.get("ticker") if isinstance(row.get("ticker"), str) else ""
        row_verdict = row_quote_freshness(row, now=now, board_quote_at=board_quote_at)
        if ticker:
            row_fresh[ticker] = row_verdict
        candidate = entry_candidate(row)
        # A virtual entry needs this row's own fresh quote, not just a fresh board.
        if candidate is not None and row_verdict.get("fresh") is not True:
            candidate = None
        # ...and a board whose every row is fresh and complete.
        if candidate is not None and not decision_available:
            candidate = None
        if candidate is not None:
            candidate["source_timestamp_at"] = row_verdict.get("quote_at")
            by_key[position_key(candidate["ticker"], candidate["side"])] = candidate
        judgments.append({
            "ticker": ticker,
            "signal": row.get("signal"),
            "strategy": row.get("strategy") if isinstance(row.get("strategy"), str) else "",
            "entry_candidate": candidate is not None,
            "row_quote_state": row_verdict.get("state"),
        })

    exits = []
    for key, position in list(engine["open_positions"].items() if decision_available else []):
        ticker, side = key.split("|", 1)
        current = None
        for row in rows:
            if isinstance(row, dict) and row.get("ticker") == ticker:
                current = row
                break
        if current is None or not _row_price_ok(current):
            continue
        # An exit price from an undated, old, future or other-day quote is
        # not marked; the observation stays open until a fresh quote arrives.
        if (row_fresh.get(ticker) or {}).get("fresh") is not True:
            continue
        still_same_side = _side_of(current.get("signal")) == side if isinstance(current.get("signal"), str) else False
        if still_same_side:
            continue
        exit_price = current.get("price")
        opened_at = position.get("at")
        bucket = "contaminated_by_data_outage" if _contaminated(engine, opened_at, now) else "clean_strategy"
        event = _next_event(engine, now=now, event_type="virtual_exit", payload={
            "position_key": key,
            "ticker": ticker,
            "side": side,
            "strategy": position.get("strategy") or "",
            "signal": current.get("signal"),
            "entry_price": position.get("entry_price"),
            "exit_price": exit_price,
            "pnl_per_share_yen": _pnl_per_share(side, position.get("entry_price"), exit_price),
            "r_multiple": _r_multiple(side, position.get("entry_price"), position.get("stop_price"), exit_price),
            "quantity": None,
            "performance_bucket": bucket,
            "exit_reason": "collector_signal_left_entry_set",
            "decision_rationale": _rationale({
                "signal": current.get("signal"),
                "strategy": current.get("strategy"),
                "entry_price": position.get("entry_price"),
                "stop_price": position.get("stop_price"),
                "price": exit_price,
                "source_timestamp": current.get("source_timestamp"),
            }),
            "related_entry_seq": position.get("seq"),
        })
        engine["ledger"].append(event)
        _append_jsonl(data_dir / "ledger.jsonl", event)
        del engine["open_positions"][key]
        exits.append(event["seq"])

    entries = []
    for key, candidate in by_key.items():
        if key in engine["open_positions"]:
            continue
        event = _next_event(engine, now=now, event_type="virtual_entry", payload={
            "position_key": key,
            "ticker": candidate["ticker"],
            "side": candidate["side"],
            "strategy": candidate["strategy"],
            "signal": candidate["signal"],
            "entry_price": candidate["entry_price"],
            "stop_price": candidate["stop_price"],
            "target1": candidate["target1"],
            "target2": candidate["target2"],
            "published_price": candidate["price"],
            "source_timestamp": candidate["source_timestamp"],
            "source_timestamp_at": candidate.get("source_timestamp_at"),
            "quantity": None,
            "performance_bucket": "open_unrealized_not_marked",
            "decision_rationale": _rationale(candidate),
        })
        engine["ledger"].append(event)
        _append_jsonl(data_dir / "ledger.jsonl", event)
        engine["open_positions"][key] = event
        entries.append(event["seq"])

    judgment = _next_event(engine, now=now, event_type="board_judgment", payload={
        "board_fingerprint": fingerprint,
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "entry_seqs": entries,
        "exit_seqs": exits,
        "judgments": judgments,
        "decision_available": decision_available,
        "decision_block_reasons": decision_reasons,
    })
    engine["ledger"].append(judgment)
    _append_jsonl(data_dir / "ledger.jsonl", judgment)
    seen.add(fingerprint)
    engine["state"]["seen_board_fingerprints"] = sorted(seen)
    engine["state"]["state"] = "RUNNING"
    engine["state"]["reason"] = ""
    _persist(engine, data_dir)
    return engine


def _persist(engine: dict, data_dir: Path) -> None:
    engine["state"]["real_submit_allowed"] = False
    engine["state"]["pid"] = os.getpid()
    _write_json(data_dir / "state.json", engine["state"])


def _plain_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


DOWNTIME_COUNT_FROM = clock_time(9, 0)
DOWNTIME_COUNT_UNTIL = clock_time(15, 30)


def counted_seconds(left: datetime, right: datetime) -> int:
    """Seconds of [left, right] that count toward downtime and uptime (JST).

    OWNER 2026-10-22 ④ (D-035): time after 15:30 is not counted as downtime.
    OWNER 2026-10-23: nor is the time before 09:00 (pre-open quotes are never fresh, so the
    Shadow is paused fail-closed every morning). The lunch break still counts. The
    incident log itself is unchanged.
    """
    if right <= left:
        return 0
    lo, hi = left.astimezone(JST), right.astimezone(JST)
    total = 0.0
    day = lo.date()
    while day <= hi.date():
        a = max(lo, datetime.combine(day, DOWNTIME_COUNT_FROM, JST))
        b = min(hi, datetime.combine(day, DOWNTIME_COUNT_UNTIL, JST))
        if b > a:
            total += (b - a).total_seconds()
        day += timedelta(days=1)
    return int(total)


def _clip_duration(incident: dict, start: datetime, end: datetime) -> int:
    opened = parse_timestamp(incident.get("occurrence_at"), start.tzinfo)
    if opened is None:
        return 0
    closed = parse_timestamp(incident.get("recovery_at"), start.tzinfo) if incident.get("recovery_at") else end
    if closed is None:
        return 0
    left = max(opened, start)
    right = min(closed, end)
    return counted_seconds(left, right)


def summarize_operations(engine: dict, *, now: datetime) -> dict:
    started = parse_timestamp(engine["state"].get("engine_started_at"), now.tzinfo)
    trades = [event for event in engine["ledger"] if event.get("event_type") == "virtual_exit"]

    def window(label: str, seconds: int) -> dict:
        if started is None:
            return _empty_window(label)
        begin = max(started, now - timedelta(seconds=seconds))
        elapsed = counted_seconds(begin, now)
        incidents = [item for item in engine["incidents"] if parse_timestamp(item.get("occurrence_at"), now.tzinfo) and parse_timestamp(item.get("occurrence_at"), now.tzinfo) >= begin]
        downtime = sum(_clip_duration(item, begin, now) for item in engine["incidents"])
        recovered = [item for item in incidents if item.get("recovery_at")]
        durations = []
        for item in recovered:
            parsed = _plain_int(item.get("duration_seconds"))
            if parsed is not None:
                durations.append(parsed)
        freshness = sum(1 for item in incidents if item.get("error_code") in {"STALE_OR_MISSING_TIMESTAMP", "INSUFFICIENT_COVERAGE", "MISSING_PAYLOAD"})
        mismatches = sum(1 for item in incidents if item.get("error_code") in {"PRICE_SOURCE_MISMATCH", "WRONG_SOURCE_WORKBOOK", "WRONG_SYMBOL_MAPPING", "DATA_CONFLICT", "CACHED_OR_SAMPLE_PAYLOAD"})
        auto_count = sum(1 for item in recovered if item.get("recovery_mode") == "AUTO")
        manual_count = sum(1 for item in recovered if item.get("recovery_mode") == "MANUAL")
        in_window_trades = []
        for trade in trades:
            at = parse_timestamp(trade.get("at"), now.tzinfo)
            if at is not None and begin <= at <= now:
                in_window_trades.append(trade)
        clean = [trade for trade in in_window_trades if trade.get("performance_bucket") == "clean_strategy"]
        dirty = [trade for trade in in_window_trades if trade.get("performance_bucket") == "contaminated_by_data_outage"]
        uptime = None if elapsed <= 0 else max(0.0, min(1.0, (elapsed - downtime) / elapsed))
        mttr = None if not durations else sum(durations) / len(durations)
        recurrence = {}
        for item in incidents:
            key = item.get("recurrence_key") or ""
            count = _plain_int(item.get("recurrence_count"))
            recurrence[key] = max(0 if count is None else count, recurrence.get(key, 0))
        return {
            "label": label,
            "error_count": len(incidents),
            "total_downtime_seconds": downtime,
            "shadow_uptime_ratio": uptime,
            "freshness_anomaly_count": freshness,
            "price_mismatch_count": mismatches,
            "auto_recovery_count": auto_count,
            "manual_response_count": manual_count,
            "mttr_seconds": mttr,
            "recurrence": recurrence,
            "clean_strategy_pnl_per_share_yen": _sum_pnl(clean),
            "contaminated_pnl_per_share_yen": _sum_pnl(dirty),
            "clean_strategy_exit_count": len(clean),
            "contaminated_exit_count": len(dirty),
        }

    return {
        "daily": window("daily", 86400),
        "weekly": window("weekly", 7 * 86400),
        "monthly": window("monthly", 31 * 86400),
    }


def _empty_window(label: str) -> dict:
    return {
        "label": label,
        "error_count": None,
        "total_downtime_seconds": None,
        "shadow_uptime_ratio": None,
        "freshness_anomaly_count": None,
        "price_mismatch_count": None,
        "auto_recovery_count": None,
        "manual_response_count": None,
        "mttr_seconds": None,
        "recurrence": {},
        "clean_strategy_pnl_per_share_yen": None,
        "contaminated_pnl_per_share_yen": None,
        "clean_strategy_exit_count": None,
        "contaminated_exit_count": None,
    }


def _sum_pnl(trades: list[dict]):
    total = 0.0
    seen = False
    for trade in trades:
        value = trade.get("pnl_per_share_yen")
        if _finite(value):
            total += value
            seen = True
    return total if seen else None


def status_snapshot(engine: dict, *, now: datetime) -> dict:
    ops = summarize_operations(engine, now=now)
    latest = None
    for incident in reversed(engine["incidents"]):
        latest = {
            "incident_id": incident.get("incident_id"),
            "occurrence_at": incident.get("occurrence_at"),
            "recovery_at": incident.get("recovery_at"),
            "duration_seconds": incident.get("duration_seconds"),
            "component": incident.get("component"),
            "error_code": incident.get("error_code"),
            "symptom": incident.get("symptom"),
            "suspected_cause": incident.get("suspected_cause"),
            "confirmed_cause": incident.get("confirmed_cause"),
            "shadow_impact": incident.get("shadow_impact"),
            "fail_closed": incident.get("fail_closed"),
            "invalidated_signal_count": incident.get("invalidated_signal_count"),
            "recovery_mode": incident.get("recovery_mode"),
            "recurrence_count": incident.get("recurrence_count"),
            "real_trade_impact": incident.get("real_trade_impact"),
        }
        break
    return {
        "schema_version": SCHEMA_VERSION,
        "state": engine["state"].get("state"),
        "reason": engine["state"].get("reason") or engine["state"].get("block_reason") or "",
        "updated_at": now.isoformat(),
        "real_submit_allowed": False,
        "ui_independent": True,
        "open_observation_count": len(engine["open_positions"]),
        "resume_blocked": engine["state"].get("resume_blocked") is True,
        "engine_pid": os.getpid(),
        "quote_freshness": engine.get("quote_freshness"),
        "board_availability": engine.get("board_availability"),
        "decision_state": "DECISION_AVAILABLE" if (engine.get("board_availability") or {}).get("decision_available") is True
        else "DECISION_BLOCKED",
        "latest_incident": latest,
        "ops": ops,
    }


def publish_status(engine: dict, status_path: Path, *, now: datetime) -> None:
    _write_json(status_path, status_snapshot(engine, now=now))


def pid_alive(pid: int) -> bool | None:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        if getattr(error, "winerror", None) == 87:
            return False
        if getattr(error, "errno", None) in {1, 3}:
            return True if error.errno == 1 else None
        return None
    else:
        return True


def _exclusive_lock(lock_path: Path, payload: dict) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(lock_path, flags)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def acquire_singleton(lock_path: Path, *, pid: int, now: datetime, alive=pid_alive, stale_seconds: int = STATUS_STALE_SECONDS) -> str:
    """Return ACQUIRED, ALREADY_RUNNING, or REFUSED_LOCK_UNKNOWN.

    A second live process must not trade. An unknown lock is not treated as free.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": pid, "heartbeat_at": now.isoformat(), "script": "ai_shadow_supervisor.py", "real_submit_allowed": False}
    if not lock_path.exists():
        return "ACQUIRED" if _exclusive_lock(lock_path, payload) else "REFUSED_LOCK_UNKNOWN"
    try:
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "REFUSED_LOCK_UNKNOWN"
    if not isinstance(existing, dict):
        return "REFUSED_LOCK_UNKNOWN"
    owner = existing.get("pid")
    state = alive(owner) if isinstance(owner, int) and not isinstance(owner, bool) else False
    if state is None:
        return "REFUSED_LOCK_UNKNOWN"
    if state is True and owner == pid:
        _write_json(lock_path, payload)
        return "ACQUIRED"
    if state is True:
        heartbeat = parse_timestamp(existing.get("heartbeat_at"), now.tzinfo)
        fresh = heartbeat is not None and abs((now - heartbeat).total_seconds()) <= stale_seconds
        if fresh:
            return "ALREADY_RUNNING"
        return "REFUSED_LOCK_UNKNOWN"
    try:
        lock_path.unlink()
    except OSError:
        return "REFUSED_LOCK_UNKNOWN"
    return "ACQUIRED" if _exclusive_lock(lock_path, payload) else "ALREADY_RUNNING"


def touch_lock(lock_path: Path, *, pid: int, now: datetime) -> None:
    _write_json(lock_path, {"pid": pid, "heartbeat_at": now.isoformat(), "script": "ai_shadow_supervisor.py", "real_submit_allowed": False})


def read_manual_recovery(data_dir: Path) -> str:
    path = data_dir / "manual_recovery.json"
    if not path.exists():
        return "AUTO"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNREADABLE"
    if not isinstance(payload, dict):
        return "UNREADABLE"
    action = payload.get("action")
    if action == "acknowledge":
        return "MANUAL"
    if action in (None, "auto"):
        return "AUTO"
    return "UNREADABLE"


def run_once(data_dir: Path, live_path: Path, status_path: Path, *, now: datetime | None = None) -> dict:
    moment = (now or now_jst()).astimezone(JST)
    engine = load_engine(data_dir, now=moment)
    payload = None
    file_mtime = None
    if live_path.exists():
        try:
            payload = json.loads(live_path.read_text(encoding="utf-8"))
            file_mtime = datetime.fromtimestamp(live_path.stat().st_mtime, tz=timezone.utc).astimezone(JST)
        except (OSError, json.JSONDecodeError, ValueError):
            payload = None
            file_mtime = None
    previous_quote_at = engine["state"].get("last_fresh_quote_at")
    verdict = assess_live_payload(payload, file_mtime=file_mtime, now=moment, previous_quote_at=previous_quote_at)
    freshness = verdict.get("quote_freshness")
    engine["quote_freshness"] = freshness
    if verdict.get("ok") and isinstance(freshness, dict) and freshness.get("fresh") is True:
        # Only a quote accepted as fresh moves the regression floor forward.
        engine["state"]["last_fresh_quote_at"] = freshness.get("quote_at")
    # Same gate as the Gateway's /health: rows judged against the identity
    # quote date, universe from the watchlist beside live_ms2.json.
    board_quote_at = freshness.get("quote_at") if isinstance(freshness, dict) else None
    rows = board_row_freshness(payload, now=moment, board_quote_at=board_quote_at)
    universe = load_expected_universe(live_path.parent)
    availability = assess_board_availability(payload, freshness, rows, universe)
    engine["board_availability"] = availability
    apply_cycle(engine, payload, verdict, now=moment, data_dir=data_dir, recovery_mode=read_manual_recovery(data_dir),
                availability=availability)
    present = {r.get("ticker") for r in rows.get("row_verdicts") or []}
    missing = [t for t in universe.get("tickers") or [] if t not in present]
    record_board_observation(data_dir, now=moment, payload=payload, verdict=verdict, availability=availability,
                             rows=rows, missing_tickers=missing, engine_state=engine["state"].get("state"))
    publish_status(engine, status_path, now=moment)
    return engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI SHADOW background supervisor")
    parser.add_argument("--live", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)
    live_path = Path(args.live)
    status_path = Path(args.status)
    lock_path = data_dir / "supervisor.lock.json"
    now = now_jst()
    lock = acquire_singleton(lock_path, pid=os.getpid(), now=now)
    if lock == "ALREADY_RUNNING":
        print("ALREADY_RUNNING")
        return 0
    if lock != "ACQUIRED":
        print("REFUSED_LOCK_UNKNOWN")
        return 2
    try:
        if args.once:
            run_once(data_dir, live_path, status_path, now=now)
            return 0
        while True:
            moment = now_jst()
            touch_lock(lock_path, pid=os.getpid(), now=moment)
            run_once(data_dir, live_path, status_path, now=moment)
            time.sleep(max(1.0, args.interval))
    finally:
        if lock_path.exists():
            try:
                current = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = None
            if isinstance(current, dict) and current.get("pid") == os.getpid():
                lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
