"""Read-only compatibility reader for Issue #282 coordination comments.

It reads the three formats that actually appear on Issue #282 side by side:

* ``COORD_V1_STRICT``: bodies that pass the PR #385 reference parser unchanged.
* ``COORD_V1_OBSERVED``: ``[100B_COORD_V1]`` bodies as agents really write them
  (extra fields, multi-recipient lists, free event names, a preamble line).
* ``REPORT_DELIVERY_V1``: the fixed PR #447 envelope.

Untagged comments are counted as ``LEGACY_UNTAGGED`` and never parsed.

The PR #385 contract is reused, not changed: strict validation is delegated to
``scripts.coordination_ledger_v1``. Nothing here posts, retries, edits or
deletes anything, and nothing here authenticates a role. The only server-side
provenance on a comment is GitHub's ``performed_via_github_app`` slug, which
names the posting tool family, never the scheduled task or the role.
``end_to_end_verified`` is therefore always false.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from scripts.coordination_ledger_v1 import (
    SECRET_RE, InvalidMessage, parse_message,
)

COORD_TAG = "[100B_COORD_V1]"
DELIVERY_TAG = "[100B_REPORT_DELIVERY_V1]"
JST = timezone(timedelta(hours=9))
FUTURE_SKEW = timedelta(minutes=5)

# Current roster (OWNER roster correction 2026-10-19). spec_audit is retired:
# it is still parsed for history, but flagged and never treated as live.
LIVE_ROLES = frozenset({
    "owner", "progress_coordinator", "development_lead", "implementer_claude",
    "revenue_hunter", "pre_next", "supply_demand_analyst",
})
RETIRED_ROLES = frozenset({"spec_audit"})
ROLE_ALIASES = {
    "supply_sq": "supply_demand_analyst",
    "claude_auditor": "implementer_claude",
}
# Which posting tool family each role is expected to use. A claim from another
# family is a spoofing indicator; a match is NOT authentication.
ROLE_CHANNEL = {
    "progress_coordinator": "chatgpt-codex-connector",
    "development_lead": "chatgpt-codex-connector",
    "revenue_hunter": "chatgpt-codex-connector",
    "pre_next": "chatgpt-codex-connector",
    "supply_demand_analyst": "chatgpt-codex-connector",
    "implementer_claude": "claude",
}
# Observed free event names mapped onto the #385 event classes. Anything not
# listed stays OTHER and cannot take part in ACK correlation.
EVENT_CLASS = {
    "ACK": "ACK",
    "ASSIGN": "ASSIGN", "TASK_ASSIGNMENT": "ASSIGN",
    "REPORT": "REPORT", "DIAGNOSTIC_RESULT": "REPORT",
    "RESULT": "RESULT", "IMPLEMENTATION_RESULT": "RESULT",
    "UPDATED_IMPLEMENTATION_RESULT": "RESULT", "DEVELOPMENT_RESULT": "RESULT",
    "VERIFICATION_RESULT": "RESULT", "IMPLEMENTATION_PROGRESS": "RESULT",
    "REVIEW": "REVIEW", "REVIEW_RESULT": "REVIEW",
    "INDEPENDENT_REVIEW_RESULT": "REVIEW", "INDEPENDENT_ACCEPTANCE": "REVIEW",
    "INDEPENDENT_CROSS_STACK_ACCEPTANCE": "REVIEW",
    "CHANGE_REQUEST": "CHANGE_REQUEST",
}
ACK_PARENTS = frozenset({"ASSIGN", "REPORT", "RESULT", "REVIEW"})
DELIVERY_KEYS = (
    "message_id", "event_type", "sender_role_authenticated", "state",
    "head_sha", "draft_pr", "ci", "real_submit_allowed", "stop_allowed",
    "cutover_eligible", "recipient_ack", "production_verified",
)
KEY_RE = re.compile(r"^([a-z][a-z0-9_]{0,63}):\s*(.*)$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
DENIAL_RE = re.compile(
    r"PLATFORM_SAFETY_DENIED|blocked by (?:OpenAI|safety)|WRITE_UNAVAILABLE|"
    r"HANDOFF_PENDING", re.IGNORECASE)


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _role(value: str) -> str:
    value = value.strip().strip("`").lower()
    return ROLE_ALIASES.get(value, value)


def _roles(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,/]|\band\b", value.replace("_and_", ","))
    return sorted({_role(p) for p in parts if p.strip()})


def _fields(lines: list[str]) -> dict[str, str]:
    """Header block: key: value lines right after the tag, up to a blank line."""
    values: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            if values:
                break
            continue
        match = KEY_RE.match(line.strip())
        if not match:
            if values:
                break
            continue
        key, value = match.groups()
        if key == "https":  # a bare URL line, not a field
            continue
        values.setdefault(key, value.strip())
    return values


def classify(comment: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Normalise one GitHub issue-comment object. Never raises on content."""
    body = comment.get("body") if isinstance(comment.get("body"), str) else ""
    created = _ts(comment.get("created_at"))
    updated = _ts(comment.get("updated_at"))
    app = (comment.get("performed_via_github_app") or {}).get("slug") or "none"
    out: dict[str, Any] = {
        "comment_id": comment.get("id"),
        "url": comment.get("html_url") or comment.get("url") or "",
        "created_at": comment.get("created_at"),
        "posting_channel": app,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "protocol": "LEGACY_UNTAGGED",
        "message_id": None, "event_type": None, "event_class": "OTHER",
        "source_role": None, "recipient_roles": [], "project_item_id": None,
        "in_reply_to": None, "declared_time": None,
        "sender_role_verified": False, "warnings": [], "blocking": [],
    }
    warn, block = out["warnings"], out["blocking"]
    if created is None:
        block.append("SERVER_TIME_MISSING")
    if updated and created and updated - created > timedelta(seconds=60):
        warn.append("EDITED_AFTER_POST")
    if SECRET_RE.search(body):
        block.append("UNSAFE_CONTENT")
    if re.search(r"real_submit_allowed\s*[:=]\s*true", body, re.IGNORECASE):
        block.append("REAL_SUBMIT_TRUE")

    lines = body.splitlines()
    tag_line = next((i for i, l in enumerate(lines)
                     if l.strip().startswith((COORD_TAG, DELIVERY_TAG))), None)
    if tag_line is None:
        return out
    tag = lines[tag_line].strip()
    if tag_line:
        warn.append("PREAMBLE_BEFORE_TAG")

    if tag.startswith(DELIVERY_TAG):
        out["protocol"] = "REPORT_DELIVERY_V1"
        values = _fields(lines[tag_line + 1:])
        out.update(message_id=values.get("message_id"),
                   event_type=values.get("event_type"),
                   event_class="REPORT" if values.get("event_type") == "REPORT" else "OTHER")
        # #447 carries no role, recipient or project: it cannot be correlated
        # to an ACK by role. That gap is a change request, not inferred here.
        warn.append("NO_ROLE_FIELDS_IN_DELIVERY_ENVELOPE")
        if set(values) - set(DELIVERY_KEYS):
            warn.append("UNKNOWN_DELIVERY_FIELD")
    else:
        if tag != COORD_TAG:
            warn.append("TEXT_ON_TAG_LINE")
        values = _fields(lines[tag_line + 1:])
        strict = "\n".join(lines[tag_line:])
        try:
            parse_message(strict, now=now)
            out["protocol"] = "COORD_V1_STRICT"
        except InvalidMessage as exc:
            out["protocol"] = "COORD_V1_OBSERVED"
            out["strict_rejection"] = str(exc)
        source = values.get("source_role")
        out.update(
            message_id=values.get("message_id"),
            event_type=values.get("event_type"),
            event_class=EVENT_CLASS.get((values.get("event_type") or "").upper(), "OTHER"),
            source_role=_role(source) if source else None,
            recipient_roles=_roles(values.get("recipient_role")),
            project_item_id=values.get("project_item_id"),
            in_reply_to=values.get("in_reply_to"),
            declared_time=(values.get("sent_at_jst") or values.get("as_of_jst")
                           or values.get("as_of")),
        )
        roles = ([out["source_role"]] if out["source_role"] else []) + out["recipient_roles"]
        if any(r in RETIRED_ROLES for r in roles):
            warn.append("RETIRED_ROLE")
        if any(r not in LIVE_ROLES | RETIRED_ROLES for r in roles):
            warn.append("UNKNOWN_ROLE")
        expected = ROLE_CHANNEL.get(out["source_role"] or "")
        if expected and app != expected:
            # "none" is a plain token (CLI/web): unattested, not contradicting.
            (warn if app == "none" else block).append(
                "CHANNEL_UNATTESTED" if app == "none" else "ROLE_CHANNEL_MISMATCH")
        if out["source_role"] and out["source_role"] in out["recipient_roles"]:
            block.append("SELF_ADDRESSED")
        if not out["source_role"]:
            warn.append("SOURCE_ROLE_MISSING")

    mid = out["message_id"]
    if mid is None:
        block.append("MESSAGE_ID_MISSING")
    elif not ID_RE.fullmatch(mid):
        block.append("MESSAGE_ID_INVALID")
    if out["in_reply_to"] and not ID_RE.fullmatch(out["in_reply_to"]):
        block.append("REPLY_ID_INVALID")
    declared = _ts(out["declared_time"])
    if out["declared_time"] and declared is None:
        warn.append("DECLARED_TIME_INVALID")
    elif declared is None:
        warn.append("DECLARED_TIME_MISSING_SERVER_TIME_USED")
    elif created and declared > created + FUTURE_SKEW:
        block.append("DECLARED_TIME_AFTER_POST")
    if created and created > now + FUTURE_SKEW:
        block.append("FUTURE_SERVER_TIME")
    if DENIAL_RE.search(body):
        out["denial_or_handoff_reported"] = True
    return out


def reconcile(comments: list[dict[str, Any]], *, now: datetime | None = None,
              baseline: list[dict[str, Any]] | None = None,
              expected_message_ids: list[str] | None = None) -> dict[str, Any]:
    """Correlate messages and ACKs. Read-only; no role is ever authenticated."""
    now = now or datetime.now(timezone.utc)
    ordered = sorted(comments, key=lambda c: (str(c.get("created_at") or ""), c.get("id") or 0))
    records = [classify(c, now=now) for c in ordered]
    by_id: dict[str, dict[str, Any]] = {}
    acks: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in records:
        mid = rec["message_id"]
        if mid is None or rec["blocking"]:
            continue
        first = by_id.get(mid)
        if first is not None:
            rec["blocking"].append("DUPLICATE_MESSAGE_ID" if first["body_sha256"]
                                   == rec["body_sha256"] else "ID_CONTENT_CONFLICT")
            continue
        by_id[mid] = rec
        parent_id = rec["in_reply_to"]
        if not parent_id:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            rec["blocking"].append("ORPHAN_REPLY_PARENT_NOT_FOUND")
            rec["correlation"] = "ORPHAN"
            continue
        problems = []
        if parent["protocol"] == "REPORT_DELIVERY_V1":
            problems.append("PARENT_HAS_NO_ROLES")
        else:
            if rec["source_role"] not in parent["recipient_roles"]:
                problems.append("REPLIER_NOT_A_RECIPIENT")
            if parent["source_role"] not in rec["recipient_roles"]:
                problems.append("REPLY_NOT_ADDRESSED_TO_PARENT_SENDER")
            if rec["project_item_id"] != parent["project_item_id"]:
                problems.append("PROJECT_ITEM_MISMATCH")
        if rec["event_class"] == "ACK":
            if parent["event_class"] not in ACK_PARENTS:
                problems.append("INVALID_ACK_PARENT")
            key = (parent_id, rec["source_role"] or "")
            if key in acks:
                problems.append("DUPLICATE_ACK")
            else:
                acks[key] = rec
        if not problems:
            rec["correlation"] = "CORRELATED"
        elif parent["protocol"] == "REPORT_DELIVERY_V1" and problems == ["PARENT_HAS_NO_ROLES"]:
            rec["correlation"] = "ID_ONLY_NO_ROLES"
            rec["warnings"].extend(problems)
        elif rec["event_class"] == "ACK":
            # Only an ACK claims receipt, so only an ACK must match exactly.
            rec["correlation"] = "MISMATCH"
            rec["blocking"].extend(problems)
        else:
            # Observed use: in_reply_to also threads a sender's own follow-ups
            # or cites a related item. Kept as a reference, never as receipt.
            rec["correlation"] = ("SELF_CONTINUATION" if rec["source_role"]
                                  == parent["source_role"] else "LOOSE_REFERENCE")
            rec["warnings"].extend(problems)

    # A reply that later cites an ACK is the only public sign that the original
    # sender re-read it. It is still not proof that its scheduled task did so.
    reread = {r["in_reply_to"] for r in by_id.values() if r["in_reply_to"]}
    for rec in by_id.values():
        if rec["event_class"] == "ACK" and rec.get("correlation") == "CORRELATED":
            rec["ack_reread_observed"] = rec["message_id"] in reread

    tamper = []
    if baseline is not None:
        now_by_cid = {r["comment_id"]: r for r in records}
        for old in baseline:
            cid = old.get("id")
            old_sha = hashlib.sha256(str(old.get("body") or "").encode("utf-8")).hexdigest()
            cur = now_by_cid.get(cid)
            if cur is None:
                tamper.append({"comment_id": cid, "finding": "DELETED_SINCE_BASELINE"})
            elif cur["body_sha256"] != old_sha:
                tamper.append({"comment_id": cid, "finding": "MODIFIED_SINCE_BASELINE"})

    # Messages a sender believes it sent (e.g. a #447 outbox SEND_UNKNOWN row).
    # Absence on the Issue is NOT failure and NEVER permission to resend.
    delivery = {}
    for mid in expected_message_ids or []:
        delivery[mid] = "OBSERVED_ON_ISSUE" if mid in by_id else "SEND_UNKNOWN_NOT_OBSERVED"

    return {
        "status": "READ_ONLY_COMPAT_CHECK",
        "messages": records,
        "role_matrix": role_matrix(records),
        "protocol_counts": _count(r["protocol"] for r in records),
        "tamper_findings": tamper,
        "expected_delivery": delivery,
        "sender_role_authenticated": False,
        "end_to_end_verified": False,
        "retry_allowed": False,
        "real_submit_allowed": False,
    }


def _count(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return dict(sorted(out.items()))


def role_matrix(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per declared role: what the public Issue shows, never more."""
    matrix: dict[str, dict[str, Any]] = {}
    for role in sorted(LIVE_ROLES - {"owner"}):
        sent = [r for r in records if r["source_role"] == role and not r["blocking"]]
        addressed = [r for r in records if role in r["recipient_roles"] and not r["blocking"]]
        acks = [r for r in sent if r["event_class"] == "ACK" and r.get("correlation") == "CORRELATED"]
        replies = [r for r in sent if r.get("correlation") == "CORRELATED"]
        unanswered = [r for r in addressed if r["event_class"] in {"ASSIGN", "REPORT", "RESULT", "REVIEW"}
                      and not any(x["in_reply_to"] == r["message_id"] and x["source_role"] == role
                                  for x in records)]
        matrix[role] = {
            "messages_claimed": len(sent),
            "last_claimed_at": sent[-1]["created_at"] if sent else None,
            "channels": _count(r["posting_channel"] for r in sent),
            "addressed_to_role": len(addressed),
            "unanswered_addressed": len(unanswered),
            "correlated_replies": len(replies),
            "correlated_acks": len(acks),
            # ACKs addressed to this role that this role later cited.
            "ack_reread_observed": sum(1 for r in records if r.get("ack_reread_observed")
                                       and role in r["recipient_roles"]),
            "write": "CLAIMED_UNVERIFIED" if sent else "NOT_OBSERVED",
            "role_authentication": "UNVERIFIED",
            "scheduled_e2e": "UNKNOWN",
        }
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Issue #282 compatibility check")
    parser.add_argument("comments_json", help="Locally saved GitHub issue comments (list)")
    parser.add_argument("--baseline", help="An earlier saved copy to detect edits/deletions")
    parser.add_argument("--expected", action="append", default=[],
                        help="message_id a sender believes it sent (repeatable)")
    parser.add_argument("--since", help="Only messages created at/after this ISO time")
    parser.add_argument("--summary", action="store_true", help="Omit per-message records")
    args = parser.parse_args()
    comments = json.loads(Path(args.comments_json).read_text(encoding="utf-8"))
    if not isinstance(comments, list):
        parser.error("expected a JSON list of issue comments")
    if args.since:
        comments = [c for c in comments if str(c.get("created_at") or "") >= args.since]
    baseline = (json.loads(Path(args.baseline).read_text(encoding="utf-8"))
                if args.baseline else None)
    result = reconcile(comments, baseline=baseline, expected_message_ids=args.expected)
    if args.summary:
        result.pop("messages")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
