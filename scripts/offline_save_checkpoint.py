"""Offline byte checkpoints, not authenticated market evidence.

Only cooperating writers on a local filesystem with atomic mkdir/replace are
supported. Never remove a stale lock automatically. Missing state blocks normal
updates; initialize() is an explicit offline bootstrap, never recovery. Local UTC
readback time is not market available_at. No live ingress integration is provided.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from contextlib import contextmanager


class CheckpointError(ValueError):
    pass


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _integer(value, minimum):
    return type(value) is int and minimum <= value <= 2**63 - 1


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _validate(record):
    keys = {'version', 'generation', 'sha256', 'byte_count', 'consumer_readback_at',
            'previous_generation', 'previous_record_sha256', 'consistency',
            'source_authenticated', 'real_submit_allowed', 'promotion_eligible'}
    if not isinstance(record, dict) or set(record) != keys:
        raise CheckpointError('CHECKPOINT_INVALID')
    if (type(record['version']) is not int or record['version'] != 1
            or not _integer(record['generation'], 1)
            or not _integer(record['byte_count'], 1) or not _hash(record['sha256'])
            or any(record[k] is not False for k in ('source_authenticated', 'real_submit_allowed', 'promotion_eligible'))):
        raise CheckpointError('CHECKPOINT_INVALID')
    try:
        stamp = datetime.fromisoformat(record['consumer_readback_at'])
        if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise CheckpointError('CHECKPOINT_CLOCK_INVALID') from None
    if record['generation'] == 1:
        valid = (record['previous_generation'] is None and record['previous_record_sha256'] is None
                 and record['consistency'] == 'EXPLICIT_OFFLINE_BOOTSTRAP')
    else:
        valid = (type(record['previous_generation']) is int
                 and record['previous_generation'] == record['generation'] - 1
                 and _hash(record['previous_record_sha256']) and record['consistency'] == 'PREVIOUS_MATCH')
    if not valid:
        raise CheckpointError('CHECKPOINT_CHAIN_INVALID')
    return record


def _read(path):
    try:
        raw = path.read_bytes()
        envelope = json.loads(raw)
        if set(envelope) != {'record', 'record_sha256'}:
            raise ValueError()
        record = _validate(envelope['record'])
        if envelope['record_sha256'] != _digest(_encode(record)):
            raise ValueError()
        return envelope
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise CheckpointError('CHECKPOINT_MISSING_OR_CORRUPT') from None


@contextmanager
def _locked(path):
    lock = path.with_name(path.name + '.lock')
    try:
        lock.mkdir()
    except OSError:
        raise CheckpointError('LOCK_UNAVAILABLE_FAIL_CLOSED') from None
    try:
        yield
    finally:
        lock.rmdir()


def load(path):
    """Read under the same exclusive lock as updates; no missing-state fallback."""
    path = Path(path)
    with _locked(path):
        return _read(path)


def _receipt_snapshot(data_path, evidence, identity=None):
    """Recheck bytes and file identity; receipts alone never authorize a save."""
    try:
        if data_path.is_symlink():
            raise CheckpointError('PATH_INVALID')
        before = data_path.stat()
        raw = data_path.read_bytes()
        after = data_path.stat()
    except OSError:
        raise CheckpointError('DATA_READ_FAILED') from None
    stamp = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    current = stamp(after)
    if (data_path.is_symlink() or stamp(before) != current
            or (identity is not None and current != identity)
            or _digest(raw) != evidence[0] or len(raw) != evidence[1]):
        raise CheckpointError('RECEIPT_DATA_CHANGED_OR_MISMATCH')
    return current


def _save(path, data_path, generation, expected, bootstrap, evidence=None):
    path, data_path = Path(path), Path(data_path)
    if path.resolve() == data_path.resolve() or path.is_symlink() or data_path.is_symlink():
        raise CheckpointError('PATH_INVALID')
    if not _integer(generation, 1):
        raise CheckpointError('GENERATION_INVALID')
    with _locked(path):
        identity = _receipt_snapshot(data_path, evidence) if evidence else None
        if bootstrap:
            if path.exists() or generation != 1:
                raise CheckpointError('BOOTSTRAP_REFUSED')
            previous = None
        else:
            previous = _read(path)
            if not _hash(expected) or previous['record_sha256'] != expected:
                raise CheckpointError('PREVIOUS_CHECKPOINT_CONFLICT')
            if generation != previous['record']['generation'] + 1:
                raise CheckpointError('GENERATION_NOT_NEXT')
        try:
            # Two separate opens: never accept a caller-supplied hash or clock.
            first = data_path.read_bytes()
            second = data_path.read_bytes()
        except OSError:
            raise CheckpointError('DATA_READ_FAILED') from None
        if not first or first != second:
            raise CheckpointError('DATA_EMPTY_OR_UNSTABLE')
        digest = _digest(second)
        if evidence and (digest, len(second)) != evidence:
            raise CheckpointError('RECEIPT_DATA_CHANGED_OR_MISMATCH')
        if previous and digest == previous['record']['sha256']:
            raise CheckpointError('DUPLICATE_DATA')
        record = _validate(dict(version=1, generation=generation, sha256=digest,
            byte_count=len(second), consumer_readback_at=datetime.now(timezone.utc).isoformat(),
            previous_generation=previous['record']['generation'] if previous else None,
            previous_record_sha256=previous['record_sha256'] if previous else None,
            consistency='PREVIOUS_MATCH' if previous else 'EXPLICIT_OFFLINE_BOOTSTRAP',
            source_authenticated=False, real_submit_allowed=False, promotion_eligible=False))
        envelope = dict(record=record, record_sha256=_digest(_encode(record)))
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', delete=False) as handle:
                temp = Path(handle.name)
                handle.write(_encode(envelope))
                handle.flush()
                os.fsync(handle.fileno())
            if _read(temp) != envelope:
                raise CheckpointError('STAGED_READBACK_FAILED')
            if evidence:
                _receipt_snapshot(data_path, evidence, identity)
            os.replace(temp, path)
            temp = None
            # A failure here means commit outcome is unverified. Never return success
            # or retry blindly; load and compare before another update.
            if _read(path) != envelope:
                raise CheckpointError('COMMITTED_READBACK_FAILED')
            if evidence:
                _receipt_snapshot(data_path, evidence, identity)
            return envelope
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)


def initialize(path, data_path):
    """Explicit new offline series. Refuses to replace existing/corrupt state."""
    return _save(path, data_path, 1, None, True)


def advance(path, data_path, *, generation, expected_record_sha256):
    """CAS update of exactly the next generation; stale writers are rejected."""
    return _save(path, data_path, generation, expected_record_sha256, False)


def advance_from_receipts(path, data_path, *, writer_receipt, consumer_receipt,
                          generation, expected_record_sha256):
    """Offline reconciliation followed by a CAS update; never bootstraps.

    Generation is local save order, not exchange event order. Writer receipts
    are unauthenticated. Checks cover mutation through committed readback, not
    future writes after this call. As with advance(), only cooperating local
    checkpoint writers are supported. Post-commit errors leave outcome unknown;
    callers must load/reconcile, never report success or blindly retry.
    """
    from scripts.ms2_observation_ingress import reconcile_writer_consumer_receipts

    # Copy before reconciliation: subsequent caller mutations cannot change
    # which byte identity the transaction authorizes.
    import copy
    matched = reconcile_writer_consumer_receipts(
        copy.deepcopy(writer_receipt), copy.deepcopy(consumer_receipt))
    if matched['state'] != 'READBACK_MATCH_ONLY':
        raise CheckpointError('RECEIPT_REJECTED:' + matched['reason'])
    evidence = (matched['published_sha256'], matched['bytes_verified'])
    return _save(path, data_path, generation, expected_record_sha256, False, evidence)
