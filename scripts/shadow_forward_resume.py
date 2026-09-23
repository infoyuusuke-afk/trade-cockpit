"""Fail-closed restart/resume policy for Shadow Forward capture.

Pure validation only. It never repairs, truncates, imports, or persists state.
"""
from __future__ import annotations

from datetime import datetime

import shadow_forward_capture as capture
import shadow_forward_evidence_chain as chain


def resume_status(events: list[dict], *, restart_now: datetime) -> str:
    if not capture._aware(restart_now):
        return "BLOCK_RESTART_TIME_INVALID"
    if not isinstance(events, list) or not events:
        return "BLOCK_NO_RESUMABLE_PREFIX"
    if capture.state_of(events) == capture.FINALIZED:
        return "BLOCK_FINALIZED_TERMINAL"

    expected_previous = chain.GENESIS
    previous_time = None
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            return "BLOCK_PREFIX_CORRUPT"
        if event.get("schema_version") != chain.SCHEMA_VERSION or event.get("source") != chain.SOURCE:
            return "BLOCK_PREFIX_CORRUPT"
        event_type = event.get("event_type")
        if event_type not in chain.ALLOWED_EVENT_TYPES:
            return "BLOCK_PREFIX_CORRUPT"
        if i == 0 and event_type != "CAPTURE_START":
            return "BLOCK_PREFIX_CORRUPT"
        if event_type == "FINALIZE":
            return "BLOCK_FINALIZED_TERMINAL"
        captured_at = event.get("captured_at")
        if not capture._aware(captured_at):
            return "BLOCK_PREFIX_CORRUPT"
        if captured_at > restart_now:
            return "BLOCK_PREFIX_FUTURE"
        if previous_time is not None and captured_at < previous_time:
            return "BLOCK_PREFIX_NON_MONOTONIC"
        if event.get("previous_hash") != expected_previous:
            return "BLOCK_PREFIX_CORRUPT"
        try:
            if event.get("event_hash") != chain.compute_event_hash(event):
                return "BLOCK_PREFIX_CORRUPT"
        except (TypeError, ValueError):
            return "BLOCK_PREFIX_CORRUPT"
        previous_time = captured_at
        expected_previous = event["event_hash"]

    return "RESUME_PREFIX_VERIFIED"


def require_resumable_prefix(events: list[dict], *, restart_now: datetime) -> list[dict]:
    if resume_status(events, restart_now=restart_now) != "RESUME_PREFIX_VERIFIED":
        raise ValueError("capture prefix not resumable")
    return events
