"""Research-only per-symbol freshness verdict and restart-surviving private journal.

No V10 runtime wiring, broker access, Excel access, network, or order permission.
Not evidence of real-market performance. Fail closed on ambiguous lineage.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_AGE_SECONDS = 120
SCHEMA = "v10-private-freshness-research-1"
TICKER = re.compile(r"^[A-Z0-9]{4}\.T$")
REPO = Path(__file__).resolve().parents[1]


class EvidenceRejected(ValueError):
    pass


def _date(value):
    if not isinstance(value, str):
        raise EvidenceRejected("TIME_MISSING")
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceRejected("TIME_INVALID") from exc
    if t.utcoffset() is None:
        raise EvidenceRejected("TIME_OFFSET_MISSING")
    return t.astimezone(timezone.utc)


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def assess(payload):
    """No LIVE availability granted, only per-symbol research eligibility labels."""
    if not isinstance(payload, dict) or payload.get("schema_version") != "v10-freshness-input-1":
        raise EvidenceRejected("SCHEMA_INVALID")
    now = _date(payload.get("evaluated_at"))
    acquired = _date(payload.get("collector_heartbeat_at"))
    session = payload.get("session_id")
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", session):
        raise EvidenceRejected("SESSION_INVALID")
    if payload.get("source_mode") != "MS2_RSS_WORKBOOK" or payload.get("workbook_identity_verified") is not True:
        raise EvidenceRejected("SOURCE_OR_WORKBOOK_UNVERIFIED")
    if (now-acquired).total_seconds() < 0 or (now-acquired).total_seconds() > MAX_AGE_SECONDS:
        collector_healthy = False
    else:
        collector_healthy = True
    expected = payload.get("expected_tickers")
    if not isinstance(expected, list) or not expected or len(expected) > 5000 or len(set(expected)) != len(expected):
        raise EvidenceRejected("EXPECTED_UNIVERSE_INVALID")
    if not all(isinstance(x, str) and TICKER.fullmatch(x) for x in expected):
        raise EvidenceRejected("EXPECTED_TICKER_INVALID")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise EvidenceRejected("ROWS_INVALID")
    evidence = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("ticker") not in expected:
            raise EvidenceRejected("UNKNOWN_SYMBOL")
        code = row["ticker"]
        if code in evidence:
            raise EvidenceRejected("DUPLICATE_SYMBOL")
        evidence[code] = row
    report = []
    for code in expected:
        row = evidence.get(code)
        reasons = []
        if not collector_healthy:
            reasons.append("COLLECTOR_HEARTBEAT_UNAVAILABLE")
        if row is None:
            reasons.append("ROW_MISSING")
        else:
            # A row's unchanged last-trade price does not imply a dead collector.
            # Only independent evidence for its observed quote is eligible.
            if row.get("source_authenticated") is not True:
                reasons.append("ROW_SOURCE_UNVERIFIED")
            if row.get("quote_observed_at") is None or row.get("quote_available_at") is None:
                reasons.append("ROW_TIME_MISSING")
            else:
                observed = _date(row["quote_observed_at"])
                available = _date(row["quote_available_at"])
                age = (now-available).total_seconds()
                if observed > available or age < 0:
                    reasons.append("ROW_FUTURE_OR_OUT_OF_ORDER")
                elif age > MAX_AGE_SECONDS:
                    reasons.append("ROW_QUOTE_STALE")
            if row.get("quote_present") is not True:
                reasons.append("ROW_QUOTE_MISSING")
        report.append({"ticker": code, "state": "FRESH" if not reasons else "BLOCKED",
                       "reasons": reasons})
    fresh = sum(x["state"] == "FRESH" for x in report)
    return {
        "schema_version": SCHEMA, "session_id": session, "evaluated_at": now.isoformat(),
        "collector_healthy": collector_healthy, "expected": len(expected),
        "fresh": fresh, "blocked": len(expected)-fresh, "rows": report,
        "aggregate_eligible": fresh == len(expected),
        "candidate_values": "WITHHELD_REQUIRES_INDEPENDENT_RECOMPUTATION",
        "real_submit_allowed": False,
    }


def _private(path):
    target = Path(path).resolve()
    if target == REPO or REPO in target.parents:
        raise EvidenceRejected("PUBLIC_REPO_PATH_FORBIDDEN")
    if not target.parent.is_dir() or target.is_symlink():
        raise EvidenceRejected("PATH_INVALID")
    return target


def _line(record, prev):
    core = {"previous_sha256": prev, "record": record}
    core["sha256"] = hashlib.sha256(_canonical(core).encode("utf-8")).hexdigest()
    return core


def journal_append(path, record):
    """Append once and fsync; readback replays *all* prior lines before append.

    POSIX-only for now; Windows safe append durability is NOT_ACCEPTED. Caller
    must hold an exclusive external writer lock. Do not attach to V10 runtime.
    """
    if os.name == "nt":
        raise EvidenceRejected("WINDOWS_NATIVE_APPEND_NOT_ACCEPTED")
    target = _private(path)
    if target.exists() and (not target.is_file() or target.is_symlink()):
        raise EvidenceRejected("FILE_UNSAFE")
    history = journal_read(target) if target.exists() else []
    if any(v["record"]["session_id"] == record["session_id"]
           and v["record"]["evaluated_at"] == record["evaluated_at"] for v in history):
        raise EvidenceRejected("DUPLICATE_EVENT")
    previous = history[-1]["sha256"] if history else "0"*64
    entry = _line(record, previous)
    descriptor = os.open(str(target), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8") as f:
            f.write(_canonical(entry) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        raise
    after = journal_read(target)
    if not after or after[-1] != entry:
        raise EvidenceRejected("READBACK_FAILED")
    return {"records": len(after), "head_sha256": entry["sha256"], "real_submit_allowed": False}


def journal_read(path):
    target = _private(path)
    previous = "0"*64
    out = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        try:
            x = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EvidenceRejected("JOURNAL_CORRUPT") from exc
        if not isinstance(x, dict) or set(x) != {"record", "previous_sha256", "sha256"}:
            raise EvidenceRejected("JOURNAL_SHAPE_INVALID")
        core = {"previous_sha256": x["previous_sha256"], "record": x["record"]}
        if x["previous_sha256"] != previous or _line(x["record"], previous)["sha256"] != x["sha256"]:
            raise EvidenceRejected("JOURNAL_HASH_CHAIN_BROKEN")
        previous = x["sha256"]
        out.append(x)
    return out
