"""Clock policy: a time override is only allowed in an explicitly initialised sandbox home.

Production-equivalent homes always use the real clock. ``--now`` and
``AUTO_PUBLISH_NOW`` are refused there (CLOCK_OVERRIDE_REFUSED), because an
arbitrary "now" would let a write forge knowledge time (metrics known_at),
dispatch timing (would_publish / MISSED), ingest freshness and audit timestamps.

A home becomes a sandbox only through ``sandbox-init`` on an EMPTY database
(recorded in ``controls`` with an audit row, using the real clock). There is no
way back and no way to turn a home that already holds data into a sandbox.
Library code and unit tests inject clocks directly (FixedClock) and do not go
through this gate.
"""
from __future__ import annotations

import sqlite3

from . import controls
from .clock import Clock, FixedClock, parse_aware
from .errors import ValidationError

SANDBOX_KEY = "home.sandbox"
DATA_TABLES = ("sessions", "stories", "schedules", "dispatches", "metrics_imports", "post_metrics",
               "slot_proposals", "shadow_evaluations", "audit_log")


def is_sandbox(conn: sqlite3.Connection) -> bool:
    return controls._get(conn, SANDBOX_KEY) == "1"


def init_sandbox(conn: sqlite3.Connection, clock: Clock, actor: str) -> dict:
    if isinstance(clock, FixedClock):
        raise ValidationError("sandbox-init must run on the real clock", code="CLOCK_OVERRIDE_REFUSED")
    if is_sandbox(conn):
        return {"sandbox": True, "noop": True}
    used = {t: n for t in DATA_TABLES if (n := conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])}
    if used or conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]:
        raise ValidationError("sandbox-init requires an empty home (this one already holds data)",
                              code="SANDBOX_REQUIRES_EMPTY_HOME", details={"rows": used})
    controls._set(conn, clock, SANDBOX_KEY, "1", actor, "sandbox home: clock override allowed")
    return {"sandbox": True, "noop": False}


def resolve_clock(conn: sqlite3.Connection, override: str | None) -> Clock:
    """Real clock unless an override is given AND the home is a sandbox; otherwise fail-closed."""
    if not override:
        return Clock()
    if not is_sandbox(conn):
        raise ValidationError("clock override (--now / AUTO_PUBLISH_NOW) is refused on a production home;"
                              " run on a sandbox home created with sandbox-init", code="CLOCK_OVERRIDE_REFUSED")
    return FixedClock(parse_aware(override))
