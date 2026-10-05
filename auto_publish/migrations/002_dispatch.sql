-- Dry-run E2E: WOULD_PUBLISH simulator bookkeeping (network-free).
-- schedules.status now also takes: DISPATCHING | WOULD_PUBLISH | BLOCKED | UNKNOWN | MISSED
-- (WOULD_PUBLISH means "every send precondition was verified at the scheduled time in DRY-RUN";
--  nothing is ever sent.)

CREATE TABLE IF NOT EXISTS dispatches (
    dispatch_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id        INTEGER NOT NULL REFERENCES schedules(schedule_id),
    story_id           TEXT NOT NULL REFERENCES stories(story_id),
    platform           TEXT NOT NULL,
    idempotency_key    TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN
                         ('IN_FLIGHT','WOULD_PUBLISH','BLOCKED','UNKNOWN','ABORTED','MISSED')),
    runner_id          TEXT NOT NULL,
    claimed_at         TEXT NOT NULL,
    lease_until        TEXT NOT NULL,
    finished_at        TEXT,
    trace_json         TEXT,
    trace_sha256       TEXT,
    error_json         TEXT
);

-- At most one live/terminal attempt per schedule; ABORTED (kill switch hit mid-flight) does not count.
CREATE UNIQUE INDEX IF NOT EXISTS ux_dispatch_once
    ON dispatches(schedule_id) WHERE status IN ('IN_FLIGHT','WOULD_PUBLISH','BLOCKED','UNKNOWN','MISSED');
-- A given idempotency key can produce at most one WOULD_PUBLISH, ever.
CREATE UNIQUE INDEX IF NOT EXISTS ux_dispatch_would_publish
    ON dispatches(idempotency_key) WHERE status = 'WOULD_PUBLISH';
-- Terminal outcomes are immutable.
CREATE TRIGGER IF NOT EXISTS dispatches_terminal_immutable
BEFORE UPDATE ON dispatches
WHEN OLD.status <> 'IN_FLIGHT'
BEGIN
    SELECT RAISE(ABORT, 'dispatch outcome is final');
END;

CREATE TRIGGER IF NOT EXISTS dispatches_no_delete
BEFORE DELETE ON dispatches
BEGIN
    SELECT RAISE(ABORT, 'dispatches are append-only');
END;
