"""WOULD_PUBLISH simulator -- the last stage of the dry-run E2E.

``would_publish`` is an *audit event*, not a publication: it records that at the
scheduled time every precondition for sending held in DRY-RUN. Nothing is sent,
no network is used, and the story itself stays SCHEDULED (R1 has no PUBLISH).

Per schedule row (one story x one platform)::

    SCHEDULED --claim--> DISPATCHING --verify ok--> WOULD_PUBLISH      (terminal)
                              |------ verify fails --> BLOCKED         (terminal, fail-closed)
                              |------ kill switch / cancel --> SCHEDULED / CANCELLED (attempt ABORTED)
                              '------ crash, lease expired --> UNKNOWN (terminal; never auto-resent)
    SCHEDULED --later than max_lateness--> MISSED                      (terminal; never sent late)

Invariants
* at most one live/terminal attempt per schedule and one WOULD_PUBLISH per
  idempotency key (DB unique indexes; terminal rows immutable by trigger);
* claim and outcome are separate committed transactions, each with its audit row;
  an attempt found IN_FLIGHT after its lease is UNKNOWN -- its outcome is never
  assumed and it is never retried automatically;
* the kill switches are checked before claiming and again inside the recording
  transaction; PAUSE ALL stops the whole run;
* verification re-derives everything from the hash-chained audit log, the
  evidence store and the artifact hashes: approval row == story approval, schedule
  row == scheduled payload, payload == what the approved content produces now.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Callable

from .. import audit, controls
from ..clock import iso_utc, parse_aware
from ..compliance import rules as compliance
from ..context import Ctx
from ..db import transaction
from ..errors import (
    AdapterNotAllowedError, ApprovalError, AutoPublishError, EvidenceError, FailClosedError,
)
from ..evidence import store as ev
from ..hashing import canonical_json, json_file_bytes, sha256_bytes, sha256_file, sha256_json
from ..publishers.contract import CONTRACT_VERSION, validate_payload
from ..publishers.registry import get_adapter
from ..state_machine import StoryState as S
from ..tts import narration as tts

TRACE_SCHEMA = "auto_publish.would_publish.v1"
MEANING = ("DRY-RUN simulation: every send precondition held at the scheduled time. "
           "Nothing was sent to any platform.")
Hook = Callable[[str, dict], None]


class SimulatedCrash(BaseException):
    """Test-only: raised from a hook to model the process dying at that point."""


def _audit(ctx: Ctx, row, action: str, frm: str | None, to: str | None, detail: dict, actor: str) -> str:
    return audit.append(ctx.conn, ctx.clock, actor=actor, entity_type="schedule",
                        entity_id=f"{row['story_id']}:{row['platform']}", action=action,
                        from_state=frm, to_state=to, detail=detail)


# ------------------------------------------------------------------ verification

def _audit_row(ctx: Ctx, story_id: str, to_state: str):
    return ctx.conn.execute(
        "SELECT hash, detail_json FROM audit_log WHERE entity_type='story' AND entity_id=? AND to_state=?"
        " ORDER BY seq DESC LIMIT 1", (story_id, to_state)).fetchone()


def verify_for_dispatch(ctx: Ctx, row) -> dict:
    """Everything that must hold for a send, re-derived from source. Raises FailClosedError."""
    from .. import pipeline  # late import: pipeline imports publishers

    story = pipeline._story(ctx, row["story_id"])
    if story["state"] != S.SCHEDULED.value:
        raise ApprovalError(f"story is {story['state']}, not SCHEDULED", code="STORY_NOT_SCHEDULED")
    approved = story["approved_content_sha256"]
    if not story["approved_by"] or not approved:
        raise ApprovalError("approval record missing", code="APPROVAL_MISSING")
    adapter = get_adapter(row["platform"], ctx.cfg)            # dry_run only, else AdapterNotAllowedError
    if row["adapter"] != adapter.name:
        raise AdapterNotAllowedError(f"schedule adapter {row['adapter']!r} != {adapter.name!r}")

    # approval and schedule as recorded in the hash-chained audit log
    chain = audit.verify_chain(ctx.conn)
    if not chain["ok"]:
        raise EvidenceError("audit chain broken", code="AUDIT_CHAIN_BROKEN", details=chain)
    appr = _audit_row(ctx, row["story_id"], S.APPROVED.value)
    if appr is None or json.loads(appr["detail_json"]).get("approved_content_sha256") != approved:
        raise EvidenceError("story approval differs from the audited approval", code="APPROVAL_AUDIT_MISMATCH")
    sched = _audit_row(ctx, row["story_id"], S.SCHEDULED.value)
    entries = {e["platform"]: e for e in json.loads(sched["detail_json"]).get("entries", [])} if sched else {}
    e = entries.get(row["platform"])
    if e is None or (e["idempotency_key"], e["payload_sha256"], e["publish_at_utc"], e["payload_path"]) != (
            row["idempotency_key"], row["payload_sha256"], row["publish_at_utc"], row["payload_path"]):
        raise EvidenceError("schedule row differs from the audited schedule", code="SCHEDULE_AUDIT_MISMATCH")

    # evidence, artifacts (incl. narration/captions), approval binding
    ev.verify_session(ctx.conn, story["session_date"])
    content = pipeline.verify_artifacts(ctx, story)
    if content != approved:
        raise EvidenceError("artifacts differ from the approved version", code="APPROVED_CONTENT_CHANGED")
    if row["idempotency_key"] != pipeline.idempotency_key(row["story_id"], row["platform"], approved):
        raise EvidenceError("idempotency key does not match the approved content", code="IDEMPOTENCY_KEY_MISMATCH")
    sdir = pipeline.story_dir(ctx, story)
    post_en = json.loads((sdir / "post_en.json").read_text(encoding="utf-8"))
    post_ja = json.loads((sdir / "post_ja.json").read_text(encoding="utf-8"))
    compliance.enforce([post_en, post_ja], story["session_date"])
    tts.verify(sdir, [post_en, post_ja])

    # payload: on disk == scheduled == contract-valid == re-derived from approved content now
    ppath = ctx.paths.artifacts / row["payload_path"]
    if not ppath.is_file():
        raise EvidenceError("dry-run payload missing", code="PAYLOAD_MISSING")
    if sha256_file(ppath) != row["payload_sha256"]:
        raise EvidenceError("dry-run payload changed after scheduling", code="PAYLOAD_TAMPERED")
    validate_payload(json.loads(ppath.read_text(encoding="utf-8")), row["platform"])
    session = ctx.conn.execute("SELECT manifest_sha256 FROM sessions WHERE session_date = ?",
                               (story["session_date"],)).fetchone()
    manifest = json.loads((sdir / "render_manifest.json").read_text(encoding="utf-8"))
    slot = {k: row[k] for k in ("wave", "publish_at_utc", "publish_at_jst", "audience_tz", "audience_local")}
    bundle = pipeline.post_bundle(story, row["platform"], sdir, post_en, post_ja, manifest, content,
                                  session["manifest_sha256"], row["idempotency_key"], slot)
    adapter.validate_asset(bundle)
    rebuilt = adapter.build_payload(bundle, parse_aware(row["publish_at_utc"]))
    if sha256_bytes(json_file_bytes(rebuilt)) != row["payload_sha256"]:
        raise EvidenceError("payload is not what the approved content produces", code="PAYLOAD_MISMATCH")

    artifacts = {r["name"]: r["sha256"] for r in ctx.conn.execute(
        "SELECT name, sha256 FROM artifacts WHERE story_id = ? ORDER BY name", (row["story_id"],))}
    narration = {}
    tm = sdir / tts.TTS_MANIFEST
    if tm.is_file():
        narration = {lang: m["narration_sha256"]
                     for lang, m in json.loads(tm.read_text(encoding="utf-8"))["langs"].items()}
    return {
        "story_id": row["story_id"], "session_date": story["session_date"], "platform": row["platform"],
        "adapter": adapter.name, "schedule_id": row["schedule_id"], "idempotency_key": row["idempotency_key"],
        "scheduled_publish_at_utc": row["publish_at_utc"], "wave": row["wave"],
        "approved_by": story["approved_by"], "approved_content_sha256": approved,
        "approval_audit_hash": appr["hash"], "schedule_audit_hash": sched["hash"],
        "evidence_manifest_sha256": session["manifest_sha256"], "artifacts": artifacts, "narration": narration,
        "payload": {"path": row["payload_path"], "sha256": row["payload_sha256"], "contract": CONTRACT_VERSION},
        "fixture": bool(story["fixture"]),
    }


# ------------------------------------------------------------------ runner

def _reconcile(ctx: Ctx, now_s: str, actor: str) -> list[dict]:
    """IN_FLIGHT past its lease => UNKNOWN. Never resent, never assumed done."""
    out = []
    for d in ctx.conn.execute("SELECT * FROM dispatches WHERE status='IN_FLIGHT' AND lease_until < ?"
                              " ORDER BY dispatch_id", (now_s,)).fetchall():
        err = {"code": "DISPATCH_OUTCOME_UNKNOWN",
               "message": "attempt still IN_FLIGHT after its lease (crash/restart?); outcome not assumed;"
                          " no automatic retry or resend"}
        with transaction(ctx.conn):
            n = ctx.conn.execute("UPDATE dispatches SET status='UNKNOWN', finished_at=?, error_json=?"
                                 " WHERE dispatch_id=? AND status='IN_FLIGHT'",
                                 (now_s, canonical_json(err), d["dispatch_id"])).rowcount
            if n != 1:
                continue
            ctx.conn.execute("UPDATE schedules SET status='UNKNOWN' WHERE schedule_id=? AND status='DISPATCHING'",
                             (d["schedule_id"],))
            _audit(ctx, d, "dispatch_unknown", "DISPATCHING", "UNKNOWN",
                   {"dispatch_id": d["dispatch_id"], "runner_id": d["runner_id"], **err}, actor)
        out.append({"dispatch_id": d["dispatch_id"], "story_id": d["story_id"], "platform": d["platform"],
                    "status": "UNKNOWN"})
    return out


def _finish(ctx: Ctx, row, dispatch_id: int, status: str, now_s: str, actor: str, *,
            schedule_status: str, detail: dict, trace: dict | None = None, action: str) -> dict:
    trace_sha = sha256_json(trace) if trace is not None else None
    err = detail.get("error")
    ctx.conn.execute(
        "UPDATE dispatches SET status=?, finished_at=?, trace_json=?, trace_sha256=?, error_json=?"
        " WHERE dispatch_id=? AND status='IN_FLIGHT'",
        (status, now_s, canonical_json(trace) if trace is not None else None, trace_sha,
         canonical_json(err) if err else None, dispatch_id))
    ctx.conn.execute("UPDATE schedules SET status=? WHERE schedule_id=? AND status='DISPATCHING'",
                     (schedule_status, row["schedule_id"]))
    _audit(ctx, row, action, "DISPATCHING", schedule_status,
           {"dispatch_id": dispatch_id, "sent": False, **({"trace_sha256": trace_sha} if trace_sha else {}),
            **detail}, actor)
    return {"dispatch_id": dispatch_id, "story_id": row["story_id"], "platform": row["platform"],
            "status": status, "schedule_status": schedule_status, "trace_sha256": trace_sha,
            **({"error": err} if err else {}), **({"reason": detail["reason"]} if "reason" in detail else {})}


def _claim(ctx: Ctx, row, runner_id: str, actor: str, now_s: str, lease_until: str, late, dcfg: dict,
           base: dict):
    """Returns the new dispatch_id, or a finished result dict (not claimed / missed)."""
    with transaction(ctx.conn):
        if ctx.conn.execute("UPDATE schedules SET status='DISPATCHING' WHERE schedule_id=? AND status='SCHEDULED'",
                            (row["schedule_id"],)).rowcount != 1:
            return {**base, "status": "NOT_CLAIMED"}          # another runner got there first
        cur = ctx.conn.execute(
            "INSERT INTO dispatches(schedule_id, story_id, platform, idempotency_key, status, runner_id, claimed_at,"
            " lease_until) VALUES (?,?,?,?, 'IN_FLIGHT', ?,?,?)",
            (row["schedule_id"], row["story_id"], row["platform"], row["idempotency_key"], runner_id, now_s,
             lease_until))
        dispatch_id = cur.lastrowid
        _audit(ctx, row, "dispatch_claimed", "SCHEDULED", "DISPATCHING",
               {"dispatch_id": dispatch_id, "runner_id": runner_id, "idempotency_key": row["idempotency_key"],
                "lease_until": lease_until, "sent": False}, actor)
        if late > timedelta(minutes=int(dcfg["max_lateness_minutes"])):
            return _finish(ctx, row, dispatch_id, "MISSED", now_s, actor, schedule_status="MISSED",
                           action="dispatch_missed",
                           detail={"reason": "SCHEDULE_WINDOW_MISSED",
                                   "lateness_seconds": int(late.total_seconds())})
    return dispatch_id


def _dispatch_one(ctx: Ctx, row, runner_id: str, actor: str, hook: Hook | None) -> dict:
    now = ctx.clock.now()
    now_s = iso_utc(now)
    dcfg = ctx.cfg["dispatch"]
    base = {"story_id": row["story_id"], "platform": row["platform"], "schedule_id": row["schedule_id"]}
    pcfg = ctx.cfg["platforms"].get(row["platform"], {})
    if controls.is_paused(ctx.conn):                          # PAUSE ALL set during this run
        with transaction(ctx.conn):
            _audit(ctx, row, "dispatch_skipped", "SCHEDULED", "SCHEDULED",
                   {"reason": "PAUSE_ALL", "sent": False}, actor)
        return {**base, "status": "SKIPPED", "reason": "PAUSE_ALL"}
    if not controls.platform_enabled(ctx.conn, row["platform"], pcfg.get("enabled", False)):
        with transaction(ctx.conn):
            _audit(ctx, row, "dispatch_skipped", "SCHEDULED", "SCHEDULED",
                   {"reason": "PLATFORM_DISABLED", "sent": False}, actor)
        return {**base, "status": "SKIPPED", "reason": "PLATFORM_DISABLED"}

    late = now - parse_aware(row["publish_at_utc"])
    lease_until = iso_utc(now + timedelta(seconds=int(dcfg["lease_seconds"])))
    try:
        claimed = _claim(ctx, row, runner_id, actor, now_s, lease_until, late, dcfg, base)
    except sqlite3.IntegrityError as exc:
        # A second attempt for a schedule that already has one (or a second WOULD_PUBLISH for the
        # same idempotency key): the DB refuses it; the claim was rolled back. Never sent.
        with transaction(ctx.conn):
            _audit(ctx, row, "dispatch_duplicate_refused", row["status"], row["status"],
                   {"reason": "DUPLICATE_DISPATCH", "db_error": str(exc), "sent": False}, actor)
        return {**base, "status": "DUPLICATE_REFUSED"}
    if not isinstance(claimed, int):
        return claimed
    dispatch_id = claimed
    if hook:
        hook("after_claim", {**base, "dispatch_id": dispatch_id})

    trace, error = None, None
    try:
        trace = verify_for_dispatch(ctx, row)
    except FailClosedError as exc:
        error = exc.to_dict()
    except AutoPublishError as exc:
        error = exc.to_dict()
    except Exception as exc:  # unexpected => fail-closed, never "probably fine"
        error = {"type": type(exc).__name__, "code": "UNEXPECTED", "message": str(exc)}
    if hook:
        hook("before_record", {**base, "dispatch_id": dispatch_id})

    with transaction(ctx.conn):
        d = ctx.conn.execute("SELECT status, lease_until FROM dispatches WHERE dispatch_id=?",
                             (dispatch_id,)).fetchone()
        if d["status"] != "IN_FLIGHT":                        # reconciled by another runner meanwhile
            return {**base, "dispatch_id": dispatch_id, "status": d["status"]}
        now_s = iso_utc(ctx.clock.now())
        story_state = ctx.conn.execute("SELECT state FROM stories WHERE story_id=?",
                                       (row["story_id"],)).fetchone()["state"]
        if now_s > d["lease_until"]:
            return _finish(ctx, row, dispatch_id, "UNKNOWN", now_s, actor, schedule_status="UNKNOWN",
                           action="dispatch_unknown",
                           detail={"error": {"code": "DISPATCH_LEASE_EXPIRED",
                                             "message": "verification outlived its lease; outcome not assumed"}})
        if story_state == S.CANCELLED.value:
            return _finish(ctx, row, dispatch_id, "ABORTED", now_s, actor, schedule_status="CANCELLED",
                           action="dispatch_aborted", detail={"reason": "STORY_CANCELLED"})
        if controls.is_paused(ctx.conn) or not controls.platform_enabled(ctx.conn, row["platform"],
                                                                          pcfg.get("enabled", False)):
            return _finish(ctx, row, dispatch_id, "ABORTED", now_s, actor, schedule_status="SCHEDULED",
                           action="dispatch_aborted", detail={"reason": "KILL_SWITCH"})
        if error is not None:
            return _finish(ctx, row, dispatch_id, "BLOCKED", now_s, actor, schedule_status="BLOCKED",
                           action="dispatch_blocked", detail={"error": error})
        trace = {"schema": TRACE_SCHEMA, "dry_run": True, "network": "none", "sent": False, "meaning": MEANING,
                 "dispatch_id": dispatch_id, "evaluated_at_utc": now_s,
                 "lateness_seconds": int(late.total_seconds()), **trace}
        result = _finish(ctx, row, dispatch_id, "WOULD_PUBLISH", now_s, actor, schedule_status="WOULD_PUBLISH",
                         action="would_publish", trace=trace, detail={"meaning": MEANING})
        if hook:
            hook("in_record", {**base, "dispatch_id": dispatch_id})
        return result


def run_due(ctx: Ctx, *, runner_id: str | None = None, hook: Hook | None = None) -> dict:
    """One pass: reconcile stale attempts, then evaluate every due schedule. Idempotent."""
    now_s = iso_utc(ctx.clock.now())
    runner_id = runner_id or f"{ctx.actor}@{now_s}"
    out = {"evaluated_at_utc": now_s, "dry_run": True, "network": "none", "sent": 0,
           "reconciled_unknown": _reconcile(ctx, now_s, ctx.actor), "results": []}
    due = ctx.conn.execute(
        "SELECT * FROM schedules WHERE status='SCHEDULED' AND publish_at_utc <= ?"
        " ORDER BY publish_at_utc, platform, schedule_id", (now_s,)).fetchall()
    if controls.is_paused(ctx.conn):
        with transaction(ctx.conn):
            audit.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="dispatch_run", entity_id=now_s,
                         action="dispatch_run_blocked", detail={"reason": "PAUSE_ALL", "due": len(due), "sent": False})
        out["blocked"] = "PAUSE_ALL"
        out["due"] = len(due)
        return out
    for row in due:
        out["results"].append(_dispatch_one(ctx, row, runner_id, ctx.actor, hook))
    return out


def list_dispatches(ctx: Ctx, story_id: str | None = None) -> list[dict]:
    q = "SELECT * FROM dispatches" + (" WHERE story_id = ?" if story_id else "") + " ORDER BY dispatch_id"
    rows = []
    for d in ctx.conn.execute(q, (story_id,) if story_id else ()):
        r = dict(d)
        r["trace"] = json.loads(r.pop("trace_json")) if r["trace_json"] else None
        r["error"] = json.loads(r.pop("error_json")) if r["error_json"] else None
        rows.append(r)
    return rows
