"""Pure capture state machine for private Shadow Forward evidence.

This module performs no persistence and has no hidden clock. Callers provide
capture_now and observation_now explicitly; actual records remain private.
"""
from __future__ import annotations

from datetime import datetime

import shadow_forward_evidence_chain as chain

EMPTY = "EMPTY"
CAPTURING = "CAPTURING"
FINALIZED = "FINALIZED"


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def state_of(events: list[dict]) -> str:
    if not events:
        return EMPTY
    if events[-1].get("event_type") == "FINALIZE":
        return FINALIZED
    return CAPTURING


def append_capture_event(events: list[dict], *, event_type: str, capture_now: datetime,
                         observation_now: datetime, payload: dict) -> dict:
    """Return a new list with one event appended, or fail closed with ValueError."""
    if not isinstance(events, list):
        raise ValueError("events must be list")
    if not _aware(capture_now) or not _aware(observation_now):
        raise ValueError("timestamps must be timezone-aware")
    if observation_now > capture_now:
        raise ValueError("observation cannot be future relative to capture")
    if not isinstance(payload, dict):
        raise ValueError("payload must be dict")

    current = state_of(events)
    if current == EMPTY:
        if event_type != "CAPTURE_START":
            raise ValueError("first event must be CAPTURE_START")
        previous_hash = chain.GENESIS
    else:
        # A partial chain is intentionally invalid under C-105 because it is not
        # finalized. For append-time validation, verify immutable prefix
        # invariants without pretending the partial chain is acceptance-valid.
        prefix_now = capture_now
        previous_hash = events[-1].get("event_hash")
        if not isinstance(previous_hash, str) or len(previous_hash) != 64:
            raise ValueError("prior chain corrupt")
        previous_time = None
        expected_previous = chain.GENESIS
        for i, event in enumerate(events):
            if not isinstance(event, dict):
                raise ValueError("prior chain corrupt")
            if event.get("source") != chain.SOURCE or event.get("schema_version") != chain.SCHEMA_VERSION:
                raise ValueError("prior chain corrupt")
            if event.get("previous_hash") != expected_previous:
                raise ValueError("prior chain corrupt")
            if event.get("event_hash") != chain.compute_event_hash(event):
                raise ValueError("prior chain corrupt")
            t = event.get("captured_at")
            if not _aware(t) or t > prefix_now or (previous_time is not None and t < previous_time):
                raise ValueError("prior chain corrupt")
            if i == 0 and event.get("event_type") != "CAPTURE_START":
                raise ValueError("prior chain corrupt")
            if i < len(events) - 1 and event.get("event_type") == "FINALIZE":
                raise ValueError("prior chain corrupt")
            previous_time = t
            expected_previous = event["event_hash"]

        if current == FINALIZED:
            raise ValueError("FINALIZE is terminal")
        if event_type not in ("LIFECYCLE_STEP", "FINALIZE"):
            raise ValueError("invalid transition")
        if capture_now < events[-1]["captured_at"]:
            raise ValueError("capture time cannot move backward")
        start_time = events[0]["captured_at"]
        if observation_now < start_time:
            raise ValueError("observation predates capture start")

    event = chain.make_event(
        event_type=event_type,
        captured_at=capture_now,
        payload={"observation_now": observation_now, "data": payload},
        previous_hash=previous_hash,
    )
    return {"state": FINALIZED if event_type == "FINALIZE" else CAPTURING,
            "events": events + [event]}
