"""Offline evidence ledger. Never imported/called by the live Watcher.

ACCEPTED is queue evidence only. Readback verifies persistence at an observed
upper bound, never its original commit time. UNKNOWN_TERMINAL closes an audit
window, not a claim of permanent loss. Every result remains NOT_CLOSED.
SQLite FULL transactions retain immutable events; checkpoints are disposable.
No authentication, power-loss or OS stall guarantee is inferred from hashes.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from scripts.ms2_offline_observation_writer import build_captured_record
from scripts.ms2_watcher_sidecar_contract import audit_sidecar_bytes

VERSION = 'ms2-poll-reconciliation-0.1'
STAGES = {'QUEUED', 'DROPPED_PRE_QUEUE', 'REJECTED_POST_QUEUE', 'PERSISTED_VERIFIED',
          'UNKNOWN_PENDING', 'UNKNOWN_TERMINAL'}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def clock(value):
    if not isinstance(value, str):
        raise ValueError('CLOCK_REQUIRED')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('TIMEZONE_NOT_GUESSED')
    return result.astimezone(timezone.utc)

def expected_record(capture):
    built = build_captured_record(capture)
    if not built['ok']:
        raise ValueError('CAPTURE_REFUSED')
    return built['record']

class Ledger:
    """Single supervisor owns a private ledger; never a synchronous poll write.

    Caller supplies measured event times. Session and generation never roll in
    place. A conflicting event permanently blocks that poll, including PIT
    queries. Event hashes are identities, not proof of process authentication.
    """
    def __init__(self, directory, session_id, generation):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', session_id) or type(generation) is not int or generation < 1:
            raise ValueError('IDENTITY_INVALID')
        self.session, self.generation = session_id, generation
        root = Path(directory)
        if root.is_symlink():
            raise ValueError('PRIVATE_PATH_LINK')
        root.mkdir(parents=True, exist_ok=True)
        for part in [root, *root.parents]:
            if part.is_symlink():
                raise ValueError('PRIVATE_PATH_LINK')
        self.path = root / (session_id + '-' + str(generation) + '.sqlite')
        if self.path.is_symlink():
            raise ValueError('PRIVATE_PATH_LINK')
        self.db = sqlite3.connect(self.path, timeout=0)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS meta(session TEXT, generation INTEGER);
          CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, body BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS conflicts(poll INTEGER PRIMARY KEY, reason TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
          CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_EVIDENCE'); END;
          CREATE TRIGGER IF NOT EXISTS conflicts_no_update BEFORE UPDATE ON conflicts
            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_CONFLICT'); END;
          CREATE TRIGGER IF NOT EXISTS conflicts_no_delete BEFORE DELETE ON conflicts
            BEGIN SELECT RAISE(ABORT,'IMMUTABLE_CONFLICT'); END;
        ''')
        with self.db:
            m = self.db.execute('SELECT * FROM meta').fetchall()
            if m and m != [(session_id, generation)]:
                raise ValueError('STALE_GENERATION')
            if not m:
                self.db.execute('INSERT INTO meta VALUES (?,?)', (session_id, generation))
        if os.name != 'nt':
            os.chmod(root, 0o700); os.chmod(self.path, 0o600)
        self.quarantine_partials()

    def close(self):
        self.db.close()

    def events(self):
        result = []
        for identity, raw in self.db.execute('SELECT id,body FROM events ORDER BY id'):
            body = json.loads(raw)
            if digest(body) != identity or body['session_id'] != self.session or body['generation'] != self.generation:
                raise ValueError('LEDGER_INTEGRITY')
            result.append(body)
        return result

    def add(self, **event):
        if event.get('stage') == 'PERSISTED_VERIFIED':
            raise ValueError('VALIDATED_READBACK_REQUIRED')
        return self._append(**event)

    def _append(self, *, poll_seq, payload_identity, stage, observed_at, reason_code,
            source_digest, session_id=None, generation=None):
        if (session_id or self.session) != self.session or (generation if generation is not None else self.generation) != self.generation:
            raise ValueError('STALE_GENERATION')
        if type(poll_seq) is not int or poll_seq < 1 or stage not in STAGES:
            raise ValueError('EVENT_INVALID')
        clock(observed_at)
        if not re.fullmatch('[0-9a-f]{64}', payload_identity) or not re.fullmatch('[0-9a-f]{64}', source_digest):
            raise ValueError('EVIDENCE_IDENTITY_REQUIRED')
        if not isinstance(reason_code, str) or not reason_code:
            raise ValueError('REASON_REQUIRED')
        body = dict(session_id=self.session, generation=self.generation, poll_seq=poll_seq,
                    payload_identity=payload_identity, stage=stage, observed_at=observed_at,
                    reason_code=reason_code, source_digest=source_digest)
        identity = digest(body)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            prior = [e for e in self.events() if e['poll_seq'] == poll_seq]
            states = {e['stage'] for e in prior} | {stage}
            conflict = any(e['payload_identity'] != payload_identity for e in prior)
            conflict |= ('DROPPED_PRE_QUEUE' in states and bool(states & {'QUEUED', 'PERSISTED_VERIFIED', 'REJECTED_POST_QUEUE'}))
            conflict |= {'REJECTED_POST_QUEUE', 'PERSISTED_VERIFIED'} <= states
            # A post-queue claim requires positive queue evidence, even if received
            # out of order upstream. Caller can retry after importing the receipt.
            if stage in {'REJECTED_POST_QUEUE', 'PERSISTED_VERIFIED'} and 'QUEUED' not in states:
                raise ValueError('QUEUE_EVIDENCE_REQUIRED')
            q = [clock(e['observed_at']) for e in prior if e['stage'] == 'QUEUED']
            if stage in {'PERSISTED_VERIFIED', 'REJECTED_POST_QUEUE'} and q and clock(observed_at) < min(q):
                conflict = True
            self.db.execute('INSERT OR IGNORE INTO events VALUES (?,?)', (identity, canonical(body)))
            if conflict:
                self.db.execute('INSERT OR IGNORE INTO conflicts VALUES (?,?)', (poll_seq, 'CONFLICTING_EVIDENCE'))
        return 'BLOCKED' if conflict else identity

    def verify_readback(self, raw, expectations, observed_at, *, source_session, source_generation):
        """Raw bytes must come from the session's published file, never a temp.

        Only validated entire JSONL is accepted. Whole-file digest binds the
        immutable PIT readback evidence. No counter or checkpoint proves rows.
        """
        clock(observed_at)
        if source_session != self.session or source_generation != self.generation:
            raise ValueError('STALE_GENERATION')
        audit = audit_sidecar_bytes(raw)
        if audit['contract_status'] not in {'ADMITTED_INCOMPLETE', 'PROJECTABLE_SYNTHETIC'}:
            raise ValueError('READBACK_CONTRACT_REFUSED')
        rows = [json.loads(line) for line in raw.splitlines()]
        source = hashlib.sha256(raw).hexdigest()
        for row in rows:
            poll = row['poll_seq']
            if poll not in expectations or row != expectations[poll]:
                # Positive row conflict blocks the matching poll permanently.
                prior = [e for e in self.events() if e['poll_seq'] == poll]
                if prior:
                    with self.db:
                        self.db.execute('INSERT OR IGNORE INTO conflicts VALUES (?,?)', (poll, 'READBACK_IDENTITY_CONFLICT'))
                raise ValueError('READBACK_IDENTITY_CONFLICT')
        already = {(e['poll_seq'],e['payload_identity']) for e in self.events() if e['stage']=='PERSISTED_VERIFIED'}
        for row in rows:
            if (row['poll_seq'],digest(row)) in already:
                continue
            self._append(poll_seq=row['poll_seq'], payload_identity=digest(row), stage='PERSISTED_VERIFIED',
                     observed_at=observed_at, reason_code='VALIDATED_PUBLISHED_READBACK', source_digest=source)
        return len(rows)

    def reconcile(self, as_of, *, window_ended=False):
        point = clock(as_of)
        all_events = self.events()
        events = [e for e in all_events if clock(e['observed_at']) <= point]
        blocked = dict(self.db.execute('SELECT poll,reason FROM conflicts'))
        result = []
        for poll in sorted({e['poll_seq'] for e in events}):
            group = [e for e in events if e['poll_seq'] == poll]
            stages = {e['stage'] for e in group}
            queued = [e for e in group if e['stage'] == 'QUEUED']
            saved = [e for e in group if e['stage'] == 'PERSISTED_VERIFIED']
            if poll in blocked:
                state, reason = 'UNKNOWN_TERMINAL', blocked[poll]
            elif saved:
                state, reason = 'PERSISTED_VERIFIED', 'VALIDATED_PUBLISHED_READBACK'
            elif 'REJECTED_POST_QUEUE' in stages:
                state, reason = 'REJECTED_POST_QUEUE', next(e['reason_code'] for e in group if e['stage'] == 'REJECTED_POST_QUEUE')
            elif 'DROPPED_PRE_QUEUE' in stages:
                state, reason = 'DROPPED_PRE_QUEUE', next(e['reason_code'] for e in group if e['stage'] == 'DROPPED_PRE_QUEUE')
            else:
                state = 'UNKNOWN_TERMINAL' if window_ended or 'UNKNOWN_TERMINAL' in stages else 'UNKNOWN_PENDING'
                reason = 'NO_PERSISTENCE_OR_REJECTION_PROOF'
            # queued_at/persisted_at are evidence times, never exchange clocks.
            result.append(dict(session_id=self.session, generation=self.generation, poll_seq=poll,
                payload_identity=group[0]['payload_identity'], queued_at=min((e['observed_at'] for e in queued), key=clock, default=None),
                persisted_at=min((e['observed_at'] for e in saved), key=clock, default=None) if poll not in blocked else None,
                persisted_at_basis='READBACK_OBSERVED_UPPER_BOUND' if saved and poll not in blocked else None,
                reason_code=reason, evidence_status=state, evidence_stages=sorted(stages),
                fail_closed=poll in blocked, close_state='NOT_CLOSED', permanent_loss_proven=False))
        return dict(version=VERSION, session_id=self.session, generation=self.generation, as_of=as_of,
                    polls=result, close_state='NOT_CLOSED', real_submit_allowed=False,
                    promotion_eligible=False, statistical_edge_confirmed=False, eligible_observed_n=0)

    def quarantine_partials(self):
        for path in self.path.parent.glob(self.path.name + '*.tmp'):
            if path.is_symlink():
                raise ValueError('PRIVATE_PATH_LINK')
            q = self.path.parent / 'quarantine'
            if q.is_symlink():raise ValueError('PRIVATE_PATH_LINK')
            q.mkdir(exist_ok=True)
            target = q / (path.name + '-' + hashlib.sha256(path.read_bytes()).hexdigest())
            if target.exists():
                if target.read_bytes() != path.read_bytes():
                    raise ValueError('QUARANTINE_CONFLICT')
                path.unlink()
            else:
                os.replace(path, target)

    def checkpoint(self, as_of, *, window_ended=False, fault=None):
        """Deterministic cache only; recovery always uses committed SQLite events."""
        body = self.reconcile(as_of, window_ended=window_ended)
        data = canonical(body) + b'\n'
        destination = self.path.with_suffix('.checkpoint.json')
        temporary = Path(str(self.path) + '.checkpoint.tmp')
        if temporary.exists():
            self.quarantine_partials()
        with open(temporary, 'xb') as output:
            output.write(data[:len(data)//2] if fault == 'partial' else data)
            output.flush(); os.fsync(output.fileno())
        if fault in {'partial', 'before_replace'}:
            raise RuntimeError('CHECKPOINT_INTERRUPTED')
        os.replace(temporary, destination)
        if os.name != 'nt':
            fd = os.open(destination.parent, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        if destination.read_bytes() != data:
            raise ValueError('CHECKPOINT_READBACK')
        return body
