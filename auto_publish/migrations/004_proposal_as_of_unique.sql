-- M2: at most one stored proposal per (platform, as_of, algorithm). A later re-evaluation must reproduce
-- it byte-for-byte (checked in code); a different result for the same as_of is refused, never stored beside it.
CREATE UNIQUE INDEX IF NOT EXISTS ux_slot_proposals_as_of
    ON slot_proposals(platform, as_of_utc, algorithm_version);
