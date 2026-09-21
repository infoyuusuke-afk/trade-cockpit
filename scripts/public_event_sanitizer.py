"""Deterministic public-safe projection for Entertainment/Publishing inputs.

Source Event Bus events are validated and never mutated.
"""
from __future__ import annotations

from scripts.event_bus import validate_event

PUBLIC_EVENT_FIELDS = {"event_id", "timestamp", "event_type", "summary"}
SAFE_PAYLOAD_FIELDS = {"summary"}
SENSITIVE_TOKENS = {
    "account", "balance", "board", "broker", "cash", "credential", "email",
    "fill", "holdings", "order", "phone", "position", "private", "quantity",
    "tape", "token",
}


def _contains_sensitive_key(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(token in normalized for token in SENSITIVE_TOKENS):
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def sanitize_event(event):
    if not validate_event(event):
        raise ValueError("invalid source event")
    payload = event["payload"]
    if _contains_sensitive_key(payload):
        raise ValueError("sensitive payload rejected")
    if not isinstance(payload, dict) or not set(payload).issubset(SAFE_PAYLOAD_FIELDS):
        raise ValueError("payload is not public-safe")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("public summary required")
    return {
        "event_id": event["event_id"],
        "timestamp": event["timestamp"],
        "event_type": event["event_type"],
        "summary": summary,
    }


def validate_sanitized_event(event):
    return (
        isinstance(event, dict)
        and set(event) == PUBLIC_EVENT_FIELDS
        and isinstance(event.get("event_id"), str)
        and bool(event["event_id"])
        and isinstance(event.get("timestamp"), str)
        and isinstance(event.get("event_type"), str)
        and bool(event["event_type"])
        and isinstance(event.get("summary"), str)
        and bool(event["summary"].strip())
    )
