"""GNH01 -> PRE-NEXT *review request*, NOT an automatically delivered signal.

The converter reads the independent local archive receipt on each invocation.
It does not claim source authenticity, external clock attestation, PRE-NEXT
delivery, Agents SDK snapshot compatibility, Brain receipt or Shadow eligibility.
The output is a pure in-memory record; no scheduler, network, broker or write.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from scripts.gnh01_intelligence_contract_v1 import (
    ContractBlocked, validate_event,
)
from scripts.gnh01_durable_archive_v1 import (
    ArchiveBlocked, read_archive_receipt,
)

SCHEMA_VERSION = "100b-gnh01-pre-next-review-request-v1"
MAX_ARCHIVE_AGE = timedelta(hours=2)


def build_pre_next_review_request(db_path, event: dict, *, now: datetime) -> dict:
    """Return a deterministic *unverified* research request for an archived event.

    No field is compatible with the executable/verified Brain handoff envelope
    by accident. The recipient must independently authenticate, validate issuer
    and ticker identity, verify source availability, and reply with real ACK.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ArchiveBlocked("LOCAL_CLOCK_UNVERIFIED")
    observed = now.astimezone(timezone.utc)
    try:
        claimed = validate_event(event, now=observed)
    except ContractBlocked as exc:
        raise ArchiveBlocked(str(exc)) from exc

    receipt = read_archive_receipt(
        db_path, claimed["event_id"], claimed["event_revision"]
    )
    if (receipt["state"] != "ARCHIVED"
            or receipt["content_hash"] != claimed["content_hash"]
            or receipt["available_at"] is None
            or receipt["real_submit_allowed"] is not False):
        raise ArchiveBlocked("ARCHIVE_CONTENT_OR_STATUS_MISMATCH")

    # Only local observation freshness is checked. It is not an assertion
    # that the source was available at that instant.
    try:
        at = datetime.fromisoformat(receipt["received_at"])
        persisted = datetime.fromisoformat(receipt["available_at"])
        if at.utcoffset() != timedelta(0) or persisted.utcoffset() != timedelta(0):
            raise ValueError("untrusted timestamp offset")
    except (TypeError, ValueError, AttributeError) as exc:
        raise ArchiveBlocked("RECEIVER_TIMESTAMP_INVALID") from exc
    age = observed - persisted
    if (age < timedelta(0) or age > MAX_ARCHIVE_AGE
            or persisted < at):
        raise ArchiveBlocked("ARCHIVE_STALE_OR_FUTURE")

    # This exact envelope intentionally does NOT conform to
    # 100b-public-agent-evidence-v1: that contract requires a trustworthy
    # available_at and a specialist research result. Those do not exist here.
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "SOURCE_REVIEW_REQUIRED",
        "source_role": "grok_bot_gnh01",
        "intended_recipient_role": "pre_next",
        "event_id": claimed["event_id"],
        "event_revision": claimed["event_revision"],
        "event_content_sha256": claimed["content_hash"],
        "source_url_unverified": event["original_source_url"],
        "original_issuer_claim": event["original_issuer"],
        "event_title_claim": event["event_title"],
        "event_summary_claim": event["event_summary"],
        "published_at_claim": event["published_at"],
        "grok_first_seen_at_claim": event["grok_first_seen_at"],
        "original_evidence_status_claim": event["evidence_status"],
        "novelty_status_claim": event["novelty_status"],
        "related_japanese_stocks_claim": event["related_japanese_stocks"],
        "local_archived_at": receipt["available_at"],
        "source_authenticity_verified": False,
        "ticker_identity_verified": False,
        "publication_available_at_verified": False,
        "brain_trade_decision_eligible": False,
        "shadow_eligible": False,
        "pre_next_delivery_verified": False,
        "pre_next_ack_verified": False,
        "real_submit_allowed": False,
    }
