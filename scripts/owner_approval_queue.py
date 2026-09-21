"""Owner approval queue projection. Does not perform approvals or side effects."""
from __future__ import annotations

from datetime import datetime

APPROVAL_TYPES = {"MAIN_MERGE", "REAL_MONEY_SUBMIT", "EXTERNAL_PUBLISH"}
INPUT_FIELDS = {"approval_id", "approval_type", "created_at", "summary"}
QUEUE_FIELDS = INPUT_FIELDS | {"status", "auto_approve"}
DECIDED_FIELDS = QUEUE_FIELDS | {"decided_at", "decided_by"}


def _aware_timestamp(value, field):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def build_queue(items):
    if not isinstance(items, list):
        raise ValueError("items must be list")
    out = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != INPUT_FIELDS:
            raise ValueError("invalid approval item")
        approval_type = item["approval_type"]
        if approval_type not in APPROVAL_TYPES:
            raise ValueError("invalid approval_type")
        approval_id = item["approval_id"]
        if not isinstance(approval_id, str) or not approval_id.strip() or approval_id in seen:
            raise ValueError("invalid or duplicate approval_id")
        seen.add(approval_id)
        _aware_timestamp(item["created_at"], "created_at")
        out.append({
            "approval_id": approval_id,
            "approval_type": approval_type,
            "created_at": item["created_at"],
            "summary": item["summary"],
            "status": "PENDING_OWNER",
            "auto_approve": False,
        })
    return sorted(out, key=lambda x: (x["created_at"], x["approval_id"]))


def decide(item, decision, *, decided_at, decided_by):
    if not isinstance(item, dict) or set(item) != QUEUE_FIELDS:
        raise ValueError("invalid queue item")
    if item["status"] != "PENDING_OWNER" or item["auto_approve"] is not False:
        raise ValueError("approval is not pending")
    if decision not in {"APPROVE", "REJECT"}:
        raise ValueError("invalid decision")
    if decided_by != "OWNER":
        raise ValueError("decided_by must be OWNER")
    created_at = _aware_timestamp(item["created_at"], "created_at")
    decision_time = _aware_timestamp(decided_at, "decided_at")
    if decision_time < created_at:
        raise ValueError("decided_at precedes created_at")
    return {
        **item,
        "status": "OWNER_APPROVED" if decision == "APPROVE" else "OWNER_REJECTED",
        "auto_approve": False,
        "decided_at": decided_at,
        "decided_by": decided_by,
    }
