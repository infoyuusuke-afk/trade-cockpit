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
import os
from pathlib import Path
import sqlite3
import stat
import threading
from typing import Callable

from scripts.gnh01_intelligence_contract_v1 import (
    ContractBlocked, canonical_bytes, content_digest, parse_event_json_bytes, validate_event,
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
    receipt_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('PENDING','ARCHIVED')),
    PRIMARY KEY (event_id, revision)
);
"""


class ArchiveBlocked(ValueError):
    """Stable fail-closed diagnostic without exposing payloads or filesystem paths."""


# Serializes *same-process* schema/WAL bootstrap. SQLite WAL still arbitrates
# cross-process writes; each transaction retains busy_timeout and fail-closed.
_INIT_LOCK = threading.RLock()


def _receipt_digest(event_id, revision, digest, payload_sha, received, available, state):
    """Detect accidental post-commit mutation; unkeyed, NOT authentication."""
    row = dict(event_id=event_id, revision=revision, content_hash=digest,
               payload_sha256=payload_sha, received_at=received,
               available_at=available, state=state)
    return hashlib.sha256(canonical_bytes(row)).hexdigest()


def _utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ArchiveBlocked("RECEIVER_CLOCK_UNVERIFIED")
    return value.astimezone(timezone.utc)


def _path(db_path) -> Path:
    """Enforce an external private archive directory before SQLite may create files.

    This is a local-path guard, NOT a proof of Windows ACL configuration.
    A storage service still needs OS ACLs and an authorized deployment directory.
    """
    try:
        p = Path(db_path)
        if (not p.is_absolute() or ".." in p.parts
                or not p.parent.is_dir()
                or str(p).startswith(("\\\\", "//"))):
            raise ArchiveBlocked("PRIVATE_STORAGE_PATH_REQUIRED")
        project = Path(__file__).resolve().parent.parent
        parent = p.parent.resolve(strict=True)
        if parent == project or project in parent.parents:
            raise ArchiveBlocked("PRIVATE_STORAGE_INSIDE_REPOSITORY")
        # Reject links/reparse points in *every* path component. An attacker
        # must not redirect a private database into the public checkout.
        for component in (p.parent, *p.parent.parents):
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ArchiveBlocked("PRIVATE_STORAGE_LINK_UNTRUSTED")
        if os.name != "nt":
            # Parent is the private data directory, not shared /tmp itself.
            if p.parent.stat().st_mode & 0o077:
                raise ArchiveBlocked("PRIVATE_STORAGE_PERMISSION_UNSAFE")
        if p.exists() or p.is_symlink():
            if p.is_symlink():
                raise ArchiveBlocked("PRIVATE_STORAGE_LINK_UNTRUSTED")
            info = p.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ArchiveBlocked("PRIVATE_STORAGE_FILE_UNSAFE")
        return p
    except ArchiveBlocked:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ArchiveBlocked("PRIVATE_STORAGE_PATH_REQUIRED") from exc


def _connect(path: Path, *, initialize=False):
    if not initialize and not path.is_file():
        raise ArchiveBlocked("ARCHIVE_NOT_FOUND")
    if initialize:
        # PRAGMA journal_mode=WAL cannot race another thread initializing WAL.
        # Restrict bootstrap to one same-process writer, never the readback.
        with _INIT_LOCK:
            con = sqlite3.connect(str(path), timeout=5, isolation_level="IMMEDIATE")
            try:
                con.execute("PRAGMA busy_timeout=5000")
                mode = con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if mode.lower() != "wal":
                    raise ArchiveBlocked("WAL_REQUIRED")
                con.execute("PRAGMA synchronous=FULL")
                con.execute(_SCHEMA)
                con.commit()
                return con
            except Exception:
                con.close()
                raise
    con = sqlite3.connect(str(path), timeout=5, isolation_level="IMMEDIATE")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _read(path: Path, event_id: str, revision: int) -> dict:
    """Independent new connection: never trust a writer's return value alone."""
    con = _connect(path)
    try:
        row = con.execute(
            "SELECT event_id,revision,content_hash,payload_json,payload_sha256,"
            "received_at,available_at,state,receipt_sha256 FROM grok_archive_v1 "
            "WHERE event_id=? AND revision=?", (event_id, revision)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise ArchiveBlocked("RECEIPT_NOT_DURABLE")
    eid, rev, digest, payload_json, payload_hash, received, available, state, receipt_sha = row
    try:
        payload = json.loads(payload_json)
        if (eid != event_id or rev != revision
                or hashlib.sha256(payload_json.encode("utf-8")).hexdigest() != payload_hash
                or content_digest(payload) != digest
                or payload["event_id"] != eid or payload["event_revision"] != rev
                or payload["content_hash"] != digest
                or _receipt_digest(eid, rev, digest, payload_hash,
                                   received, available, state) != receipt_sha):
            raise ArchiveBlocked("ARCHIVE_INTEGRITY_FAILURE")
        received_dt = datetime.fromisoformat(received)
        if (received_dt.tzinfo is None or received_dt.utcoffset() is None
                or received_dt.utcoffset().total_seconds() != 0):
            raise ArchiveBlocked("ARCHIVE_INTEGRITY_FAILURE")
        if state == "ARCHIVED":
            if available is None:
                raise ArchiveBlocked("ARCHIVE_INTEGRITY_FAILURE")
            available_dt = datetime.fromisoformat(available)
            if (available_dt.tzinfo is None or available_dt.utcoffset() is None
                    or available_dt < received_dt):
                raise ArchiveBlocked("ARCHIVE_INTEGRITY_FAILURE")
        elif available is not None:
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
            # BEGIN IMMEDIATE MUST precede SELECT; otherwise concurrent writers
            # both observe "missing" before an implicit transaction begins and
            # one hits a UNIQUE constraint at INSERT (not a safe duplicate ACK).
            con.execute("BEGIN IMMEDIATE")
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
                    received_at = started.isoformat()
                    receipt_sha = _receipt_digest(event_id, rev, digest, payload_sha,
                                                  received_at, None, "PENDING")
                    con.execute(
                        "INSERT INTO grok_archive_v1 "
                        "(event_id,revision,content_hash,payload_json,payload_sha256,"
                        "received_at,available_at,receipt_sha256,state) "
                        "VALUES (?,?,?,?,?,?,NULL,?,'PENDING')",
                        (event_id, rev, digest, payload_json, payload_sha,
                         received_at, receipt_sha),
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
                    receipt_sha = _receipt_digest(
                        event_id, rev, digest, initial["raw_payload_sha256"],
                        initial["received_at"], finish.isoformat(), "ARCHIVED")
                    con.execute(
                        "UPDATE grok_archive_v1 "
                        "SET available_at=?,state='ARCHIVED',receipt_sha256=? "
                        "WHERE event_id=? AND revision=? AND content_hash=? AND state='PENDING'",
                        (finish.isoformat(), receipt_sha, event_id, rev, digest),
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


def archive_json_once(db_path, raw: bytes, *, clock=None) -> dict:
    """One-shot local bytes-to-archive entry point for a future private exporter.

    This is NOT a listener, scheduler, endpoint, external-origin authentication,
    verified source receipt, PRE-NEXT ACK, Brain decision or Shadow execution.
    Parse first (bounded UTF-8, no duplicate keys, floats or NaN) and archive
    only after full semantic/safety validation. No network or broker imports.
    """
    try:
        event = parse_event_json_bytes(raw)
    except ContractBlocked as exc:
        raise ArchiveBlocked(str(exc)) from exc
    return archive_event(db_path, event, clock=clock)
