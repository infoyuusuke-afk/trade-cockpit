"""Human kill switches: PAUSE ALL and per-platform DISABLE.

Absence of a key is interpreted fail-closed where it matters: a platform that
was never explicitly enabled is disabled unless the config enables it.
"""
from __future__ import annotations

import sqlite3

from . import audit
from .clock import Clock, iso_utc
from .db import transaction
from .errors import ControlBlockedError

PAUSED_KEY = "global.paused"


def _set(conn: sqlite3.Connection, clock: Clock, key: str, value: str, actor: str, reason: str) -> None:
    with transaction(conn):
        prev = conn.execute("SELECT value FROM controls WHERE key = ?", (key,)).fetchone()
        conn.execute(
            "INSERT INTO controls(key, value, updated_at, updated_by) VALUES (?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (key, value, iso_utc(clock.now()), actor),
        )
        audit.append(
            conn, clock, actor=actor, entity_type="control", entity_id=key, action="set",
            from_state=prev["value"] if prev else None, to_state=value, detail={"reason": reason},
        )


def _get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM controls WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def pause_all(conn, clock, actor: str, reason: str = "") -> None:
    _set(conn, clock, PAUSED_KEY, "1", actor, reason)


def resume_all(conn, clock, actor: str, reason: str = "") -> None:
    _set(conn, clock, PAUSED_KEY, "0", actor, reason)


def is_paused(conn) -> bool:
    return _get(conn, PAUSED_KEY) == "1"


def set_platform_enabled(conn, clock, platform: str, enabled: bool, actor: str, reason: str = "") -> None:
    _set(conn, clock, f"platform.{platform}.enabled", "1" if enabled else "0", actor, reason)


def platform_enabled(conn, platform: str, config_default: bool) -> bool:
    v = _get(conn, f"platform.{platform}.enabled")
    if v is None:
        return bool(config_default)
    return v == "1"


def require_not_paused(conn, action: str) -> None:
    if is_paused(conn):
        raise ControlBlockedError(f"PAUSE ALL is active; refusing {action}", details={"action": action})
