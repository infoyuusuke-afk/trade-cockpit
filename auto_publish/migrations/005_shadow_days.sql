-- Shadow operation (contract auto_publish.shadow_day.v1): append-only, point-in-time evidence records.
-- Identity = (session_date, observation_as_of_utc, contract). An identical re-run is a no-op and a
-- different result for the same identity is refused in code (SHADOW_DAY_CONFLICT); rows are never
-- updated or deleted (triggers). generated_at_utc (wall clock) is stored here, outside the hashed report.
CREATE TABLE IF NOT EXISTS shadow_days (
    record_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date           TEXT NOT NULL REFERENCES sessions(session_date),
    observation_as_of_utc  TEXT NOT NULL,
    contract               TEXT NOT NULL,
    generated_at_utc       TEXT NOT NULL,
    report_json            TEXT NOT NULL,
    report_sha256          TEXT NOT NULL CHECK (length(report_sha256) = 64),
    day_status             TEXT NOT NULL CHECK (day_status IN ('OK','UNKNOWN','VIOLATION')),
    UNIQUE (session_date, observation_as_of_utc, contract)
);
CREATE TRIGGER IF NOT EXISTS shadow_days_append_only_u BEFORE UPDATE ON shadow_days
BEGIN SELECT RAISE(ABORT, 'shadow_days is append-only'); END;
CREATE TRIGGER IF NOT EXISTS shadow_days_append_only_d BEFORE DELETE ON shadow_days
BEGIN SELECT RAISE(ABORT, 'shadow_days is append-only'); END;
