-- Auto Publish System V1 / R1 DRY-RUN schema.
-- All timestamps are ISO-8601 UTC strings ("...Z").

CREATE TABLE IF NOT EXISTS sessions (
    session_date      TEXT PRIMARY KEY,               -- YYYY-MM-DD (JST trading session)
    input_dir         TEXT NOT NULL,
    state             TEXT NOT NULL,                  -- INGESTED | VALIDATED | FAILED
    manifest_sha256   TEXT,                           -- evidence lock hash
    fixture           INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date      TEXT NOT NULL REFERENCES sessions(session_date),
    rel_path          TEXT NOT NULL,
    sha256            TEXT NOT NULL CHECK (length(sha256) = 64),
    size_bytes        INTEGER NOT NULL,
    source_mtime_utc  TEXT NOT NULL,
    kind              TEXT NOT NULL,
    store_path        TEXT NOT NULL,                  -- content-addressed immutable copy
    ingested_at       TEXT NOT NULL,
    UNIQUE (session_date, rel_path)
);

CREATE TABLE IF NOT EXISTS facts (
    fact_id           TEXT PRIMARY KEY,
    session_date      TEXT NOT NULL REFERENCES sessions(session_date),
    evidence_id       INTEGER NOT NULL REFERENCES evidence(evidence_id),
    pointer           TEXT NOT NULL,                  -- RFC 6901 JSON pointer into the evidence file
    kind              TEXT NOT NULL,
    topic             TEXT NOT NULL,
    basis             TEXT NOT NULL CHECK (basis IN ('observed','paper','shadow','real')),
    value_json        TEXT NOT NULL,
    UNIQUE (evidence_id, pointer)
);

CREATE TABLE IF NOT EXISTS stories (
    story_id                 TEXT PRIMARY KEY,
    session_date             TEXT NOT NULL REFERENCES sessions(session_date),
    topic                    TEXT NOT NULL,
    state                    TEXT NOT NULL,
    score                    REAL NOT NULL,
    score_breakdown_json     TEXT NOT NULL,
    plan_json                TEXT NOT NULL,          -- hook + 3 bullets -> fact_ids
    fixture                  INTEGER NOT NULL DEFAULT 0,
    attempts                 INTEGER NOT NULL DEFAULT 0,
    last_error               TEXT,
    failed_from_state        TEXT,
    content_sha256           TEXT,
    approved_content_sha256  TEXT,
    approved_by              TEXT,
    approved_at              TEXT,
    version                  INTEGER NOT NULL DEFAULT 0,  -- bumped on every transition (CAS)
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    UNIQUE (session_date, topic)
);

CREATE TABLE IF NOT EXISTS drafts (
    story_id      TEXT NOT NULL REFERENCES stories(story_id),
    lang          TEXT NOT NULL,
    body_json     TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    PRIMARY KEY (story_id, lang)
);

CREATE TABLE IF NOT EXISTS artifacts (
    story_id      TEXT NOT NULL REFERENCES stories(story_id),
    name          TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    PRIMARY KEY (story_id, name)
);

CREATE TABLE IF NOT EXISTS schedules (
    schedule_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id           TEXT NOT NULL REFERENCES stories(story_id),
    platform           TEXT NOT NULL,
    adapter            TEXT NOT NULL,
    wave               TEXT NOT NULL,
    publish_at_utc     TEXT NOT NULL,
    publish_at_jst     TEXT NOT NULL,
    audience_tz        TEXT NOT NULL,
    audience_local     TEXT NOT NULL,
    status             TEXT NOT NULL,                 -- SCHEDULED | CANCELLED
    idempotency_key    TEXT NOT NULL UNIQUE,
    payload_path       TEXT NOT NULL,
    payload_sha256     TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    UNIQUE (story_id, platform)                       -- same story can never go out twice per platform
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_schedules_slot
    ON schedules(platform, publish_at_utc) WHERE status = 'SCHEDULED';

CREATE TABLE IF NOT EXISTS controls (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL
);

-- Append-only, hash-chained audit trail.
CREATE TABLE IF NOT EXISTS audit_log (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc        TEXT NOT NULL,
    actor         TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    action        TEXT NOT NULL,
    from_state    TEXT,
    to_state      TEXT,
    detail_json   TEXT NOT NULL,
    prev_hash     TEXT NOT NULL,
    hash          TEXT NOT NULL UNIQUE
);

CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
