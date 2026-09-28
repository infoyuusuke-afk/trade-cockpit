"""Multi-business-day shadow observation -- contract ``auto_publish.shadow_period.v1``.

A period record observes a range of calendar dates [date_from, date_to] AS OF one
``observation_as_of`` (T). It reads ONLY:

* the TSE calendar (which dates are trading sessions),
* STORED ``shadow_day.v1`` records that were knowable at T
  (``observation_as_of_utc <= T`` AND ``generated_at_utc <= T``), and
* audit rows stamped <= T (session existence, record anchors, head presence).

It never re-evaluates a past day with current information and never rewrites a
day record: a day's verdict is copied from its latest stored record visible at T.
The only write is the period record itself plus its audit row. Nothing is sent;
no network is used.

Per trading date the period says one of
  OK / UNKNOWN / VIOLATION  -- copied from the day record (+ period-level evidence checks)
  PENDING                   -- not yet due at T and no final record yet (not counted)
  CLOSED                    -- not a TSE trading session (weekend / holiday)
A trading date is *due* at T once T >= the end of its last configured wave window
+ max_lateness + lease (from config; recorded in the body as ``due_rule``). A due
date without a session, without a visible record, or with a record made before
the day was resolved is UNKNOWN (SESSION_MISSING / SHADOW_DAY_MISSING /
SHADOW_DAY_PREMATURE) -- never guessed, never skipped.

Canonical hash: same rules as shadow_day.v1 (no floats, UTC ``Z`` second-precision
timestamps for ``*_utc`` keys, explicit nulls, sorted lists) with its own domain
prefix b"auto_publish.shadow_period.v1\\n". ``generated_at_utc`` of the period is
stored beside the record, never in the hashed body.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from .. import audit
from ..clock import iso_utc
from ..context import Ctx
from ..db import transaction
from ..errors import ValidationError
from ..hashing import canonical_json, sha256_bytes
from ..marketcal.tse import load_calendar
from ..scheduler.slots import wave_window
from . import day as shadow_day

CONTRACT = "auto_publish.shadow_period.v1"
HASH_DOMAIN = (CONTRACT + "\n").encode("utf-8")
MAX_RANGE_DAYS = 62
DEFAULT_ACCEPTANCE_DAYS = 5
OK, UNKNOWN, VIOLATION, PENDING, CLOSED = "OK", "UNKNOWN", "VIOLATION", "PENDING", "CLOSED"
VERIFIED, NA = shadow_day.VERIFIED, shadow_day.NA
UNRESOLVED_SCHEDULE = {"SCHEDULED", "DISPATCHING"}
PRE_SCHEDULE_STORY = {"SELECTED", "FACT_CHECKED", "SCRIPTED", "LOCALIZED", "RENDERED", "AWAITING_APPROVAL",
                      "APPROVED", "FAILED"}


def canonical_bytes(report: dict) -> bytes:
    shadow_day._validate(report)                    # same canonical rules as the day contract
    return HASH_DOMAIN + canonical_json(report).encode("utf-8")


def report_hash(report: dict) -> str:
    return sha256_bytes(canonical_bytes(report))


def acceptance_days(cfg: dict) -> int:
    n = (cfg.get("shadow") or {}).get("acceptance_trading_days", DEFAULT_ACCEPTANCE_DAYS)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_RANGE_DAYS:
        raise ValidationError(f"shadow.acceptance_trading_days must be an integer 1..{MAX_RANGE_DAYS}",
                              code="CONFIG_INVALID")
    return n


def due_rule(cfg: dict) -> dict:
    ends = sorted({(w["day_offset"], w["end_jst"]) for p in cfg["platforms"].values() for w in
                   (cfg["waves"][n] for n in p["waves"])})
    return {"last_wave_day_offset": int(ends[-1][0]), "last_wave_end_jst": ends[-1][1],
            "max_lateness_minutes": int(cfg["dispatch"]["max_lateness_minutes"]),
            "lease_seconds": int(cfg["dispatch"]["lease_seconds"])}


def due_at(session_date: str, rule: dict) -> datetime:
    _, end = wave_window(session_date, {"day_offset": rule["last_wave_day_offset"], "start_jst": "00:00",
                                        "end_jst": rule["last_wave_end_jst"]})
    return end + timedelta(minutes=rule["max_lateness_minutes"], seconds=rule["lease_seconds"])


def _range(date_from: str, date_to: str) -> list[date]:
    try:
        a, b = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError as exc:
        raise ValidationError(f"invalid date: {exc}", code="PERIOD_RANGE_INVALID") from exc
    if b < a or (b - a).days + 1 > MAX_RANGE_DAYS:
        raise ValidationError(f"period must be 1..{MAX_RANGE_DAYS} days with from <= to", code="PERIOD_RANGE_INVALID")
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


# ------------------------------------------------------------------ one date

def _latest_record(ctx: Ctx, session_date: str, t: str):
    return ctx.conn.execute(
        "SELECT * FROM shadow_days WHERE contract=? AND session_date=? AND observation_as_of_utc <= ?"
        " AND generated_at_utc <= ? ORDER BY observation_as_of_utc DESC, record_id DESC LIMIT 1",
        (shadow_day.CONTRACT, session_date, t, t)).fetchone()


def _anchored(vis: list[dict], row) -> bool:
    for r in vis:
        if r["action"] == "shadow_day_recorded" and r["entity_id"] == row["session_date"]:
            d = json.loads(r["detail_json"])
            if d.get("record_id") == row["record_id"] and d.get("report_sha256") == row["report_sha256"] \
                    and d.get("observation_as_of_utc") == row["observation_as_of_utc"]:
                return True
    return False


def _day_facts(rep: dict) -> dict:
    """Observation values copied from a stored day record (never recomputed)."""
    scheds = [(s, x) for x in rep["stories"] for s in x["schedules"]]
    kill = rep["kill_switch"]
    unresolved = [s["platform"] for s, _ in scheds if s["status_at_as_of"] in UNRESOLVED_SCHEDULE]
    held = [p for p in unresolved if kill["paused"] or not kill["platforms_enabled"].get(p, False)]
    subs = [x["content"]["ja_subtitles"] for x in rep["stories"] if x["content"] and x["content"]["ja_subtitles"]]
    margins = {}
    for x in rep["stories"]:
        for p, m in sorted(((x["content"] or {}).get("length_margins") or {}).items()):
            if m is not None:
                margins[p] = min(margins.get(p, m["margin"]), m["margin"])
    return {
        "stories": len(rep["stories"]),
        "would_publish": rep["dispatch_counts"].get("WOULD_PUBLISH", 0),
        **{k.lower(): rep["attention"][k] for k in ("BLOCKED", "IN_FLIGHT", "MISSED", "UNKNOWN")},
        "unresolved_schedules": len(unresolved), "held_by_kill_switch": len(held),
        "pre_schedule_stories": sum(x["state_at_as_of"] in PRE_SCHEDULE_STORY for x in rep["stories"]),
        "human_approval_verified": sum(x["human_approval"] == VERIFIED for x in rep["stories"]),
        "scheduled_stories": sum(bool(x["schedules"]) for x in rep["stories"]),
        "proposal_differs": sum(s["proposal_differs"] for s, _ in scheds),
        "proposal_available": sum(s["proposal_then"] is not None for s, _ in scheds),
        "kill_switch_paused": bool(kill["paused"]),
        "platforms_disabled": sorted(p for p, on in kill["platforms_enabled"].items() if not on),
        "compliance_violations": sum(x["content"]["compliance_violations"] for x in rep["stories"] if x["content"]),
        "min_length_margin": margins,
        "ja_suspected_midword_breaks_heuristic": sum(s["suspected_midword_breaks"] for s in subs),
        "ja_max_display_width": max([0] + [s["max_display_width"] for s in subs]),
    }


def _date_entry(ctx: Ctx, cal, d: date, t: str, vis: list[dict], heads: set, rule: dict) -> tuple[dict, dict | None]:
    ds = d.isoformat()
    st = cal.status(d)
    due = due_at(ds, rule)
    session_seen = any(r["entity_type"] == "session" and r["entity_id"] == ds for r in vis)
    entry = {"date": ds, "calendar": st.reason, "trading": st.trading, "due_at_utc": iso_utc(due) if st.trading else None,
             "due": bool(st.trading and iso_utc(due) <= t), "session_seen": session_seen, "record": None,
             "status": CLOSED, "reasons": [], "final": False, "full_chain": False, "facts": None}
    if not st.trading:
        if session_seen:
            entry.update(status=UNKNOWN, reasons=["SESSION_ON_CLOSED_DAY"])
        return entry, None
    row = _latest_record(ctx, ds, t)
    if row is None:
        if entry["due"]:
            entry.update(status=UNKNOWN, reasons=["SHADOW_DAY_MISSING" if session_seen else "SESSION_MISSING"])
        else:
            entry["status"] = PENDING
        return entry, None
    entry["record"] = {"record_id": row["record_id"], "observation_as_of_utc": row["observation_as_of_utc"],
                       "generated_at_utc": row["generated_at_utc"], "report_sha256": row["report_sha256"],
                       "day_status": row["day_status"]}
    try:
        rep = json.loads(row["report_json"])
        intact = (shadow_day.report_hash(rep) == row["report_sha256"] and rep.get("contract") == shadow_day.CONTRACT
                  and rep.get("session_date") == ds and rep.get("day_status") == row["day_status"]
                  and rep.get("observation_as_of_utc") == row["observation_as_of_utc"])
    except (ValueError, ValidationError):
        rep, intact = None, False
    if not intact:
        entry.update(status=UNKNOWN, reasons=["SHADOW_RECORD_TAMPERED"])
        return entry, None
    reasons = []
    if not _anchored(vis, row):
        reasons.append("SHADOW_RECORD_UNANCHORED")
    head = rep["audit"]["head_at_as_of"]
    violation = []
    if head is not None and head not in heads:
        violation.append("AUDIT_HEAD_MISSING")                # evidence the day was based on is gone
    if not (rep["dry_run"] is True and rep["sent"] is False and rep["network"] == "none"):
        violation.append("DRY_RUN_BOUNDARY")
    facts = _day_facts(rep)
    entry["facts"] = facts
    resolved = facts["unresolved_schedules"] == 0 and facts["in_flight"] == 0 and facts["pre_schedule_stories"] == 0
    after_due = row["observation_as_of_utc"] >= iso_utc(due)
    entry["final"] = bool(resolved or after_due)
    if not entry["final"]:
        if not entry["due"]:
            entry.update(status=PENDING, reasons=sorted(reasons + violation))
            return entry, rep
        reasons.append("SHADOW_DAY_PREMATURE")
    elif facts["unresolved_schedules"] > facts["held_by_kill_switch"] or facts["in_flight"]:
        reasons.append("SCHEDULE_UNRESOLVED_AFTER_DUE")
    status = row["day_status"]
    if violation:
        status = VIOLATION
    elif reasons and status == OK:
        status = UNKNOWN
    entry.update(status=status, reasons=sorted(reasons + violation))
    entry["full_chain"] = bool(status == OK and entry["final"] and facts["would_publish"] > 0
                               and facts["human_approval_verified"] == facts["scheduled_stories"])
    return entry, rep


# ------------------------------------------------------------------ cross-day

def cross_day_duplicates(reports: dict[str, dict]) -> dict:
    """Same payload / trace / story appearing under more than one session date (stored records only)."""
    seen: dict[str, dict[str, set]] = {"payload_sha256": {}, "trace_sha256": {}, "story_id": {}}
    for ds, rep in sorted(reports.items()):
        for x in rep["stories"]:
            seen["story_id"].setdefault(x["story_id"], set()).add(ds)
            for s in x["schedules"]:
                seen["payload_sha256"].setdefault(s["payload_sha256"], set()).add(ds)
        for d in rep["dispatches"]:
            if d["trace_sha256"]:
                seen["trace_sha256"].setdefault(d["trace_sha256"], set()).add(ds)
    return {k: sorted([h, sorted(v)] for h, v in m.items() if len(v) > 1) for k, m in seen.items()}


def _worst(statuses) -> str:
    s = set(statuses)
    return VIOLATION if VIOLATION in s else UNKNOWN if UNKNOWN in s else OK


# ------------------------------------------------------------------ build / record

def build(ctx: Ctx, date_from: str, date_to: str, observation_as_of: datetime) -> dict:
    """Deterministic point-in-time period report (the hashed body). Read-only."""
    t = shadow_day._require_past(ctx, observation_as_of)
    days = _range(date_from, date_to)
    target = acceptance_days(ctx.cfg)
    cal = load_calendar(ctx.cfg.get("tse_calendar_path"))
    for d in (days[0], days[-1]):
        cal.status(d)                                       # fail-closed if the calendar does not cover the range
    rule = due_rule(ctx.cfg)
    tl = shadow_day._timeline(ctx, t, iso_utc(ctx.clock.now()))
    vis = tl["visible"]
    heads = {r["hash"] for r in vis}
    entries, reports = [], {}
    for d in days:
        e, rep = _date_entry(ctx, cal, d, t, vis, heads, rule)
        entries.append(e)
        if rep is not None and e["final"]:
            reports[e["date"]] = rep
    dups = cross_day_duplicates(reports)
    evidence = []
    if tl["non_monotonic"]:
        evidence.append("AUDIT_TIME_NON_MONOTONIC")
    if tl["future"]:
        evidence.append("FUTURE_EVIDENCE")
    chain = audit.verify_chain(ctx.conn)
    counted = [e for e in entries if e["status"] in (OK, UNKNOWN, VIOLATION)]
    recorded = [e["record"]["day_status"] for e in counted if e["record"]]
    rec_reasons = {"SHADOW_RECORD_TAMPERED", "SHADOW_RECORD_UNANCHORED", "AUDIT_HEAD_MISSING"}
    checks = {
        "calendar_coverage": UNKNOWN if any(set(e["reasons"]) & {"SESSION_MISSING", "SHADOW_DAY_MISSING",
                                                                 "SHADOW_DAY_PREMATURE", "SESSION_ON_CLOSED_DAY"}
                                            for e in entries) else VERIFIED,
        "day_records": NA if not recorded else {OK: VERIFIED}.get(_worst(recorded), _worst(recorded)),
        "record_integrity": VIOLATION if any("AUDIT_HEAD_MISSING" in e["reasons"] for e in entries) else
        UNKNOWN if any(set(e["reasons"]) & rec_reasons for e in entries) else VERIFIED,
        "resolution": UNKNOWN if any("SCHEDULE_UNRESOLVED_AFTER_DUE" in e["reasons"] for e in entries) else VERIFIED,
        "cross_day_duplicates": VIOLATION if any(dups.values()) else VERIFIED,
        "dry_run_boundary": VIOLATION if any("DRY_RUN_BOUNDARY" in e["reasons"] for e in entries) else VERIFIED,
        "audit_chain": VERIFIED if chain["ok"] else VIOLATION,
        "audit_time": UNKNOWN if evidence else VERIFIED,
    }
    vals = set(checks.values()) | {e["status"] for e in counted}
    period_status = VIOLATION if VIOLATION in vals else UNKNOWN if UNKNOWN in vals else OK
    trading = [e for e in entries if e["trading"]]
    due_days = [e for e in trading if e["due"]]
    full = sum(e["full_chain"] for e in entries)
    tot = lambda k: sum((e["facts"] or {}).get(k, 0) for e in entries if e["final"])
    return {
        "contract": CONTRACT, "input_contract": shadow_day.CONTRACT,
        "date_from": date_from, "date_to": date_to, "observation_as_of_utc": t,
        "dry_run": True, "network": "none", "sent": False,
        "calendar": {"tse_calendar_sha256": cal.sha256,
                     "trading_days": len(trading), "closed_days": len(entries) - len(trading)},
        "due_rule": rule, "days": entries, "cross_day_duplicates": dups,
        "audit": {"chain_ok": chain["ok"], "head_at_as_of": tl["head_at_as_of"],
                  "non_monotonic_seqs": tl["non_monotonic"], "future_seqs": tl["future"]},
        "checks": checks, "period_status": period_status,
        "totals": {
            "trading_days_due": len(due_days), "trading_days_pending": sum(e["status"] == PENDING for e in trading),
            **{f"days_{s.lower()}": sum(e["status"] == s for e in entries) for s in (OK, UNKNOWN, VIOLATION)},
            "full_chain_days": full,
            **{k: tot(k) for k in ("stories", "would_publish", "blocked", "missed", "unknown", "held_by_kill_switch",
                                   "proposal_differs", "proposal_available", "compliance_violations",
                                   "ja_suspected_midword_breaks_heuristic")},
            "days_kill_switch_paused": sum(bool(e["facts"] and e["facts"]["kill_switch_paused"]) for e in entries),
        },
        "acceptance": {"target_trading_days": target, "full_chain_days": full,
                       "met": bool(period_status == OK and full >= target)},
    }


def record(ctx: Ctx, date_from: str, date_to: str, observation_as_of: datetime) -> dict:
    """Append-only. Identity = (date_from, date_to, observation_as_of, contract); an identical re-run
    is a no-op, a different result for the same identity is refused (SHADOW_PERIOD_CONFLICT)."""
    rep = build(ctx, date_from, date_to, observation_as_of)
    sha = report_hash(rep)
    gen = iso_utc(ctx.clock.now())
    key = (date_from, date_to, rep["observation_as_of_utc"], CONTRACT)
    with transaction(ctx.conn):
        prev = ctx.conn.execute("SELECT record_id, report_sha256, generated_at_utc FROM shadow_periods WHERE"
                                " date_from=? AND date_to=? AND observation_as_of_utc=? AND contract=?", key).fetchone()
        if prev:
            if prev["report_sha256"] != sha:
                raise ValidationError("a shadow period record for this range and observation_as_of already exists"
                                      " with different content", code="SHADOW_PERIOD_CONFLICT",
                                      details={"record_id": prev["record_id"], "stored": prev["report_sha256"],
                                               "new": sha})
            return {"record_id": prev["record_id"], "report_sha256": sha, "generated_at_utc": prev["generated_at_utc"],
                    "noop": True, "report": rep}
        cur = ctx.conn.execute(
            "INSERT INTO shadow_periods(date_from, date_to, observation_as_of_utc, contract, generated_at_utc,"
            " report_json, report_sha256, period_status) VALUES (?,?,?,?,?,?,?,?)",
            (*key, gen, canonical_json(rep), sha, rep["period_status"]))
        audit.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="shadow_period",
                     entity_id=f"{date_from}..{date_to}", action="shadow_period_recorded", to_state="RECORDED",
                     detail={"record_id": cur.lastrowid, "observation_as_of_utc": rep["observation_as_of_utc"],
                             "report_sha256": sha, "period_status": rep["period_status"],
                             "acceptance_met": rep["acceptance"]["met"]})
    return {"record_id": cur.lastrowid, "report_sha256": sha, "generated_at_utc": gen, "noop": False, "report": rep}


def load(ctx: Ctx, record_id: int) -> dict:
    """A stored period record, hash-verified (never recomputed)."""
    row = ctx.conn.execute("SELECT * FROM shadow_periods WHERE record_id=?", (record_id,)).fetchone()
    if row is None:
        raise ValidationError(f"unknown shadow period record {record_id}", code="SHADOW_PERIOD_NOT_FOUND")
    rep = json.loads(row["report_json"])
    if report_hash(rep) != row["report_sha256"]:
        raise ValidationError(f"shadow period record {record_id} hash mismatch", code="SHADOW_RECORD_TAMPERED")
    return {"record_id": row["record_id"], "generated_at_utc": row["generated_at_utc"],
            "report_sha256": row["report_sha256"], "report": rep}
