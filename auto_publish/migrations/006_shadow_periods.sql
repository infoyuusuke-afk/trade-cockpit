-- Multi-business-day shadow observation (contract auto_publish.shadow_period.v1): append-only,
-- point-in-time period records built from STORED shadow_day.v1 records only.
-- Identity = (date_from, date_to, observation_as_of_utc, contract). An identical re-run is a no-op and
-- a different result for the same identity is refused in code (SHADOW_PERIOD_CONFLICT); rows are never
-- updated or deleted (triggers). generated_at_utc (wall clock) is stored here, outside the hashed report.
-- Additive only: no existing table or row is touched.
CREATE TABLE IF NOT EXISTS shadow_periods (
    record_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date_from              TEXT NOT NULL,
    date_to                TEXT NOT NULL,
    observation_as_of_utc  TEXT NOT NULL,
    contract               TEXT NOT NULL,
    generated_at_utc       TEXT NOT NULL,
    report_json            TEXT NOT NULL,
    report_sha256          TEXT NOT NULL CHECK (length(report_sha256) = 64),
    period_status          TEXT NOT NULL CHECK (period_status IN ('OK','UNKNOWN','VIOLATION')),
    CHECK (date_from <= date_to),
    UNIQUE (date_from, date_to, observation_as_of_utc, contract)
);
CREATE TRIGGER IF NOT EXISTS shadow_periods_append_only_u BEFORE UPDATE ON shadow_periods
BEGIN SELECT RAISE(ABORT, 'shadow_periods is append-only'); END;
CREATE TRIGGER IF NOT EXISTS shadow_periods_append_only_d BEFORE DELETE ON shadow_periods
BEGIN SELECT RAISE(ABORT, 'shadow_periods is append-only'); END;
