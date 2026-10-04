"""Explicit state machines for sessions and stories.

Spec pipeline: INGEST -> VALIDATE -> STORY_SELECT -> FACT_CHECK -> SCRIPT ->
LOCALIZE -> ASSET_RENDER -> APPROVAL -> SCHEDULE -> (PUBLISH ...)

States record the *completed* stage. INGEST/VALIDATE operate on a session (one
trading day of evidence); the remaining stages operate on individual stories.
R1 stops at SCHEDULED: there is deliberately no transition into PUBLISHING.

Transitions are compare-and-set on (state, version) and always write an audit
row in the same transaction.
"""
from __future__ import annotations

import sqlite3
from enum import Enum

from . import audit
from .clock import Clock, iso_utc
from .db import transaction
from .errors import InvalidTransitionError, StateConflictError


class SessionState(str, Enum):
    INGESTED = "INGESTED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class StoryState(str, Enum):
    SELECTED = "SELECTED"                    # STORY_SELECT done
    FACT_CHECKED = "FACT_CHECKED"            # FACT_CHECK done
    SCRIPTED = "SCRIPTED"                    # SCRIPT done
    LOCALIZED = "LOCALIZED"                  # LOCALIZE (+ compliance) done
    RENDERED = "RENDERED"                    # ASSET_RENDER done
    AWAITING_APPROVAL = "AWAITING_APPROVAL"  # APPROVAL pending (human)
    APPROVED = "APPROVED"                    # APPROVAL granted
    SCHEDULED = "SCHEDULED"                  # SCHEDULE done (dry-run payloads written) -- R1 terminal
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


SESSION_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.INGESTED: {SessionState.VALIDATED, SessionState.FAILED},
    SessionState.VALIDATED: set(),
    SessionState.FAILED: set(),
}

S = StoryState
STORY_TRANSITIONS: dict[StoryState, set[StoryState]] = {
    S.SELECTED: {S.FACT_CHECKED, S.FAILED, S.CANCELLED},
    S.FACT_CHECKED: {S.SCRIPTED, S.FAILED, S.CANCELLED},
    S.SCRIPTED: {S.LOCALIZED, S.FAILED, S.CANCELLED},
    S.LOCALIZED: {S.RENDERED, S.FAILED, S.CANCELLED},
    S.RENDERED: {S.AWAITING_APPROVAL, S.FAILED, S.CANCELLED},
    S.AWAITING_APPROVAL: {S.APPROVED, S.FAILED, S.CANCELLED},
    S.APPROVED: {S.SCHEDULED, S.FAILED, S.CANCELLED},
    S.SCHEDULED: {S.CANCELLED},              # R1: no PUBLISHING state exists
    # Retry re-enters the state *before* the stage that failed.
    S.FAILED: {S.SELECTED, S.FACT_CHECKED, S.SCRIPTED, S.LOCALIZED, S.RENDERED, S.APPROVED, S.CANCELLED},
    S.CANCELLED: set(),
}

# Stage that runs *from* each state (used by the runner and by retry bookkeeping).
NEXT_STAGE: dict[StoryState, str] = {
    S.SELECTED: "FACT_CHECK",
    S.FACT_CHECKED: "SCRIPT",
    S.SCRIPTED: "LOCALIZE",
    S.LOCALIZED: "ASSET_RENDER",
    S.RENDERED: "APPROVAL_REQUEST",
    S.APPROVED: "SCHEDULE",
}


def can_transition(frm: StoryState, to: StoryState) -> bool:
    return to in STORY_TRANSITIONS.get(frm, set())


def transition_story(
    conn: sqlite3.Connection,
    clock: Clock,
    story_id: str,
    frm: StoryState,
    to: StoryState,
    *,
    actor: str,
    reason: str = "",
    extra_updates: dict | None = None,
    detail: dict | None = None,
) -> int:
    """CAS transition. Returns the new version. Raises on illegal or lost race."""
    if not can_transition(frm, to):
        raise InvalidTransitionError(f"{story_id}: {frm.value} -> {to.value} is not allowed")
    extra_updates = dict(extra_updates or {})
    now = iso_utc(clock.now())
    with transaction(conn):
        row = conn.execute("SELECT state, version FROM stories WHERE story_id = ?", (story_id,)).fetchone()
        if row is None:
            raise InvalidTransitionError(f"unknown story {story_id}")
        if row["state"] != frm.value:
            raise StateConflictError(f"{story_id}: expected {frm.value}, found {row['state']}")
        sets = ["state = :to", "version = version + 1", "updated_at = :now"]
        params = {"to": to.value, "now": now, "sid": story_id, "frm": frm.value, "ver": row["version"]}
        for i, (col, val) in enumerate(extra_updates.items()):
            if not col.isidentifier():
                raise ValueError(f"bad column {col!r}")
            sets.append(f"{col} = :x{i}")
            params[f"x{i}"] = val
        cur = conn.execute(
            f"UPDATE stories SET {', '.join(sets)} WHERE story_id = :sid AND state = :frm AND version = :ver",
            params,
        )
        if cur.rowcount != 1:
            raise StateConflictError(f"{story_id}: concurrent modification")
        audit.append(
            conn, clock, actor=actor, entity_type="story", entity_id=story_id, action="transition",
            from_state=frm.value, to_state=to.value, detail={"reason": reason, **(detail or {})},
        )
        return row["version"] + 1


def transition_session(
    conn: sqlite3.Connection,
    clock: Clock,
    session_date: str,
    frm: SessionState,
    to: SessionState,
    *,
    actor: str,
    reason: str = "",
    extra_updates: dict | None = None,
    detail: dict | None = None,
) -> None:
    if to not in SESSION_TRANSITIONS.get(frm, set()):
        raise InvalidTransitionError(f"session {session_date}: {frm.value} -> {to.value} is not allowed")
    now = iso_utc(clock.now())
    extra_updates = dict(extra_updates or {})
    with transaction(conn):
        sets = ["state = :to", "updated_at = :now"]
        params = {"to": to.value, "now": now, "d": session_date, "frm": frm.value}
        for i, (col, val) in enumerate(extra_updates.items()):
            if not col.isidentifier():
                raise ValueError(f"bad column {col!r}")
            sets.append(f"{col} = :x{i}")
            params[f"x{i}"] = val
        cur = conn.execute(
            f"UPDATE sessions SET {', '.join(sets)} WHERE session_date = :d AND state = :frm", params
        )
        if cur.rowcount != 1:
            raise StateConflictError(f"session {session_date}: expected {frm.value}")
        audit.append(
            conn, clock, actor=actor, entity_type="session", entity_id=session_date, action="transition",
            from_state=frm.value, to_state=to.value, detail={"reason": reason, **(detail or {})},
        )
