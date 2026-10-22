"""Offline private GNH01 -> local PRE-NEXT *review reader* handoff.

No network/Grok Routine, no ChatGPT Task invocation, no Brain/Shadow/broker.
Sender HMAC proves configured local key possession, NOT Grok identity or
source authenticity. Local reader ACK is NOT a scheduled PRE-NEXT Task ACK.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat

from scripts.gnh01_intelligence_contract_v1 import (
    canonical_bytes, IDENT, HEX64, parse_event_json_bytes, ContractBlocked,
)
from scripts.gnh01_durable_archive_v1 import ArchiveBlocked, _path, _utc
from scripts.gnh01_pre_next_review_v1 import (
    SCHEMA_VERSION as REVIEW_SCHEMA, build_pre_next_review_request,
)

ENVELOPE_SCHEMA = "100b-gnh01-private-review-envelope-v1"
ACK_SCHEMA = "100b-gnh01-local-reader-ack-v1"
SENDER_KEY = "GNH01_PRENEXT_REVIEW_HMAC_KEY"
READER_KEY = "GNH01_PRENEXT_READER_ACK_HMAC_KEY"
MAX_BYTES = 64_000
MAX_AGE = timedelta(minutes=15)
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
NAME_RE = re.compile(r"^gnh01_review_([A-Za-z0-9_-]{3,96})_([1-9][0-9]{0,6})_([0-9a-f]{12})\.json$")
REVIEW_KEYS = frozenset({
    "schema_version", "state", "source_role", "sender_role_authenticated",
    "grok_direct_emission_verified", "origin_transport_verified",
    "intended_recipient_role", "event_id", "event_revision",
    "event_content_sha256", "source_url_unverified", "original_issuer_claim",
    "event_title_claim", "event_summary_claim", "published_at_claim",
    "grok_first_seen_at_claim", "original_evidence_status_claim",
    "novelty_status_claim", "related_japanese_stocks_claim",
    "local_archived_at", "source_authenticity_verified",
    "ticker_identity_verified", "publication_available_at_verified",
    "brain_trade_decision_eligible", "shadow_eligible",
    "pre_next_delivery_verified", "pre_next_ack_verified",
    "real_submit_allowed",
})
UNTRUSTED_FALSE = (
    "sender_role_authenticated", "grok_direct_emission_verified",
    "origin_transport_verified", "source_authenticity_verified",
    "ticker_identity_verified", "publication_available_at_verified",
    "brain_trade_decision_eligible", "shadow_eligible",
    "pre_next_delivery_verified", "pre_next_ack_verified",
    "real_submit_allowed",
)


class HandoffBlocked(ValueError):
    """Fail-closed reason: never include secret or news text in diagnostics."""


def _root(folder):
    """Use existing archive path guard; deployment must independently check ACLs."""
    try:
        root = Path(folder)
        return _path(root / ".gnh01_private_root_guard").parent
    except (ArchiveBlocked, OSError, TypeError, ValueError) as exc:
        raise HandoffBlocked("PRIVATE_HANDOFF_FOLDER_UNSAFE") from exc


def _key(envname: str) -> bytes:
    value = os.environ.get(envname, "")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise HandoffBlocked("PRIVATE_HMAC_KEY_MISSING_OR_INVALID")
    return bytes.fromhex(value)


def _sig(key: bytes, purpose: bytes, payload: dict) -> str:
    return hmac.new(key, purpose + canonical_bytes(payload), hashlib.sha256).hexdigest()


def _dt(value: str) -> datetime:
    if not isinstance(value, str):
        raise HandoffBlocked("HANDOFF_TIMESTAMP_INVALID")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffBlocked("HANDOFF_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise HandoffBlocked("HANDOFF_TIMESTAMP_NOT_UTC")
    return dt.astimezone(timezone.utc)


def _validate_review(value: dict) -> None:
    if type(value) is not dict or set(value) != REVIEW_KEYS:
        raise HandoffBlocked("REVIEW_FIELDS_INVALID")
    if (value["schema_version"] != REVIEW_SCHEMA
            or value["state"] != "SOURCE_REVIEW_REQUIRED"
            or value["intended_recipient_role"] != "pre_next"
            or value["source_role"] not in ("grok_bot_gnh01", "owner_instruction_relay")
            or any(value[k] is not False for k in UNTRUSTED_FALSE)):
        raise HandoffBlocked("REVIEW_SAFETY_STATE_INVALID")
    if (type(value["event_id"]) is not str
            or not IDENT.fullmatch(value["event_id"])
            or type(value["event_revision"]) is not int
            or not 1 <= value["event_revision"] <= 1_000_000
            or type(value["event_content_sha256"]) is not str
            or not HEX64.fullmatch(value["event_content_sha256"])):
        raise HandoffBlocked("REVIEW_ID_INVALID")
    if not isinstance(value["source_url_unverified"], str) or not value["source_url_unverified"].startswith("https://"):
        raise HandoffBlocked("REVIEW_SOURCE_URL_INVALID")
    if type(value["related_japanese_stocks_claim"]) is not list:
        raise HandoffBlocked("REVIEW_STOCK_CLAIM_INVALID")
    _dt(value["local_archived_at"])


def _name(review):
    return ("gnh01_review_" + review["event_id"] + "_" +
            str(review["event_revision"]) + "_" +
            review["event_content_sha256"][:12] + ".json")


def _strict_json(raw: bytes):
    if type(raw) is not bytes or not 2 <= len(raw) <= MAX_BYTES:
        raise HandoffBlocked("HANDOFF_JSON_SIZE_INVALID")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise HandoffBlocked("HANDOFF_JSON_DUPLICATE_KEY")
            result[k] = v
        return result

    def reject(_):
        raise HandoffBlocked("HANDOFF_JSON_NONFINITE")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=reject, parse_float=reject)
    except HandoffBlocked:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise HandoffBlocked("HANDOFF_JSON_INVALID") from exc


def _write_once(path: Path, raw: bytes):
    if len(raw) > MAX_BYTES:
        raise HandoffBlocked("HANDOFF_TOO_LARGE")
    if path.exists() or path.is_symlink():
        raise HandoffBlocked("HANDOFF_ALREADY_EXISTS")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        raise HandoffBlocked("HANDOFF_ALREADY_EXISTS") from exc
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        # Do not delete a possibly-written message; uncertain writes must not retry.
        raise


def _read_once(path: Path, root: Path):
    if path.parent != root or path.is_symlink() or not path.is_file():
        raise HandoffBlocked("HANDOFF_PATH_INVALID")
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or not 2 <= before.st_size <= MAX_BYTES):
        raise HandoffBlocked("HANDOFF_FILE_INVALID")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
        middle = os.fstat(handle.fileno())
    after = path.lstat()
    fingerprint = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_nlink)
    if (len(raw) != before.st_size or fingerprint(before) != fingerprint(middle)
            or fingerprint(before) != fingerprint(after)):
        raise HandoffBlocked("HANDOFF_CHANGED_DURING_READ")
    return raw


def export_review(db_path, event: dict, *, private_dir, now: datetime) -> Path:
    """Exclusive write of an unverified research request; no recipient ACK."""
    root = _root(private_dir)
    at = _utc(lambda: now)
    review = build_pre_next_review_request(db_path, event, now=at)
    _validate_review(review)
    if at - _dt(review["local_archived_at"]) > timedelta(hours=2):
        raise HandoffBlocked("ARCHIVE_STALE")
    sender_key = _key(SENDER_KEY)
    payload = {
        "review": review, "emitted_at": at.isoformat(),
        "producer_kind": "LOCAL_ARCHIVE_EXPORTER_NOT_GROK",
        "recipient": "pre_next", "real_submit_allowed": False,
    }
    body = {
        "schema_version": ENVELOPE_SCHEMA, "payload": payload,
        "hmac_sha256": _sig(sender_key, b"100B:GNH01:REVIEW:V1\n", payload),
    }
    target = root / _name(review)
    _write_once(target, canonical_bytes(body) + b"\n")
    return target


def receive_review(path, *, private_dir, now: datetime) -> dict:
    """Local independent reader: signed ACK does NOT imply a ChatGPT Task read."""
    root = _root(private_dir)
    at = _utc(lambda: now)
    target = Path(path)
    if not NAME_RE.fullmatch(target.name):
        raise HandoffBlocked("HANDOFF_FILENAME_INVALID")
    raw = _read_once(target, root)
    body = _strict_json(raw)
    if type(body) is not dict or set(body) != {
        "schema_version", "payload", "hmac_sha256"
    } or body["schema_version"] != ENVELOPE_SCHEMA:
        raise HandoffBlocked("ENVELOPE_SCHEMA_INVALID")
    payload = body["payload"]
    if type(payload) is not dict or set(payload) != {
        "review", "emitted_at", "producer_kind", "recipient", "real_submit_allowed"
    }:
        raise HandoffBlocked("ENVELOPE_FIELDS_INVALID")
    signature = body["hmac_sha256"]
    if type(signature) is not str or not DIGEST_RE.fullmatch(signature):
        raise HandoffBlocked("SIGNATURE_FORMAT_INVALID")
    if not hmac.compare_digest(
        _sig(_key(SENDER_KEY), b"100B:GNH01:REVIEW:V1\n", payload), signature
    ):
        raise HandoffBlocked("HANDOFF_AUTHENTICATION_FAILED")
    if (payload["producer_kind"] != "LOCAL_ARCHIVE_EXPORTER_NOT_GROK"
            or payload["recipient"] != "pre_next"
            or payload["real_submit_allowed"] is not False):
        raise HandoffBlocked("ENVELOPE_SAFETY_INVALID")
    review = payload["review"]
    _validate_review(review)
    if target.name != _name(review):
        raise HandoffBlocked("HANDOFF_FILENAME_CONTENT_MISMATCH")
    emitted = _dt(payload["emitted_at"])
    archived = _dt(review["local_archived_at"])
    if (emitted > at or at - emitted > MAX_AGE
            or archived > emitted or emitted - archived > timedelta(hours=2)):
        raise HandoffBlocked("HANDOFF_STALE_OR_FUTURE")
    key = _key(READER_KEY)
    if key == _key(SENDER_KEY):
        raise HandoffBlocked("READER_AND_SENDER_KEYS_MUST_DIFFER")
    ack = {
        "schema_version": ACK_SCHEMA,
        "ack_kind": "LOCAL_READER_ONLY_NOT_CHATGPT_PRE_NEXT",
        "event_id": review["event_id"],
        "event_revision": review["event_revision"],
        "event_content_sha256": review["event_content_sha256"],
        "envelope_sha256": hashlib.sha256(raw).hexdigest(),
        "received_at": at.isoformat(),
        "state": "LOCAL_REVIEW_READER_ACK_ONLY",
        "pre_next_scheduled_task_ack": False,
        "source_authenticity_verified": False,
        "brain_received": False,
        "shadow_eligible": False,
        "real_submit_allowed": False,
    }
    ack_signed = {
        "schema_version": ACK_SCHEMA, "payload": ack,
        "hmac_sha256": _sig(key, b"100B:GNH01:LOCAL-ACK:V1\n", ack),
    }
    ack_path = target.with_name(target.stem + ".ack.json")
    _write_once(ack_path, canonical_bytes(ack_signed) + b"\n")
    # Independently reopen the ACK and verify its HMAC, exact content and origin.
    actual = _strict_json(_read_once(ack_path, root))
    if (actual != ack_signed or type(actual) is not dict
            or not hmac.compare_digest(
                _sig(key, b"100B:GNH01:LOCAL-ACK:V1\n", actual["payload"]),
                actual["hmac_sha256"],
            )):
        raise HandoffBlocked("ACK_INDEPENDENT_READBACK_FAILED")
    return dict(ack, signed_ack_independently_read_back=True,
                ack_path=str(ack_path))


def verify_local_ack(path, *, private_dir) -> dict:
    """Inspect a recorded local ACK without implying task or Brain receipt."""
    root = _root(private_dir)
    target = Path(path)
    if not target.name.endswith(".ack.json"):
        raise HandoffBlocked("ACK_FILENAME_INVALID")
    obj = _strict_json(_read_once(target, root))
    if (type(obj) is not dict or set(obj) != {"schema_version", "payload", "hmac_sha256"}
            or obj["schema_version"] != ACK_SCHEMA):
        raise HandoffBlocked("ACK_SCHEMA_INVALID")
    ack = obj["payload"]
    if (type(ack) is not dict or ack.get("schema_version") != ACK_SCHEMA
            or ack.get("ack_kind") != "LOCAL_READER_ONLY_NOT_CHATGPT_PRE_NEXT"
            or ack.get("state") != "LOCAL_REVIEW_READER_ACK_ONLY"
            or any(ack.get(k) is not False for k in (
                "pre_next_scheduled_task_ack", "source_authenticity_verified",
                "brain_received", "shadow_eligible", "real_submit_allowed"
            ))):
        raise HandoffBlocked("ACK_SAFETY_INVALID")
    expected = _sig(_key(READER_KEY), b"100B:GNH01:LOCAL-ACK:V1\n", ack)
    if (type(obj["hmac_sha256"]) is not str
            or not hmac.compare_digest(expected, obj["hmac_sha256"])):
        raise HandoffBlocked("ACK_AUTHENTICATION_FAILED")
    return dict(ack, signed_ack_independently_read_back=True)
