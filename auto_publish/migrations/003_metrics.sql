-- Timing optimisation (proposal-only): post metrics, point-in-time snapshots, proposals, shadow evaluations.
-- Every table here is append-only. Nothing in this phase changes a schedule.

CREATE TABLE IF NOT EXISTS metrics_imports (
    import_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL,
    source_name      TEXT NOT NULL,                 -- file name only (no local path)
    sha256           TEXT NOT NULL CHECK (length(sha256) = 64),
    size_bytes       INTEGER NOT NULL,
    contract         TEXT NOT NULL,
    rows_total       INTEGER NOT NULL,
    rows_new         INTEGER NOT NULL,
    rows_duplicate   INTEGER NOT NULL,
    store_path       TEXT NOT NULL,                 -- read-only content-addressed copy of the raw CSV
    imported_at_utc  TEXT NOT NULL,                 -- knowledge time for every row first seen here
    imported_by      TEXT NOT NULL,
    UNIQUE (platform, sha256)
);

-- One row per (post, observation time). A later snapshot of the same post is a new row;
-- a different value for an existing (post, observed_at) is refused (no silent rewrite of the past).
CREATE TABLE IF NOT EXISTS post_metrics (
    obs_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id               INTEGER NOT NULL REFERENCES metrics_imports(import_id),
    platform                TEXT NOT NULL,
    post_ref                TEXT NOT NULL,
    story_id                TEXT,
    published_at_utc        TEXT NOT NULL,
    observed_at_utc         TEXT NOT NULL,
    known_at_utc            TEXT NOT NULL,
    impressions             INTEGER,
    views                   INTEGER,
    watch_time_seconds      INTEGER,
    completion_rate         REAL,
    likes                   INTEGER,
    comments                INTEGER,
    shares                  INTEGER,
    saves                   INTEGER,
    follows_gained          INTEGER,
    video_duration_seconds  REAL,
    row_sha256              TEXT NOT NULL,
    UNIQUE (platform, post_ref, observed_at_utc)
);
CREATE INDEX IF NOT EXISTS ix_post_metrics_pit ON post_metrics(platform, known_at_utc, observed_at_utc);

CREATE TABLE IF NOT EXISTS slot_proposals (
    proposal_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    platform           TEXT NOT NULL,
    as_of_utc          TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('PROPOSED','BASELINE_CONFIRMED','INCONCLUSIVE')),
    algorithm_version  TEXT NOT NULL,
    input_sha256       TEXT NOT NULL,
    proposal_json      TEXT NOT NULL,
    proposal_sha256    TEXT NOT NULL,
    created_at_utc     TEXT NOT NULL,
    UNIQUE (platform, as_of_utc, input_sha256, algorithm_version)
);

CREATE TABLE IF NOT EXISTS shadow_evaluations (
    eval_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id      INTEGER NOT NULL REFERENCES slot_proposals(proposal_id),
    as_of_utc        TEXT NOT NULL,
    input_sha256     TEXT NOT NULL,
    result_json      TEXT NOT NULL,
    result_sha256    TEXT NOT NULL,
    created_at_utc   TEXT NOT NULL,
    UNIQUE (proposal_id, as_of_utc, input_sha256)
);

CREATE TRIGGER IF NOT EXISTS metrics_imports_append_only_u BEFORE UPDATE ON metrics_imports
BEGIN SELECT RAISE(ABORT, 'metrics_imports is append-only'); END;
CREATE TRIGGER IF NOT EXISTS metrics_imports_append_only_d BEFORE DELETE ON metrics_imports
BEGIN SELECT RAISE(ABORT, 'metrics_imports is append-only'); END;
CREATE TRIGGER IF NOT EXISTS post_metrics_append_only_u BEFORE UPDATE ON post_metrics
BEGIN SELECT RAISE(ABORT, 'post_metrics is append-only'); END;
CREATE TRIGGER IF NOT EXISTS post_metrics_append_only_d BEFORE DELETE ON post_metrics
BEGIN SELECT RAISE(ABORT, 'post_metrics is append-only'); END;
CREATE TRIGGER IF NOT EXISTS slot_proposals_append_only_u BEFORE UPDATE ON slot_proposals
BEGIN SELECT RAISE(ABORT, 'slot_proposals is append-only'); END;
CREATE TRIGGER IF NOT EXISTS slot_proposals_append_only_d BEFORE DELETE ON slot_proposals
BEGIN SELECT RAISE(ABORT, 'slot_proposals is append-only'); END;
CREATE TRIGGER IF NOT EXISTS shadow_evaluations_append_only_u BEFORE UPDATE ON shadow_evaluations
BEGIN SELECT RAISE(ABORT, 'shadow_evaluations is append-only'); END;
CREATE TRIGGER IF NOT EXISTS shadow_evaluations_append_only_d BEFORE DELETE ON shadow_evaluations
BEGIN SELECT RAISE(ABORT, 'shadow_evaluations is append-only'); END;
