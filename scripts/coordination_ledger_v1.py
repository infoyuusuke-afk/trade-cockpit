"""Read-only, offline validator for public 100B coordination Issue comments.

This module has NO network or repository write capability, and NEVER authorizes
trade execution, publication, merging, cross-engine modifications or billing.
Source roles are self-declared and NOT authenticated by public GitHub comments.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any

PREFIX = "[100B_COORD_V1]"
REPO = "https://github.com/infoyuusuke-afk/trade-cockpit"
ROLES = frozenset({
    "progress_coordinator", "development_lead", "spec_audit",
    "revenue_hunter", "pre_next", "supply_demand_analyst", "claude_auditor",
})
EVENTS = frozenset({"REPORT", "ASSIGN", "ACK", "RESULT", "REVIEW", "CHANGE_REQUEST"})
REPLY_EVENTS = frozenset({"ACK", "RESULT", "REVIEW", "CHANGE_REQUEST"})
BOUNDARIES = frozenset({
    "REVIEW_ONLY", "OWNER_APPROVED_PILOT", "CHANGE_REQUEST_PENDING_OWNER",
})
REQUIRED = frozenset({
    "message_id", "event_type", "source_role", "recipient_role",
    "project_item_id", "sent_at_jst", "evidence_url",
    "owner_approval_boundary", "real_submit_allowed",
})
OPTIONAL = frozenset({
    "in_reply_to", "state", "next_action", "acceptance", "main_sha",
    "pr_number", "head_sha", "data_as_of", "data_available_at", "ev",
    "pf", "n", "cost_impact",
})
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
SHA_RE = re.compile(r"^[a-fA-F0-9]{40}$")
# Defense in depth only: user review is still mandatory before public posting.
SECRET_RE = re.compile(
    r"ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|"
    r"sk-[A-Za-z0-9]{12,}|Bearer\s+\S+|"
    r"[A-Za-z]:\\|/Users/|/home/|"
    r"(?i:real_submit_allowed\s*:\s*true)"
)


class InvalidMessage(ValueError):
    """A public coordination record must fail closed."""


def _parse_timestamp(value: str, now: datetime) -> None:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidMessage("INVALID_TIMESTAMP") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(hours=9):
        raise InvalidMessage("TIMESTAMP_NOT_JST_OFFSET")
    if timestamp > now + timedelta(minutes=5):
        raise InvalidMessage("FUTURE_TIMESTAMP")


def parse_message(body: str, *, now: datetime | None = None) -> dict[str, str] | None:
    """Ignore legacy comments; validate every tagged record strictly."""
    if not isinstance(body, str):
        raise InvalidMessage("BODY_NOT_TEXT")
    if not body.startswith(PREFIX):
        return None
    if len(body) > 8000 or SECRET_RE.search(body):
        raise InvalidMessage("UNSAFE_OR_OVERSIZE_BODY")
    values: dict[str, str] = {}
    for line in body.splitlines()[1:]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or key not in (REQUIRED | OPTIONAL) or key in values:
            raise InvalidMessage("UNKNOWN_DUPLICATE_OR_MALFORMED_FIELD")
        if not value or len(value) > 1000:
            raise InvalidMessage("EMPTY_OR_OVERSIZE_FIELD")
        values[key] = value
    if not REQUIRED.issubset(values):
        raise InvalidMessage("MISSING_REQUIRED_FIELD")
    if values["real_submit_allowed"] != "false":
        raise InvalidMessage("REAL_SUBMIT_MUST_BE_FALSE")
    if values["source_role"] not in ROLES or values["recipient_role"] not in ROLES:
        raise InvalidMessage("UNKNOWN_ROLE")
    if values["source_role"] == values["recipient_role"]:
        raise InvalidMessage("SELF_DELIVERY_FORBIDDEN")
    if values["event_type"] not in EVENTS:
        raise InvalidMessage("UNKNOWN_EVENT")
    if values["owner_approval_boundary"] not in BOUNDARIES:
        raise InvalidMessage("UNKNOWN_OWNER_BOUNDARY")
    for field in ("message_id", "project_item_id"):
        if not ID_RE.fullmatch(values[field]):
            raise InvalidMessage("INVALID_ID")
    if "in_reply_to" in values and not ID_RE.fullmatch(values["in_reply_to"]):
        raise InvalidMessage("INVALID_REPLY_ID")
    if values["event_type"] in REPLY_EVENTS and "in_reply_to" not in values:
        raise InvalidMessage("REPLY_REFERENCE_REQUIRED")
    if values["event_type"] == "ASSIGN" and values["source_role"] != "progress_coordinator":
        raise InvalidMessage("ASSIGN_REQUIRES_COORDINATOR")
    if not (
        values["evidence_url"] == REPO
        or values["evidence_url"].startswith(REPO + "/")
    ):
        raise InvalidMessage("PUBLIC_REPO_EVIDENCE_REQUIRED")
    for field in ("main_sha", "head_sha"):
        if field in values and not SHA_RE.fullmatch(values[field]):
            raise InvalidMessage("INVALID_SHA")
    if "pr_number" in values and not (
        values["pr_number"].isdigit() and int(values["pr_number"]) > 0
    ):
        raise InvalidMessage("INVALID_PR_NUMBER")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise InvalidMessage("NAIVE_CLOCK")
    _parse_timestamp(values["sent_at_jst"], current)
    return values


def reconcile(comments: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate messages and causal relations without claiming role identity."""
    seen: dict[str, dict[str, str]] = {}
    acked_parent_role: set[tuple[str, str]] = set()
    valid: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for index, comment in enumerate(comments):
        url = str(comment.get("url") or "")
        try:
            message = parse_message(comment.get("body", ""), now=now)
            if message is None:
                continue
            mid = message["message_id"]
            if mid in seen:
                raise InvalidMessage("DUPLICATE_MESSAGE_ID")
            parent_id = message.get("in_reply_to")
            if parent_id:
                parent = seen.get(parent_id)
                if parent is None:
                    raise InvalidMessage("MISSING_OR_UNVERIFIED_PARENT")
                if (
                    message["source_role"] != parent["recipient_role"]
                    or message["recipient_role"] != parent["source_role"]
                    or message["project_item_id"] != parent["project_item_id"]
                ):
                    raise InvalidMessage("WRONG_DIRECTION_OR_PROJECT")
                if message["event_type"] == "ACK" and parent["event_type"] not in {
                    "ASSIGN", "REPORT", "REVIEW"
                }:
                    raise InvalidMessage("INVALID_ACK_PARENT")
                if message["event_type"] == "REVIEW" and parent["event_type"] not in {
                    "RESULT", "REPORT"
                }:
                    raise InvalidMessage("INVALID_REVIEW_PARENT")
            if message["event_type"] == "ACK" and parent_id:
                dedupe_key = (parent_id, message["source_role"])
                if dedupe_key in acked_parent_role:
                    raise InvalidMessage("DUPLICATE_ACK_FOR_PARENT")
                acked_parent_role.add(dedupe_key)
            seen[mid] = message
            valid.append({
                "message_id": mid,
                "event_type": message["event_type"],
                "project_item_id": message["project_item_id"],
                "source_role": message["source_role"],
                "recipient_role": message["recipient_role"],
                "in_reply_to": parent_id or "",
                "url": url,
                "sender_role_verified": "false",
            })
        except InvalidMessage as exc:
            errors.append({"index": str(index), "url": url, "error": str(exc)})
    return {
        "status": "SCHEMA_CHECK_ONLY",
        "valid_messages": valid,
        "invalid_messages": errors,
        "sender_role_authenticated": False,
        "end_to_end_verified": False,
        "real_submit_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only public coordination ledger check")
    parser.add_argument("comments_json", help="Locally supplied public GitHub issue comment JSON")
    args = parser.parse_args()
    raw = json.loads(Path(args.comments_json).read_text(encoding="utf-8"))
    comments = raw if isinstance(raw, list) else raw.get("comments")
    if not isinstance(comments, list):
        parser.error("expected a list or object with a comments list")
    result = reconcile(comments)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result["invalid_messages"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
