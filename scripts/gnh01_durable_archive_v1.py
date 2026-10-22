"""GNH01 durable *archive-only* receipt, isolated from V10 and broker paths.

A sender's bridge_received_at and evidence_status are untrusted claims.
A local SQLite commit/readback creates an auditable receiver-side observation,
NOT clock/NTP attestation, authenticated Grok delivery, or trading eligibility.
No network, background scheduler, order or model API is used.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable

from scripts.gnh01_intelligence_contract_v1 import (
    ContractBlocked, canonical_bytes, content_digest, validate_event,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS grok_archive_v1 (
    event_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    received_at TEXT NOT NULL,
    available_at TEXT,
    state TEXT NOT NULL CHECK (state IN ('PENDING','ARCHIVED')),
    PRIMARY KEY (event_id, revision)
);
"""


class ArchiveBlocked(ValueError):
    """Stable fail-closed diagnostic without exposing payloads or filesystem paths."""


def _utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ArchiveBlocked("RECEIVER_CLOCK_UNVERIFIED")
    return value.astimezone(timezone.utc)


def _path(db_path) -> Path:
    p = Path(db_path)
    if (not p.is_absolute() or not p.parent.is_dir() or p.is_symlink()
            or (p.exists() and not p.is_file())):
        raise ArchiveBlocked("PRIVATE_STORAGE_PATH_REQUIRED")
    return p


def _connect(path: Path, *, initialize=False):
    if not initialize and not path.is_file():
        raise ArchiveBlocked("ARCHIVE_NOT_FOUND")
    con = sqlite3.connect(str(path), timeout=5, isolation_level="IMMEDIATE")
    con.execute("PRAGMA busy_timeout=5000")
    if initialize:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute(_SCHEMA)
        con.commit()
    return con


def _read(path: Path, event_id: str, revision: int) -> dict:
    """Independent new connection: never trust a writer's return value alone."""
    con = _connect(path)
    try:
        row = con.execute(
            "SELECT event_id,revision,content_hash,payload_json,payload_sha256,"
            "received_at,available_at,state FROM grok_archive_v1 "
            "WHERE event_id=? AND revision=?", (event_id, revision)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise ArchiveBlocked("RECEIPT_NOT_DURABLE")
    eid, rev, digest, payload_json, payload_hash, received, available, state = row
    try:
        payload = json.loads(payload_json)
        if (eid != event_id or rev != revision
                or hashlib.sha256(payload_json.encode("utf-8")).hexdigest() != payload_hash
                or content_digest(payload) != digest
                or payload["event_id"] != eid or payload["event_revision"] != rev
                or payload["content_hash"] != digest):
            raise ArchiveBlocked("ARCHIVE_INTEGRITY_FAILURE")
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise ArchiveBlocked("ARCHIVE_INTEGRITY_FAILURE") from exc
    return {
        "event_id": eid,
        "event_revision": rev,
        "content_hash": digest,
        "received_at": received,
        "available_at": available,
        "state": state,
        "raw_payload_sha256": payload_hash,
        # An independently read local timestamp is not NTP/source attestation.
        "available_at_verified": False,
        "receiver_clock_attested": False,
        "source_authenticity_verified": False,
        "brain_receiver_ack_verified": False,
        "shadow_eligible": False,
        "real_submit_allowed": False,
    }


def read_archive_receipt(db_path, event_id: str, revision: int) -> dict:
    """Read-only audit metadata; never return news payload or raw MS2 data."""
    path = _path(db_path)
    try:
        return _read(path, event_id, revision)
    except sqlite3.DatabaseError as exc:
        raise ArchiveBlocked("STORAGE_UNAVAILABLE") from exc


def archive_event(db_path, event: dict, *, clock=None) -> dict:
    """Validate, append an immutable revision, commit, and independently re-read.

    A crash between PENDING and ARCHIVED is recoverable with the *same* event.
    A duplicate same event/revision/hash is idempotent; a conflicting update is
    rejected. A revised event must use the next sequential revision.
    This only persists untrusted external claims for independent verification.
    """
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    path = _path(db_path)
    started = _utc(clock)
    try:
        validated = validate_event(event, now=started)
    except ContractBlocked as exc:
        raise ArchiveBlocked(str(exc)) from exc
    payload_json = canonical_bytes(event).decode("utf-8")
    payload_sha = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    event_id = validated["event_id"]
    rev = validated["event_revision"]
    digest = validated["content_hash"]
    duplicate = False

    try:
        con = _connect(path, initialize=True)
        try:
            with con:
                existing = con.execute(
                    "SELECT content_hash,state FROM grok_archive_v1 "
                    "WHERE event_id=? AND revision=?", (event_id, rev)
                ).fetchone()
                if existing:
                    if existing[0] != digest:
                        raise ArchiveBlocked("REVISION_CONTENT_CONFLICT")
                    duplicate = True
                else:
                    maxrev, newest_at = con.execute(
                        "SELECT MAX(revision),MAX(available_at) FROM grok_archive_v1 "
                        "WHERE event_id=?", (event_id,)
                    ).fetchone()
                    if rev != (maxrev or 0) + 1:
                        raise ArchiveBlocked("REVISION_GAP_OR_REGRESSION")
                    if newest_at is not None and started.isoformat() < newest_at:
                        raise ArchiveBlocked("RECEIVER_CLOCK_REGRESSION")
                    con.execute(
                        "INSERT INTO grok_archive_v1 "
                        "(event_id,revision,content_hash,payload_json,payload_sha256,"
                        "received_at,available_at,state) VALUES (?,?,?,?,?,?,NULL,'PENDING')",
                        (event_id, rev, digest, payload_json, payload_sha, started.isoformat()),
                    )
        finally:
            con.close()

        # New connection after durable first commit; catches corruption or loss.
        initial = _read(path, event_id, rev)
        if initial["content_hash"] != digest:
            raise ArchiveBlocked("REVISION_CONTENT_CONFLICT")
        if initial["state"] == "PENDING":
            # The second commit follows independent readback. It is deliberately
            # not a Brain ACK or point-in-time source provenance attestation.
            finish = _utc(clock)
            if finish < datetime.fromisoformat(initial["received_at"]):
                raise ArchiveBlocked("RECEIVER_CLOCK_REGRESSION")
            con = _connect(path)
            try:
                with con:
                    con.execute(
                        "UPDATE grok_archive_v1 SET available_at=?,state='ARCHIVED' "
                        "WHERE event_id=? AND revision=? AND content_hash=? AND state='PENDING'",
                        (finish.isoformat(), event_id, rev, digest),
                    )
            finally:
                con.close()
        result = _read(path, event_id, rev)
        if result["state"] != "ARCHIVED" or result["available_at"] is None:
            raise ArchiveBlocked("RECEIPT_NOT_DURABLE")
        result["duplicate"] = duplicate
        result["receipt_independently_read_back"] = True
        result["state"] = "ARCHIVED_RESEARCH_ONLY"
        return result
    except sqlite3.DatabaseError as exc:
        raise ArchiveBlocked("STORAGE_UNAVAILABLE") from exc
