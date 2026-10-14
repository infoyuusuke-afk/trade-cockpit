"""Offline supervisor-owned evidence, separate from canonical 2048-byte payload.

Single producer seqlock. A supervisor retains the mapping through producer death.
An OPEN checkpoint is durable before launching a producer. Never infer no gaps
from a missing/torn/latest checkpoint. No authentication or power-loss claim.
"""
import hashlib
import json
import os
import struct
import time
import uuid
from multiprocessing import shared_memory
from pathlib import Path

REASONS = ('ACCEPTED', 'QUEUE_FULL', 'GATE_BUSY', 'NOT_READY', 'STALE',
           'INVALID', 'STOP', 'KILL', 'WRITER_STOPPED', 'OTHER')
SIZE = 1024


def read_snapshot(buf, generation):
    first = struct.unpack_from('<q', buf, 0)[0]
    if first & 1:
        return None
    raw = bytes(buf[:SIZE])
    last = struct.unpack_from('<q', buf, 0)[0]
    values = struct.unpack_from('<128q', raw)
    if first != last or values[0] != first or values[1] != generation:
        return None
    total, last_poll, complete = values[2:5]
    counters = {}
    for i, reason in enumerate(REASONS):
        count, first_poll, end_poll, first_ms, last_ms = values[8+i*5:13+i*5]
        if count < 0 or (count and (first_poll < 1 or end_poll < first_poll or last_ms < first_ms)):
            return None
        if count:
            counters[reason] = dict(count=count, first_poll=first_poll,
                last_poll=end_poll, first_unix_ms=first_ms, last_unix_ms=last_ms)
    if total < 0 or total != sum(x['count'] for x in counters.values()) or complete not in (0, 1):
        return None
    return dict(version=first, generation=generation, total=total,
                last_poll=last_poll, producer_complete=bool(complete), counters=counters)


class Evidence:
    def __init__(self, root, generation):
        self.root = Path(root).resolve() / 'data/private/ms2_sidecar/drop'
        self.root.mkdir(parents=True, exist_ok=True)
        self.session = uuid.uuid4().hex
        self.path = self.root / (self.session + '.json')
        self.generation = generation
        self.shm = shared_memory.SharedMemory(create=True, name='e'+uuid.uuid4().hex[:11], size=SIZE)
        self.shm.buf[:] = b'\0' * SIZE
        struct.pack_into('<q', self.shm.buf, 8, generation)
        self.previous = None
        self.last = None
        self.checkpoint('OPEN')  # Before producer creation; not on critical loop.

    def checkpoint(self, outcome='RUNNING', fault=None):
        snap = read_snapshot(self.shm.buf, self.generation)
        if snap is not None and self.last is not None:
            for key, old in self.last['counters'].items():
                if snap['counters'].get(key, {}).get('count', 0) < old['count']:
                    snap = None
                    break
            if snap is not None and (snap['version'] < self.last['version'] or snap['total'] < self.last['total']):
                snap = None
        if snap is not None:
            self.last = snap
        body = dict(schema='OFFLINE_DROP_V1', session=self.session, generation=self.generation,
            snapshot=self.last, snapshot_integrity='VERIFIED' if snap is not None else 'TORN_OR_INVALID',
            outcome=outcome, state='GAP_EVIDENCE', close_state='NOT_CLOSED',
            tail='ACCOUNTED_TO_PRODUCER_COMPLETE' if snap is not None and snap['producer_complete'] and outcome == 'EXIT_0' else 'UNKNOWN',
            accepted_means='QUEUED_ONLY', timestamp_domain='UNIX_MS_UTC',
            power_loss='NOT_VERIFIED', real_submit_allowed=False,
            promotion_eligible=False, statistical_edge_confirmed=False)
        raw = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
        envelope = json.dumps(dict(body=body, sha256=hashlib.sha256(raw).hexdigest()), sort_keys=True).encode()
        temp = self.path.with_suffix('.tmp')
        with open(temp, 'wb') as stream:
            if os.name != 'nt': os.chmod(temp, 0o600)
            stream.write(envelope[:len(envelope)//2])
            if fault == 'partial': raise RuntimeError('SYNTHETIC_PARTIAL_WRITE')
            stream.write(envelope[len(envelope)//2:]); stream.flush(); os.fsync(stream.fileno())
        if fault == 'before_replace': raise RuntimeError('SYNTHETIC_BEFORE_REPLACE')
        os.replace(temp, self.path)
        if os.name != 'nt':
            fd = os.open(self.root, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        self.previous = body
        return body

    def close(self):
        self.shm.close()
        if os.name != 'nt': self.shm.unlink()


def recover(path):
    """Read only. Never replay old observations or merge sessions/counters."""
    try:
        envelope = json.loads(Path(path).read_bytes())
        body = envelope['body']
        raw = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
        if hashlib.sha256(raw).hexdigest() != envelope['sha256']:
            raise ValueError('HASH')
        if body['schema'] != 'OFFLINE_DROP_V1' or body['close_state'] != 'NOT_CLOSED':
            raise ValueError('CONTRACT')
        return body
    except (ValueError, KeyError, OSError, TypeError):
        return dict(state='BLOCKED', close_state='NOT_CLOSED', tail='UNKNOWN')
