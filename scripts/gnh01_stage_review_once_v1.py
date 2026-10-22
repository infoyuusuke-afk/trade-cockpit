"""One-shot private quarantine staging; no network, recipient ACK or promotion.

Reuses #490's archive, event validator and exclusive signed review writer.
The dispatch claim lives in that SAME archive database. After any uncertain
export, subsequent invocations inspect only and never recreate a delivery.
This is a callable adapter, not an installed scheduler or authenticated ingress.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import hashlib
import hmac
import sqlite3

from scripts.gnh01_durable_archive_v1 import (
    ArchiveBlocked, _connect, _path, _utc, archive_event,
)
from scripts.gnh01_intelligence_contract_v1 import parse_event_json_bytes
from scripts.gnh01_pre_next_review_v1 import build_pre_next_review_request
from scripts.gnh01_private_review_handoff_v1 import (
    ENVELOPE_SCHEMA, SENDER_KEY, MAX_AGE, HandoffBlocked, _dt, _key,
    _name, _read_once, _root, _sig, _strict_json, export_review,
)

TABLE = """CREATE TABLE IF NOT EXISTS gnh01_review_dispatch_v1 (
    event_id TEXT NOT NULL, revision INTEGER NOT NULL,
    content_hash TEXT NOT NULL, destination TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('SEND_UNKNOWN','READ_VERIFIED')),
    envelope_hash TEXT,
    PRIMARY KEY(event_id,revision)
)"""


def _inspect(db_path, event, *, private_dir, now):
    """Independent file open + archive readback; never generate a reader ACK."""
    at = _utc(lambda: now)
    root = _root(private_dir)
    review = build_pre_next_review_request(db_path, event, now=at)
    path = root / _name(review)
    obj_raw = _read_once(path, root)
    obj = _strict_json(obj_raw)
    if (type(obj) is not dict or set(obj) != {
            'schema_version', 'payload', 'hmac_sha256'}
            or obj['schema_version'] != ENVELOPE_SCHEMA):
        raise HandoffBlocked('STAGED_ENVELOPE_INVALID')
    payload = obj['payload']
    if (type(payload) is not dict or set(payload) != {
            'review', 'emitted_at', 'producer_kind', 'recipient', 'real_submit_allowed'}
            or payload['review'] != review
            or payload['producer_kind'] != 'LOCAL_ARCHIVE_EXPORTER_NOT_GROK'
            or payload['recipient'] != 'pre_next'
            or payload['real_submit_allowed'] is not False):
        raise HandoffBlocked('STAGED_ARCHIVE_MISMATCH')
    signature = obj['hmac_sha256']
    if (type(signature) is not str or not hmac.compare_digest(
            _sig(_key(SENDER_KEY), b'100B:GNH01:REVIEW:V1\n', payload), signature)):
        raise HandoffBlocked('STAGED_SIGNATURE_INVALID')
    emitted = _dt(payload['emitted_at'])
    if not _dt(review['local_archived_at']) <= emitted <= at or at-emitted > MAX_AGE:
        raise HandoffBlocked('STAGED_STALE_OR_FUTURE')
    return path, hashlib.sha256(obj_raw).hexdigest()


def inspect_staged_review(db_path, event, *, private_dir, now: datetime) -> dict:
    """Read a completed dispatch without sending, repairing or upgrading UNKNOWN."""
    path = _path(db_path)
    target, digest = _inspect(path, event, private_dir=private_dir, now=now)
    with closing(_connect(path)) as con:
        row = con.execute(
            'SELECT content_hash,destination,state,envelope_hash '
            'FROM gnh01_review_dispatch_v1 WHERE event_id=? AND revision=?',
            (event['event_id'], event['event_revision']),
        ).fetchone()
    if row != (event['content_hash'], str(target), 'READ_VERIFIED', digest):
        raise HandoffBlocked('DISPATCH_UNVERIFIED_NO_RETRY')
    return {
        'state': 'STAGED_REVIEW_ONLY',
        'event_id': event['event_id'], 'event_revision': event['event_revision'],
        'content_hash': event['content_hash'], 'envelope_sha256': digest,
        'local_archive_and_envelope_readback_verified': True,
        'source_authenticity_verified': False,
        'pre_next_automated_receipt_verified': False,
        'pre_next_ack_verified': False, 'shadow_ingestion_verified': False,
        'brain_receipt_verified': False, 'end_to_end_verified': False,
        'real_submit_allowed': False,
    }


def stage_json_once(db_path, raw: bytes, *, private_dir, now: datetime) -> dict:
    """Validate -> archive -> durable claim -> exclusive export -> readback.

Same identity with changed destination/content blocks. Completed duplicates
are independently reread; UNKNOWN never calls the exporter again, even when
the original write failed before creating a file. Caller must retain the
archive database across runs; deleting it is not an authorized recovery path.
No recipient key is needed and no synthetic receiver ACK is fabricated.
"""
    at = _utc(lambda: now)
    event = parse_event_json_bytes(raw)
    root = _root(private_dir)
    path = _path(db_path)
    _key(SENDER_KEY)  # reject unconfigured exporter before any persistence
    archive_event(path, event, clock=lambda: at)
    review = build_pre_next_review_request(path, event, now=at)
    target = root / _name(review)
    identity = (event['event_id'], event['event_revision'])
    existing = None
    try:
        with closing(_connect(path)) as con:
            con.execute('PRAGMA synchronous=FULL')
            con.execute('BEGIN IMMEDIATE')
            with con:
                con.execute(TABLE)
                existing = con.execute(
                    'SELECT content_hash,destination,state,envelope_hash '
                    'FROM gnh01_review_dispatch_v1 WHERE event_id=? AND revision=?',
                    identity,
                ).fetchone()
                if existing is None:
                    con.execute('INSERT INTO gnh01_review_dispatch_v1 VALUES(?,?,?,?,?,NULL)',
                                (*identity, event['content_hash'], str(target), 'SEND_UNKNOWN'))
        if existing is not None:
            if existing[:2] != (event['content_hash'], str(target)):
                raise HandoffBlocked('DISPATCH_IDENTITY_CONFLICT')
            if existing[2] != 'READ_VERIFIED':
                raise HandoffBlocked('SEND_UNKNOWN_NO_RETRY')
            return inspect_staged_review(path, event, private_dir=root, now=at)

        # The claim is durable BEFORE the only export attempt. Any exception
        # leaves SEND_UNKNOWN sticky; there is deliberately no reset/retry API.
        export_review(path, event, private_dir=root, now=at)
        actual, digest = _inspect(path, event, private_dir=root, now=at)
        if actual != target:
            raise HandoffBlocked('DISPATCH_DESTINATION_MISMATCH')
        with closing(_connect(path)) as con:
            con.execute('PRAGMA synchronous=FULL')
            with con:
                updated = con.execute(
                    "UPDATE gnh01_review_dispatch_v1 SET state='READ_VERIFIED',envelope_hash=? "
                    "WHERE event_id=? AND revision=? AND content_hash=? AND destination=? "
                    "AND state='SEND_UNKNOWN' AND envelope_hash IS NULL",
                    (digest, *identity, event['content_hash'], str(target)),
                ).rowcount
                if updated != 1:
                    raise HandoffBlocked('DISPATCH_COMMIT_CONFLICT')
        return inspect_staged_review(path, event, private_dir=root, now=at)
    except sqlite3.DatabaseError as exc:
        raise ArchiveBlocked('DISPATCH_STORAGE_UNAVAILABLE_NO_RETRY') from exc
