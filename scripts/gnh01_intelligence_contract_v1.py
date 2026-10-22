"""Offline, research-only GNH01 event contract; never imports a broker or API client.

This validates a *claim* from an external sender. Passing validation does not
prove the source is authentic, nor does it grant Brain/Shadow trade eligibility.
PROJECT_ITEM_ID: P0-GLOBAL-INTELLIGENCE-TO-SHADOW-INTEGRATION-20261022
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit

SCHEMA_VERSION = "intelligence_event_v1"
LANE = "PUBLIC_RESEARCH_UNAUTHENTICATED_NOT_EXECUTION"
REQUIRED = frozenset({
    "schema_version", "event_id", "source_role", "original_source_url",
    "original_issuer", "event_type", "affected_region", "published_at",
    "provider_available_at", "grok_first_seen_at", "grok_reported_at",
    "bridge_received_at", "event_title", "event_summary",
    "related_japanese_stocks", "evidence_status", "novelty_status",
    "content_hash", "event_revision", "data_lane", "real_submit_allowed",
})
# Delivery-time fields are intentionally excluded: a retry must not change
# content identity. Any changed source assertion requires a new revision.
CONTENT_FIELDS = frozenset(REQUIRED - {
    "content_hash", "bridge_received_at", "grok_reported_at",
})
EVIDENCE = frozenset({
    "PRIMARY_VERIFIED", "SECONDARY_VERIFIED", "UNVERIFIED", "CONTRADICTED",
    "STALE", "INVALIDATED",
})
NOVELTY = frozenset({
    "TRUE_NEW", "MATERIAL_UPDATE", "MISSED_PREVIOUS", "RECONFIRMATION",
})
EVENT_TYPES = frozenset({"NEWS", "IR", "PUBLIC_SOCIAL", "MACRO", "CORRECTION"})
SOURCE_ROLES = frozenset({"grok_bot_gnh01", "owner_instruction_relay"})
UTC_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$")
IDENT = re.compile(r"^[A-Za-z0-9_-]{3,96}$")
TICKER = re.compile(r"^(?:\d{4}|\d{3}[A-Z])(?:\.T)?$")
HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_EVENT_JSON_BYTES = 64_000


class ContractBlocked(ValueError):
    """A deterministic fail-closed reason; not an execution signal."""


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_digest(event: dict) -> str:
    return hashlib.sha256(canonical_bytes({k: event[k] for k in CONTENT_FIELDS})).hexdigest()


def parse_event_json_bytes(raw: bytes) -> dict:
    """Strict bounded JSON for a future external adapter; no network or trust.

    json.loads normally keeps only the last duplicate key and accepts NaN/Inf.
    Both can conceal sender assertions or create inconsistent content hashes.
    The GNH01 schema has no floating-point values at any nesting level.
    """
    if type(raw) is not bytes or not 2 <= len(raw) <= MAX_EVENT_JSON_BYTES:
        raise ContractBlocked("EVENT_JSON_SIZE_OR_TYPE_INVALID")

    def unique_keys(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ContractBlocked("JSON_DUPLICATE_KEY")
            obj[k] = v
        return obj

    def reject_noninteger(_):
        raise ContractBlocked("JSON_NONFINITE_OR_FLOAT_BLOCKED")

    try:
        obj = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_keys,
            parse_float=reject_noninteger,
            parse_constant=reject_noninteger,
        )
    except ContractBlocked:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise ContractBlocked("EVENT_JSON_INVALID") from exc
    if type(obj) is not dict:
        raise ContractBlocked("EVENT_FIELDS_INVALID")
    return obj


def _clock(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not UTC_ISO.fullmatch(value):
        raise ContractBlocked("UTC_TIMESTAMP_REQUIRED")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractBlocked("TIMESTAMP_INVALID") from exc
    if moment.utcoffset() != timedelta(0):
        raise ContractBlocked("UTC_TIMESTAMP_REQUIRED")
    return moment.astimezone(timezone.utc)


def _public_url(raw):
    if not isinstance(raw, str) or not 12 <= len(raw) <= 600 or raw != raw.strip():
        raise ContractBlocked("SOURCE_URL_INVALID")
    if any(ord(c) <= 32 or ord(c) == 127 or c == "\\" for c in raw):
        raise ContractBlocked("SOURCE_URL_INVALID")
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password
                or parsed.port is not None or parsed.query or parsed.fragment
                or not parsed.path.startswith("/") or not parsed.netloc.isascii()):
            raise ContractBlocked("PUBLIC_HTTPS_SOURCE_REQUIRED")
        host = host.lower()
        if (host in {"localhost", "localhost.localdomain"}
                or host.endswith((".local", ".internal", ".localhost"))
                or "." not in host or any(not HOST_LABEL.fullmatch(p) for p in host.split("."))):
            raise ContractBlocked("PUBLIC_HTTPS_SOURCE_REQUIRED")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ContractBlocked("PUBLIC_HTTPS_SOURCE_REQUIRED")
    except ContractBlocked:
        raise
    except ValueError as exc:
        raise ContractBlocked("SOURCE_URL_INVALID") from exc


def _text(value, *, limit):
    return (isinstance(value, str) and 1 <= len(value) <= limit
            and all(ord(c) >= 32 or c == "\n" for c in value))


def validate_event(event: dict, *, now: datetime) -> dict:
    """Validate immutable event content, provenance timestamps, and no-order flag.

    The returned state is archival research only; PRIMARY_VERIFIED is an
    *untrusted sender assertion* until an independent verifier attests it.
    """
    if type(event) is not dict or set(event) != REQUIRED:
        raise ContractBlocked("EVENT_FIELDS_INVALID")
    if (event["schema_version"] != SCHEMA_VERSION
            or event["data_lane"] != LANE
            or event["real_submit_allowed"] is not False):
        raise ContractBlocked("SCHEMA_OR_SAFETY_GATE_INVALID")
    if (not isinstance(event["event_id"], str)
            or not IDENT.fullmatch(event["event_id"])
            or type(event["event_revision"]) is not int
            or not 1 <= event["event_revision"] <= 1_000_000):
        raise ContractBlocked("EVENT_ID_OR_REVISION_INVALID")
    if (any(type(event[k]) is not str for k in ("source_role", "event_type",
             "evidence_status", "novelty_status"))
            or event["source_role"] not in SOURCE_ROLES
            or event["event_type"] not in EVENT_TYPES
            or event["evidence_status"] not in EVIDENCE
            or event["novelty_status"] not in NOVELTY):
        raise ContractBlocked("EVENT_ENUM_INVALID")
    _public_url(event["original_source_url"])
    for field, limit in (("original_issuer", 160), ("affected_region", 80),
                         ("event_title", 240), ("event_summary", 2000)):
        if not _text(event[field], limit=limit):
            raise ContractBlocked("EVENT_TEXT_INVALID")
    stocks = event["related_japanese_stocks"]
    if type(stocks) is not list or len(stocks) > 20:
        raise ContractBlocked("STOCK_LIST_INVALID")
    seen = set()
    for row in stocks:
        if (type(row) is not dict or set(row) != {"security_code", "official_company_name"}
                or not isinstance(row["security_code"], str)
                or not TICKER.fullmatch(row["security_code"])
                or not _text(row["official_company_name"], limit=120)):
            raise ContractBlocked("STOCK_IDENTITY_INVALID")
        # Japanese tickers may be supplied with or without the .T suffix.
        # Treat 285A and 285A.T as the same security, not two stocks.
        normalized_code = row["security_code"].removesuffix(".T")
        if normalized_code in seen:
            raise ContractBlocked("STOCK_IDENTITY_INVALID")
        seen.add(normalized_code)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ContractBlocked("LOCAL_CLOCK_UNVERIFIED")
    now = now.astimezone(timezone.utc)
    times = {name: _clock(event[name], required=(name == "bridge_received_at"))
             for name in ("published_at", "provider_available_at", "grok_first_seen_at",
                          "grok_reported_at", "bridge_received_at")}
    if any(t > now + timedelta(seconds=5) for t in times.values() if t is not None):
        raise ContractBlocked("FUTURE_EVENT_TIMESTAMP")
    received = times["bridge_received_at"]
    if any(t > received for k, t in times.items() if k != "bridge_received_at" and t):
        raise ContractBlocked("LOOKAHEAD_TIMESTAMP")
    if times["published_at"] and any(
        t < times["published_at"] for k, t in times.items()
        if k not in {"published_at"} and t is not None
    ):
        raise ContractBlocked("PUBLICATION_SEQUENCE_INVALID")
    if (times["grok_first_seen_at"] and times["grok_reported_at"]
            and times["grok_first_seen_at"] > times["grok_reported_at"]):
        raise ContractBlocked("GROK_SEQUENCE_INVALID")
    if not isinstance(event["content_hash"], str) or not HEX64.fullmatch(event["content_hash"]):
        raise ContractBlocked("CONTENT_HASH_FORMAT_INVALID")
    if content_digest(event) != event["content_hash"]:
        raise ContractBlocked("CONTENT_HASH_MISMATCH")
    # An upstream-supplied bridge_received_at is an untrusted claim. It is
    # NOT a point-in-time receipt. Only a separate durable receiver receipt
    # can establish an independently verified available_at.
    return {"state": "ARCHIVE_RESEARCH_ONLY", "event_id": event["event_id"],
            "event_revision": event["event_revision"],
            "content_hash": event["content_hash"],
            "available_at": None,
            "claimed_bridge_received_at": received.isoformat(),
            "available_at_verified": False,
            "source_authenticity_verified": False,
            "stock_identity_verified": False,
            "brain_receiver_ack_verified": False,
            "shadow_eligible": False, "real_submit_allowed": False}