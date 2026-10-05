"""Display rules for cockpit lanes that are not the live entry signal.

A stored weekly snapshot is never a research sample. Missing fresh data stays
NOT AVAILABLE. This module does not submit orders and does not edit entry rules.
"""
from __future__ import annotations

import re
from pathlib import Path

SOURCE_LIVE = "LIVE"
SOURCE_SYNTHETIC = "SYNTHETIC/REPLAY"
SOURCE_SNAPSHOT = "SNAPSHOT"
SOURCE_MISSING = "NOT_AVAILABLE"
POSITION_BLOCK_REASON = "BROKER_POSITION_RSS_UNIMPLEMENTED"
WEEKLY_SNAPSHOT_CREATED = "2026-09-19 20:17 JST"

_ROOT = Path(__file__).resolve().parents[1]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def is_weekly_snapshot(record) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("created_at") == WEEKLY_SNAPSHOT_CREATED:
        return True
    count = record.get("count")
    win_rate = _number(record.get("win_rate"))
    pf = _number(record.get("pf"))
    pnl = _number(record.get("pnl"))
    return count == 15 and win_rate == 93.3 and pf == 14.32 and pnl == 109200.0


def performance_source(record) -> str:
    if not isinstance(record, dict):
        return SOURCE_MISSING
    if is_weekly_snapshot(record) or record.get("source_stage") == SOURCE_SNAPSHOT:
        return SOURCE_SNAPSHOT
    stage = record.get("source_stage")
    if stage == SOURCE_SYNTHETIC:
        return SOURCE_SYNTHETIC
    if stage == "LIVE_SHADOW":
        return SOURCE_LIVE
    return SOURCE_MISSING


def research_block_reason(record) -> str:
    """Why this row stays out of Research N, BASELINE N, and promotion."""
    source = performance_source(record)
    if source == SOURCE_SNAPSHOT or is_weekly_snapshot(record):
        return "WEEKLY_SNAPSHOT_NOT_LIVE_SHADOW"
    if source == SOURCE_SYNTHETIC:
        return "SYNTHETIC_NOT_LIVE_SAMPLE"
    if source != SOURCE_LIVE:
        return "NOT_AVAILABLE"
    return "LEDGER_ADMISSION_ONLY"


def research_sample_n(records) -> int:
    """UI lanes do not admit rows. The ledger remains the only research gate."""
    return 0 if records is not None else 0


def volume_surge_display(value, fresh: bool) -> dict:
    number = _number(value)
    if not fresh or number is None or number < 0:
        return {"text": "—", "status": SOURCE_MISSING, "lit": False}
    return {"text": f"{number:.2f}倍", "status": "OBSERVED", "lit": number >= 1.4}


def kioxia_score_display(offered_probability=None, clean_n: int = 0) -> dict:
    """Do not turn N=0, or an offered percent, into a forecast probability."""
    return {
        "probability": SOURCE_MISSING,
        "expectancy": SOURCE_MISSING,
        "confidence": SOURCE_MISSING,
        "past_statistics": "CARD_SUMMARY_ONLY",
        "clean_n": clean_n if clean_n == 0 else clean_n,
        "generated": False,
        "discarded_offer": offered_probability is not None,
        "real_submit_allowed": False,
    }


def position_block() -> dict:
    return {
        "status": "BLOCKED",
        "reason": POSITION_BLOCK_REASON,
        "rss_order": "UNIMPLEMENTED",
        "private_holdings_published": False,
        "unblock_by_live_order": False,
        "real_submit_allowed": False,
    }


def event_lane_display(items) -> dict:
    buckets = {"pts_overnight": [], "previous_limit": [], "same_day_pickup": []}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("lane")
        fresh = item.get("fresh") is True
        stage = item.get("source_stage")
        if kind in buckets and fresh and stage in {SOURCE_LIVE, "LIVE_SHADOW"}:
            buckets[kind].append({"symbol": item.get("symbol"), "source_stage": stage})
    return {
        key: {"status": "OBSERVED" if rows else SOURCE_MISSING, "rows": rows}
        for key, rows in buckets.items()
    }


def earnings_lanes() -> dict:
    return {
        "calendar": {
            "status": "PARTIAL",
            "live_signal": False,
            "source": "JPX financial announcement schedule",
        },
        "past_results": {"status": "PARTIAL", "live_signal": False},
        "this_forecast": {
            "probability": SOURCE_MISSING,
            "expectancy": SOURCE_MISSING,
            "live_signal": False,
        },
        "swing_prep": {
            "status": SOURCE_MISSING,
            "live_signal": False,
            "note": "A one-month swing plan is not connected to the live entry rule.",
        },
        "real_submit_allowed": False,
    }


def powershell_non_ascii_lines(relative: str) -> dict:
    """Separate Japanese comments from non-ASCII that sits in execution text."""
    path = _ROOT / relative
    comment_lines = []
    code_lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.isascii():
            continue
        code = re.sub(r"#.*$", "", line)
        if code.isascii():
            comment_lines.append(number)
        else:
            code_lines.append(number)
    return {
        "path": relative,
        "comment_only_lines": comment_lines,
        "execution_lines": code_lines,
        "safe_to_strip_comments_only": bool(comment_lines) and not code_lines,
    }
