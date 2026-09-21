"""Private Shadow Forward evidence-chain pure validator.

No file I/O, broker/RSS order calls, or Real path. Actual evidence stays under
ignored private roots. This module only constructs/verifies deterministic
metadata envelopes so edits, deletion, insertion, and reordering fail closed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

SCHEMA_VERSION = "shadow-forward-evidence-chain-0.1"
SOURCE = "SHADOW_FORWARD"
GENESIS = "0" * 64
ALLOWED_EVENT_TYPES = ("CAPTURE_START", "LIFECYCLE_STEP", "FINALIZE")


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _canonical(value):
    if isinstance(value, datetime):
        if not _aware(value):
            raise ValueError("datetime must be timezone-aware")
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonical(x) for x in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("unsupported evidence value")


def compute_event_hash(event: dict) -> str:
    payload = {k: v for k, v in event.items() if k != "event_hash"}
    raw = json.dumps(_canonical(payload), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def make_event(*, event_type: str, captured_at: datetime, payload: dict,
               previous_hash: str = GENESIS) -> dict:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError("invalid event_type")
    if not _aware(captured_at):
        raise ValueError("captured_at must be timezone-aware")
    if not isinstance(payload, dict):
        raise ValueError("payload must be dict")
    if not isinstance(previous_hash, str) or len(previous_hash) != 64:
        raise ValueError("invalid previous_hash")
    event = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "event_type": event_type,
        "captured_at": captured_at,
        "previous_hash": previous_hash,
        "payload": payload,
    }
    event["event_hash"] = compute_event_hash(event)
    return event


def verify_chain(events: list[dict], *, now: datetime) -> dict:
    reasons = []
    if not _aware(now):
        return {"valid": False, "reasons": ["NOW_NOT_TIMEZONE_AWARE"], "finalized": False}
    if not isinstance(events, list) or not events:
        return {"valid": False, "reasons": ["CHAIN_EMPTY_OR_INVALID"], "finalized": False}

    previous_hash = GENESIS
    previous_time = None
    finalized = False
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            reasons.append(f"EVENT_{index}_INVALID")
            continue
        if event.get("schema_version") != SCHEMA_VERSION:
            reasons.append(f"EVENT_{index}_SCHEMA")
        if event.get("source") != SOURCE:
            reasons.append(f"EVENT_{index}_SOURCE")
        event_type = event.get("event_type")
        if event_type not in ALLOWED_EVENT_TYPES:
            reasons.append(f"EVENT_{index}_TYPE")
        captured_at = event.get("captured_at")
        if not _aware(captured_at):
            reasons.append(f"EVENT_{index}_TIME")
        else:
            if captured_at > now:
                reasons.append(f"EVENT_{index}_FUTURE")
            if previous_time is not None and captured_at < previous_time:
                reasons.append(f"EVENT_{index}_NON_MONOTONIC")
            previous_time = captured_at
        if event.get("previous_hash") != previous_hash:
            reasons.append(f"EVENT_{index}_PREVIOUS_HASH")
        try:
            expected = compute_event_hash(event)
        except (TypeError, ValueError):
            reasons.append(f"EVENT_{index}_UNHASHABLE")
            expected = None
        if event.get("event_hash") != expected:
            reasons.append(f"EVENT_{index}_HASH")
        if index == 0 and event_type != "CAPTURE_START":
            reasons.append("FIRST_EVENT_NOT_CAPTURE_START")
        if finalized:
            reasons.append(f"EVENT_{index}_AFTER_FINALIZE")
        if event_type == "FINALIZE":
            finalized = True
        previous_hash = event.get("event_hash") if isinstance(event.get("event_hash"), str) else ""

    if not finalized:
        reasons.append("CHAIN_NOT_FINALIZED")
    return {"valid": not reasons, "reasons": reasons, "finalized": finalized}
