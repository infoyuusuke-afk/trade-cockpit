"""GNH01 offline delivery-chain audit: local evidence, NOT cloud E2E.

Read-only, independently reopens durable archive, private signed review,
and signed local reader-only ACK. Never invokes ChatGPT Tasks, Grok,
PRE-NEXT cloud account, Brain, V10, broker or scheduler.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path

from scripts.gnh01_durable_archive_v1 import ArchiveBlocked, _utc, read_archive_receipt
from scripts.gnh01_pre_next_review_v1 import build_pre_next_review_request
from scripts.gnh01_private_review_handoff_v1 import (
    ACK_SCHEMA, ENVELOPE_SCHEMA, HandoffBlocked, MAX_AGE, READER_KEY,
    SENDER_KEY, _dt, _key, _name, _read_once, _root, _sig,
    _strict_json, _validate_review, verify_local_ack,
)

EXPECTED_ACK_FIELDS = frozenset({
    "schema_version", "ack_kind", "event_id", "event_revision",
    "event_content_sha256", "envelope_sha256", "received_at", "state",
    "pre_next_scheduled_task_ack", "source_authenticity_verified",
    "brain_received", "shadow_eligible", "real_submit_allowed",
})


def audit_local_chain(db_path, event: dict, *, private_dir, now: datetime) -> dict:
    """Reject missing, stale, mismatched or forged LOCAL chain components.

    A successful result establishes only a matched LOCAL synthetic chain.
    A malicious operator with both HMAC keys can forge a chain, so no
    external sender identity or live-scheduled-task attestation is inferred.
    """
    try:
        at = _utc(lambda: now)
    except ArchiveBlocked as exc:
        raise HandoffBlocked(str(exc)) from exc
    root = _root(private_dir)
    # Independently reads the archive and validates the immutable event
    # revision/content identity before looking at the transport.
    expected = build_pre_next_review_request(db_path, event, now=at)
    _validate_review(expected)
    archive = read_archive_receipt(
        db_path, expected["event_id"], expected["event_revision"]
    )
    if (archive["state"] != "ARCHIVED"
            or archive["available_at"] != expected["local_archived_at"]
            or archive["content_hash"] != expected["event_content_sha256"]
            or archive["real_submit_allowed"] is not False):
        raise HandoffBlocked("ARCHIVE_CHAIN_MISMATCH")

    envelope_path = root / _name(expected)
    try:
        envelope_raw = _read_once(envelope_path, root)
    except (OSError, ValueError) as exc:
        raise HandoffBlocked("ENVELOPE_NOT_DURABLE_OR_INVALID") from exc
    envelope = _strict_json(envelope_raw)
    if (type(envelope) is not dict or set(envelope) != {
            "schema_version", "payload", "hmac_sha256"
        } or envelope.get("schema_version") != ENVELOPE_SCHEMA):
        raise HandoffBlocked("ENVELOPE_SCHEMA_INVALID")
    payload = envelope["payload"]
    if (type(payload) is not dict or set(payload) != {
            "review", "emitted_at", "producer_kind", "recipient",
            "real_submit_allowed"
        } or payload["review"] != expected):
        raise HandoffBlocked("ENVELOPE_ARCHIVE_CONTENT_MISMATCH")
    _validate_review(payload["review"])
    if (payload["producer_kind"] != "LOCAL_ARCHIVE_EXPORTER_NOT_GROK"
            or payload["recipient"] != "pre_next"
            or payload["real_submit_allowed"] is not False):
        raise HandoffBlocked("ENVELOPE_SAFETY_INVALID")
    digest = envelope["hmac_sha256"]
    if (type(digest) is not str or len(digest) != 64
            or not hmac.compare_digest(
                _sig(_key(SENDER_KEY), b"100B:GNH01:REVIEW:V1\n", payload),
                digest,
            )):
        raise HandoffBlocked("ENVELOPE_SIGNATURE_INVALID")

    emitted = _dt(payload["emitted_at"])
    archived = _dt(expected["local_archived_at"])
    if (not archived <= emitted <= at
            or at - emitted > MAX_AGE
            or emitted - archived > timedelta(hours=2)):
        raise HandoffBlocked("ENVELOPE_STALE_OR_FUTURE")

    ack_path = envelope_path.with_name(envelope_path.stem + ".ack.json")
    try:
        local_ack = verify_local_ack(ack_path, private_dir=root)
    except (OSError, ValueError) as exc:
        raise HandoffBlocked("ACK_NOT_DURABLE_OR_INVALID") from exc
    if set(local_ack) != EXPECTED_ACK_FIELDS | {"signed_ack_independently_read_back"}:
        raise HandoffBlocked("ACK_FIELDS_INVALID")
    if (local_ack["schema_version"] != ACK_SCHEMA
            or local_ack["event_id"] != expected["event_id"]
            or local_ack["event_revision"] != expected["event_revision"]
            or local_ack["event_content_sha256"] != expected["event_content_sha256"]
            or local_ack["envelope_sha256"] != hashlib.sha256(envelope_raw).hexdigest()
            or local_ack["real_submit_allowed"] is not False
            or local_ack["signed_ack_independently_read_back"] is not True):
        raise HandoffBlocked("ACK_ENVELOPE_IDENTITY_MISMATCH")
    local_received = _dt(local_ack["received_at"])
    if (not emitted <= local_received <= at
            or local_received - emitted > MAX_AGE):
        raise HandoffBlocked("ACK_STALE_OR_FUTURE")

    # All below are LOCAL observations. Do not set E2E/PRE/BRAIN success flags.
    return {
        "state": "LOCAL_CHAIN_MATCH_RESEARCH_ONLY",
        "event_id": expected["event_id"],
        "event_revision": expected["event_revision"],
        "content_hash": expected["event_content_sha256"],
        "local_archive_readback_verified": True,
        "local_signed_review_verified": True,
        "local_signed_reader_ack_verified": True,
        "sender_role_authenticated": False,
        "grok_unattended_routine_verified": False,
        "grok_direct_emission_verified": False,
        "pre_next_scheduled_task_delivery_verified": False,
        "pre_next_scheduled_task_ack_verified": False,
        "source_authenticity_verified": False,
        "brain_receiver_ack_verified": False,
        "shadow_eligible": False,
        "real_submit_allowed": False,
    }
