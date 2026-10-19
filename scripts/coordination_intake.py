"""Offline intake/ACK contract for #447. No authorized production adapter exists.

This module has no network transport, CLI send option, or production activation.
The synthetic harness uses the SAME SQLite outbox as #447. Caller JSON cannot
authorize a route or authenticate a scheduled run. A future platform adapter
requires separate review; never substitute a different transport after denial.
"""
from contextlib import closing
import hashlib
import json
import sqlite3

from scripts.coordination_report_delivery import Blocked, render, require


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def initialize(db):
    # Extend an existing #447 outbox; never create/replace a missing queue.
    from pathlib import Path
    require(Path(db).is_file(), 'OUTBOX_MISSING')
    with closing(sqlite3.connect(db)) as con, con:
        require(con.execute("SELECT name FROM sqlite_master WHERE name='reports'").fetchone(),
                'NOT_REPORT_OUTBOX')
        con.execute('CREATE TABLE intake (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, '
                    'message_id TEXT UNIQUE NOT NULL, state TEXT NOT NULL, route TEXT NOT NULL)')
        con.execute('CREATE TABLE route_blocks (route TEXT PRIMARY KEY)')


def production_status():
    return dict(state='WRITE_UNAVAILABLE', reason='NO_VERIFIED_AUTHORIZED_INPUT_ADAPTER',
                end_to_end_verified=False, sender_role_authenticated=False,
                real_submit_allowed=False)


class SyntheticQueue:
    """Dependency-injected contract harness, NOT a production sender.

    Fixtures must attest routes and runs outside the untrusted message envelope.
    Every result is SYNTHETIC_ONLY; no path returns real END_TO_END_VERIFIED.
    """
    def __init__(self, db, fixture):
        self.db, self.fixture = db, fixture

    def connect(self):
        from pathlib import Path
        require(Path(self.db).is_file(), 'OUTBOX_MISSING')
        con = sqlite3.connect(self.db, timeout=10)
        con.execute('PRAGMA synchronous=FULL')
        return con

    def result(self, state):
        return dict(state=state, evidence_class='SYNTHETIC_ONLY',
                    end_to_end_verified=False, sender_role_authenticated=False)

    def intake(self, event):
        require(type(event) is dict and set(event) ==
                {'event_id', 'source_role', 'recipient_role', 'run_id', 'report'}, 'SCHEMA')
        import re
        for field in ('event_id', 'source_role', 'recipient_role', 'run_id'):
            require(type(event[field]) is str and
                    re.fullmatch('[a-zA-Z0-9_-]{1,100}', event[field]), 'IDENTITY')
        require(event['source_role'] != event['recipient_role'], 'SELF_ACK')
        key, _, _ = render(event['report'])
        payload = canonical(event)
        # Stable sender/destination scope: new message/run IDs cannot clear denial.
        route = canonical([event['source_role'], 'issue282'])
        with closing(self.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            old = con.execute('SELECT payload,state FROM intake WHERE event_id=?',
                              (event['event_id'],)).fetchone()
            if old:
                require(old[0] == payload, 'EVENT_CONTENT_CONFLICT')
                return self.result(old[1])
            require(not con.execute('SELECT 1 FROM intake WHERE message_id=?', (key,)).fetchone(),
                    'MESSAGE_ALREADY_QUEUED')
            allowed = self.fixture.authorize(event)
            if allowed == 'PLATFORM_SAFETY_DENIED':
                con.execute('INSERT OR IGNORE INTO route_blocks VALUES (?)', (route,))
            blocked = con.execute('SELECT 1 FROM route_blocks WHERE route=?', (route,)).fetchone()
            state = 'QUEUED' if allowed == 'AUTHORIZED' and not blocked else 'WRITE_UNAVAILABLE'
            con.execute('INSERT INTO intake VALUES (?,?,?,?,?)',
                        (event['event_id'], payload, key, state, route))
            return self.result(state)

    def dispatch(self, event_id):
        # Claim and commit before external fixture call; concurrent workers and
        # process death cannot create a second attempt. No retry API exists.
        with closing(self.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT payload,state,route FROM intake WHERE event_id=?',
                              (event_id,)).fetchone()
            require(row is not None, 'UNKNOWN_EVENT')
            event, state, route = json.loads(row[0]), row[1], row[2]
            if state != 'QUEUED':
                return self.result(state)
            allowed = self.fixture.authorize(event)
            if allowed == 'PLATFORM_SAFETY_DENIED':
                con.execute('INSERT OR IGNORE INTO route_blocks VALUES (?)', (route,))
            blocked = con.execute('SELECT 1 FROM route_blocks WHERE route=?', (route,)).fetchone()
            state = 'SEND_UNKNOWN' if allowed == 'AUTHORIZED' and not blocked else 'WRITE_UNAVAILABLE'
            con.execute('UPDATE intake SET state=? WHERE event_id=?', (state, event_id))
            if state == 'SEND_UNKNOWN':
                # Holds the whole sender route across crash/timeout, including a
                # newly minted event ID. Release only after exact successful readback.
                con.execute('INSERT OR IGNORE INTO route_blocks VALUES (?)', (route,))
        if state != 'SEND_UNKNOWN':
            return self.result(state)
        try:
            # Fixture calls #447 deliver using this exact DB, never a second queue.
            state = self.fixture.deliver(self.db, event)
            require(state in {'READ_VERIFIED', 'SEND_UNKNOWN'}, 'DELIVERY_RESULT')
        except Exception:
            state = 'SEND_UNKNOWN'
        with closing(self.connect()) as con, con:
            con.execute('UPDATE intake SET state=? WHERE event_id=?', (state, event_id))
            # Do not clear a route block automatically: a concurrent denial may
            # have occurred. This bounded harness permits one attempt per sender.
        return self.result(state)

    def verify_ack(self, event_id):
        # No ACK creation and no delivery retry. Recompute on every invocation;
        # a previously verified comment can be edited/deleted/revoked.
        with closing(self.connect()) as con:
            row = con.execute('SELECT payload,state,message_id FROM intake WHERE event_id=?',
                              (event_id,)).fetchone()
            require(row is not None and row[1] == 'READ_VERIFIED', 'REPORT_NOT_READ_VERIFIED')
        event, key = json.loads(row[0]), row[2]
        try:
            # Independent exact GET of the original report is required again.
            require(self.fixture.report_readback(event), 'REPORT_CHANGED')
            # The fixture models COMPLETE pagination; failure never means zero.
            matches = self.fixture.find_acks(key)
            require(len(matches) == 1, 'ACK_MISSING_OR_DUPLICATE')
            ack = matches[0]
            require(set(ack) == {'message_id', 'in_reply_to', 'source_role', 'recipient_role',
                                'run_id', 'url', 'body_sha256'}, 'ACK_SCHEMA')
            import re
            from scripts.coordination_report_delivery import WEB
            require(type(ack['url']) is str and re.fullmatch(
                re.escape(WEB) + r'/issues/282#issuecomment-[1-9][0-9]*', ack['url']), 'ACK_URL')
            require(type(ack['run_id']) is str and ack['run_id'] != event['run_id']
                    and bool(ack['run_id']), 'ACK_INDEPENDENT_RUN')
            require(ack['in_reply_to'] == key and
                    ack['source_role'] == event['recipient_role'] and
                    ack['recipient_role'] == event['source_role'], 'ACK_DIRECTION')
            require(self.fixture.authenticated_run(ack['source_role'], ack['run_id'], ack['url']),
                    'ACK_RUN_UNAUTHENTICATED')
            body = self.fixture.get_ack(ack['url'])
            expected = canonical({k: v for k, v in ack.items() if k != 'body_sha256'})
            require(body == expected and hashlib.sha256(body.encode()).hexdigest() == ack['body_sha256'],
                    'ACK_READBACK_MISMATCH')
            # A shared GitHub login / textual role is insufficient. These receipts
            # originate in the independent run fixture, not in public comment text.
            require(self.fixture.receipt(ack['source_role'], ack['run_id'], ack['url'],
                                         ack['body_sha256'], later_than=None), 'RECEIVER_REREAD_MISSING')
            require(self.fixture.receipt(event['source_role'], None, ack['url'],
                                         ack['body_sha256'], later_than=event['run_id']),
                    'SENDER_LATER_RUN_REREAD_MISSING')
            return self.result('ACK_VERIFIED')
        except Exception:
            return self.result('HANDOFF_PENDING')
