"""Trusted-ingestion adapter for private Shadow Forward capture.

The caller cannot supply capture_now. The runner-owned clock is sampled at
receipt and that value alone is passed to the C-106 state machine.
No persistence, scheduler, broker, RSS, or Real-submit side effects.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import shadow_forward_capture as capture


def ingest(events: list[dict], *, event_type: str, observation_now: datetime,
           payload: dict, clock: Callable[[], datetime]) -> dict:
    if not callable(clock):
        raise ValueError("runner clock required")
    receipt_now = clock()
    if not capture._aware(receipt_now):
        raise ValueError("runner clock must return timezone-aware datetime")
    if not isinstance(payload, dict):
        raise ValueError("payload must be dict")

    # Reserved provenance names may not be smuggled through caller data.
    forbidden = {"capture_now", "captured_at", "receipt_now", "runner_received_at"}
    if forbidden.intersection(payload):
        raise ValueError("caller cannot override trusted ingestion provenance")

    result = capture.append_capture_event(
        events,
        event_type=event_type,
        capture_now=receipt_now,
        observation_now=observation_now,
        payload=payload,
    )
    return {
        "state": result["state"],
        "events": result["events"],
        "runner_received_at": receipt_now,
    }
