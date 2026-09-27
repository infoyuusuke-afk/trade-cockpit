"""Shadow day record -- contract ``auto_publish.shadow_day.v1`` -- and the multi-day summary.

A shadow day record re-checks one trading session's dry-run chain

    slot proposal (as_of before scheduling) -> human approval -> schedule (fixed slot)
    -> WOULD_PUBLISH / BLOCKED / UNKNOWN / MISSED -> shadow day record

READ-ONLY and POINT-IN-TIME: it describes the session as it stood at
``observation_as_of`` (T) using only evidence stamped at or before T. It changes no
story, schedule, dispatch or proposal; the only write is the record itself plus
its audit row. Nothing is sent; no network is used.

Times
* ``observation_as_of_utc`` (T): part of the record identity and of the hash.
  T must be strictly before the current second (as for slot proposals).
* ``generated_at_utc``: the wall-clock time the record was made. Stored beside the
  record, NEVER inside the hashed body.

Point-in-time reconstruction (what was knowable at T)
* session / story state = the last audit transition stamped <= T
* schedule status      = the last schedule audit event stamped <= T (else SCHEDULED
                         once created <= T; CANCELLED if the story was cancelled by T)
* dispatch status      = its outcome if finished <= T, IN_FLIGHT if claimed <= T but
                         finished later; later claims are invisible
* proposals            = stored (created) <= T; kill switches = control audit <= T
* Evidence that contradicts the timeline (an audit row stamped <= T appended after
  a later-stamped row, a record stamped after generation time, a dispatch finishing
  before it was claimed) is reported as UNKNOWN (FUTURE_EVIDENCE /
  AUDIT_TIME_NON_MONOTONIC / DISPATCH_TIME_INCONSISTENT) -- never corrected.

Verdicts: every check is VERIFIED, VIOLATION (proven problem, e.g. a duplicate),
UNKNOWN (cannot be determined: missing file, trace mismatch, irreproducible
conditions, future evidence) or NOT_APPLICABLE. Recorded statuses (WOULD_PUBLISH,
BLOCKED, ...) are copied as they are and never re-classified. ``day_status`` is
VIOLATION if any check is VIOLATION, else UNKNOWN if any is UNKNOWN, else OK.

Canonical hash (``report_hash``) -- versioned for this contract only; the existing
canonical/hash helpers are reused unchanged:
* bytes = b"auto_publish.shadow_day.v1\\n" + UTF-8 of canonical_json(report)
  (keys sorted, separators "," ":", non-ASCII kept, NaN/Infinity rejected)
* timestamps: UTC, second precision, "YYYY-MM-DDTHH:MM:SSZ" (keys ending ``_utc``)
* floats are forbidden anywhere in the body (counts, widths, lengths are integers)
* null: every declared key is always present; "no value" is JSON null
* lists: stories by story_id, schedules by platform, dispatches by dispatch_id,
  proposals by platform, problems in that same order, duplicate groups sorted
The Japanese subtitle metric is a HEURISTIC observation (``used_for_safety: false``)
and never influences a verdict.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta

from .. import audit
from ..clock import JST, iso_utc, parse_aware
from ..compliance import rules as compliance
from ..context import Ctx
from ..db import transaction
from ..errors import AutoPublishError, ValidationError
from ..hashing import canonical_json, sha256_bytes, sha256_file, sha256_json
from ..publishers.contract import x_weighted_length
from ..text.wrap import display_width

CONTRACT = "auto_publish.shadow_day.v1"
SUMMARY_CONTRACT = "auto_publish.shadow_summary.v1"
HASH_DOMAIN = (CONTRACT + "\n").encode("utf-8")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DISPATCH_EVENTS = ("dispatch_skipped", "dispatch_aborted", "dispatch_blocked", "dispatch_unknown",
                   "dispatch_missed", "dispatch_duplicate_refused")
VERIFIED, VIOLATION, UNKNOWN, NA = "VERIFIED", "VIOLATION", "UNKNOWN", "NOT_APPLICABLE"
CATEGORIES = (
    ("future", {"EVIDENCE_FUTURE", "FUTURE_EVIDENCE", "AS_OF_NOT_IN_PAST", "AUDIT_TIME_NON_MONOTONIC",
                "DISPATCH_TIME_INCONSISTENT"}),
    ("unknown", {"DISPATCH_OUTCOME_UNKNOWN", "DISPATCH_LEASE_EXPIRED", "UNKNOWN_RESULT",
                 "CONDITIONS_NOT_REPRODUCIBLE"}),
    ("stale", {"EVIDENCE_STALE", "SCHEDULE_WINDOW_MISSED", "EVIDENCE_PREMATURE"}),
)


def category(code: str | None) -> str:
    for name, codes in CATEGORIES:
        if code in codes:
            return name
    if code and (code.endswith("_MISSING") or code in {"INPUT_MISSING", "INSUFFICIENT_EVIDENCE"}):
        return "missing"
    if code and (code.endswith(("_TAMPERED", "_MISMATCH", "_CHANGED")) or code == "AUDIT_CHAIN_BROKEN"):
        return "integrity"
    return "other"


# ------------------------------------------------------------------ canonical hash (contract-local)

def _validate(obj, path="$") -> None:
    if isinstance(obj, float):
        raise ValidationError(f"float at {path} is not allowed in {CONTRACT}", code="SHADOW_CANONICAL_INVALID")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValidationError(f"non-string key at {path}", code="SHADOW_CANONICAL_INVALID")
            if k.endswith("_utc") and v is not None and not UTC_RE.match(str(v)):
                raise ValidationError(f"{path}.{k} is not a normalised UTC timestamp", code="SHADOW_CANONICAL_INVALID")
            _validate(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _validate(v, f"{path}[{i}]")


def canonical_bytes(report: dict) -> bytes:
    _validate(report)
    return HASH_DOMAIN + canonical_json(report).encode("utf-8")


def report_hash(report: dict) -> str:
    return sha256_bytes(canonical_bytes(report))


# ------------------------------------------------------------------ helpers

def _script(ch: str) -> str | None:
    if ch == "ー" or "゠" <= ch <= "ヿ":
        return "katakana"
    if "぀" <= ch <= "ゟ":
        return "hiragana"
    if unicodedata.name(ch, "").startswith("CJK UNIFIED IDEOGRAPH"):
        return "kanji"
    return None


def subtitle_quality(srt_text: str) -> dict:
    """HEURISTIC, observation only: a line break inside a cue is a *suspected mid-word break*
    when the characters on both sides are of the same script (katakana, kanji or hiragana)."""
    cues = [c for c in srt_text.strip().split("\n\n") if c.strip()]
    lines, max_w, suspects = 0, 0, []
    for c in cues:
        text = c.strip().splitlines()[2:]
        lines += len(text)
        max_w = max([max_w] + [display_width(t) for t in text])
        for a, b in zip(text, text[1:]):
            if a and b and _script(a[-1]) and _script(a[-1]) == _script(b[0]):
                suspects.append(f"{a[-3:]}|{b[:3]}")
    return {"heuristic": True, "used_for_safety": False, "cues": len(cues), "lines": lines,
            "max_display_width": max_w, "suspected_midword_breaks": len(suspects), "examples": suspects[:10]}


def _require_past(ctx: Ctx, as_of: datetime) -> str:
    t, now = iso_utc(as_of), iso_utc(ctx.clock.now())
    if t >= now:
        raise ValidationError(f"observation_as_of {t} is not in the past (now {now})", code="AS_OF_NOT_IN_PAST")
    return t


def default_as_of(ctx: Ctx) -> datetime:
    return ctx.clock.now().replace(microsecond=0) - timedelta(seconds=1)


def _timeline(ctx: Ctx, t: str, now_s: str) -> dict:
    """Audit rows visible at t, plus timeline anomalies (never corrected)."""
    rows = [dict(r) for r in ctx.conn.execute("SELECT * FROM audit_log ORDER BY seq")]
    visible, non_mono, future, running = [], [], [], ""
    for r in rows:
        if r["ts_utc"] <= t:
            if r["ts_utc"] < running:
                non_mono.append(r["seq"])
            visible.append(r)
        if r["ts_utc"] > now_s:
            future.append(r["seq"])
        running = max(running, r["ts_utc"])
    return {"visible": visible, "non_monotonic": non_mono, "future": future,
            "head_at_as_of": visible[-1]["hash"] if visible else None}


def _last(visible: list[dict], entity_type: str, entity_id: str, *, with_state=True) -> dict | None:
    for r in reversed(visible):
        if r["entity_type"] == entity_type and r["entity_id"] == entity_id and (r["to_state"] or not with_state):
            return r
    return None


def _approval_at(visible: list[dict], story: dict) -> dict:
    """Same rule as pipeline.approval_evidence, restricted to audit rows stamped <= T."""
    rows = [r for r in visible if r["entity_type"] == "story" and r["entity_id"] == story["story_id"]
            and r["to_state"] == "APPROVED"]
    human = [r for r in rows if r["from_state"] == "AWAITING_APPROVAL"]
    if not human:
        return {"status": UNKNOWN, "reason": "APPROVAL_EVIDENCE_MISSING"}
    h = human[-1]
    d = json.loads(h["detail_json"])
    if d.get("approved_content_sha256") != story["approved_content_sha256"] or h["actor"] != story["approved_by"]:
        return {"status": UNKNOWN, "reason": "APPROVAL_AUDIT_MISMATCH"}
    for r in rows:
        if r["seq"] > h["seq"]:
            rd = json.loads(r["detail_json"])
            if r["from_state"] != "FAILED" or rd.get("approved_content_sha256") != d["approved_content_sha256"] \
                    or rd.get("inherited_from_audit_hash") != h["hash"]:
                return {"status": UNKNOWN, "reason": "APPROVAL_AUDIT_MISMATCH"}
    return {"status": VERIFIED, "reason": None, "approval_audit_hash": h["hash"]}


def _trace_check(ctx: Ctx, d: dict) -> str | None:
    """None when the WOULD_PUBLISH trace still matches the files; else the UNKNOWN reason."""
    trace = json.loads(d["trace_json"]) if d["trace_json"] else None
    if trace is None or sha256_json(trace) != d["trace_sha256"]:
        return "TRACE_HASH_MISMATCH"
    arts = {r["name"]: r["rel_path"] for r in ctx.conn.execute(
        "SELECT name, rel_path FROM artifacts WHERE story_id=?", (d["story_id"],))}
    for name, sha in sorted(trace["artifacts"].items()):
        p = ctx.paths.artifacts / arts[name] if name in arts else None
        if p is None or not p.is_file():
            return "ARTIFACT_MISSING"
        if sha256_file(p) != sha:
            return "ARTIFACT_CHANGED"
    pp = ctx.paths.artifacts / trace["payload"]["path"]
    if not pp.is_file():
        return "PAYLOAD_MISSING"
    if sha256_file(pp) != trace["payload"]["sha256"]:
        return "PAYLOAD_CHANGED"
    return None


def _content(story: dict, sdir) -> dict | None:
    if not sdir.is_dir():
        return None
    posts = [json.loads((sdir / f).read_text(encoding="utf-8")) for f in ("post_en.json", "post_ja.json")
             if (sdir / f).is_file()]
    margins = {}
    for name, limit, fn in (("tiktok", 2200, lambda r: len(r["post_info"]["title"])),
                            ("x", 280, lambda r: x_weighted_length(r["text"])),
                            ("youtube_shorts", 100, lambda r: len(r["snippet"]["title"]))):
        p = sdir / "dry_run" / f"{name}.json"
        margins[name] = None
        if p.is_file():
            used = fn(json.loads(p.read_text(encoding="utf-8"))["request"])
            margins[name] = {"used": used, "limit": limit, "margin": limit - used}
    ja = sdir / "captions_ja-JP.srt"
    return {"compliance_violations": sum(len(compliance.check_post(p, story["session_date"])) for p in posts),
            "posts_checked": len(posts), "length_margins": margins,
            "ja_subtitles": subtitle_quality(ja.read_text(encoding="utf-8")) if ja.is_file() else None}


def _codes(codes: list[str | None]) -> dict:
    by_code, by_cat = {}, {}
    for c in codes:
        if c:
            by_code[c] = by_code.get(c, 0) + 1
            by_cat[category(c)] = by_cat.get(category(c), 0) + 1
    return {"by_code": by_code, "by_category": by_cat}


# ------------------------------------------------------------------ build / record / summary

def build(ctx: Ctx, session_date: str, observation_as_of: datetime) -> dict:
    """Deterministic point-in-time report (the hashed body). Read-only."""
    from .. import pipeline
    from ..metrics.optimizer import ALGORITHM, evaluate
    t = _require_past(ctx, observation_as_of)
    now_s = iso_utc(ctx.clock.now())
    srow = ctx.conn.execute("SELECT * FROM sessions WHERE session_date=?", (session_date,)).fetchone()
    if srow is None:
        raise ValidationError(f"unknown session {session_date}", code="SESSION_NOT_FOUND")
    tl = _timeline(ctx, t, now_s)
    vis = tl["visible"]
    evidence_problems: list[str] = []
    if tl["non_monotonic"]:
        evidence_problems.append("AUDIT_TIME_NON_MONOTONIC")
    if tl["future"]:
        evidence_problems.append("FUTURE_EVIDENCE")

    s_last = _last(vis, "session", session_date)
    s_fail = None
    if s_last and s_last["to_state"] == "FAILED":       # validate() records exc.to_dict() as the detail
        det = json.loads(s_last["detail_json"])
        s_fail = det.get("code") or (det.get("error") or {}).get("code")
    session = {"state_at_as_of": s_last["to_state"] if s_last else None, "fixture": bool(srow["fixture"]),
               "manifest_sha256": srow["manifest_sha256"] if s_last else None, "failed_code": s_fail}

    stories, story_codes = [], []
    all_scheds, visible_dispatches, approval_verdicts = [], [], []
    for st in ctx.conn.execute("SELECT * FROM stories WHERE session_date=? ORDER BY story_id", (session_date,)):
        st = dict(st)
        last = _last(vis, "story", st["story_id"])
        if last is None:
            continue                                        # not yet selected at T
        state = last["to_state"]
        fcode = (json.loads(last["detail_json"]).get("error") or {}).get("code") if state == "FAILED" else None
        story_codes.append(fcode)
        ever_approved = any(r["entity_type"] == "story" and r["entity_id"] == st["story_id"]
                            and r["to_state"] == "APPROVED" for r in vis)
        appr = _approval_at(vis, st) if ever_approved else {"status": NA, "reason": None}
        approval_verdicts.append(appr["status"])
        scheds = []
        for r in ctx.conn.execute("SELECT * FROM schedules WHERE story_id=? AND created_at <= ? ORDER BY platform",
                                  (st["story_id"], t)):
            r = dict(r)
            ev = _last(vis, "schedule", f"{r['story_id']}:{r['platform']}")
            status = ev["to_state"] if ev else ("CANCELLED" if state == "CANCELLED" else "SCHEDULED")
            if status == "SCHEDULED" and state == "CANCELLED":
                status = "CANCELLED"
            prop = ctx.conn.execute(
                "SELECT proposal_id, status, as_of_utc, proposal_json FROM slot_proposals WHERE platform=?"
                " AND created_at_utc <= ? AND as_of_utc < ? ORDER BY as_of_utc DESC, proposal_id DESC LIMIT 1",
                (r["platform"], t, r["created_at"])).fetchone()
            fixed = parse_aware(r["publish_at_utc"]).astimezone(JST)
            fixed_slot = f"{r['wave']}@{fixed.hour:02d}:{fixed.minute:02d}"
            rec = json.loads(prop["proposal_json"]).get("recommended_slot") if prop else None
            scheds.append({"platform": r["platform"], "status_at_as_of": status, "fixed_slot": fixed_slot,
                           "publish_at_utc": r["publish_at_utc"], "payload_sha256": r["payload_sha256"],
                           "proposal_then": None if prop is None else {
                               "proposal_id": prop["proposal_id"], "status": prop["status"],
                               "as_of_utc": prop["as_of_utc"], "recommended_slot": rec},
                           "proposal_differs": bool(rec and rec != fixed_slot)})
            all_scheds.append({"schedule_id": r["schedule_id"], "payload_sha256": r["payload_sha256"]})
        for d in ctx.conn.execute("SELECT * FROM dispatches WHERE story_id=? AND claimed_at <= ? ORDER BY dispatch_id",
                                  (st["story_id"], t)):
            visible_dispatches.append(dict(d))
        stories.append({"story_id": st["story_id"], "topic": st["topic"], "state_at_as_of": state,
                        "failed_code": fcode, "human_approval": appr["status"],
                        "human_approval_reason": appr["reason"], "schedules": scheds,
                        "content": _content(st, pipeline.story_dir(ctx, st))})

    dispatches, disp_codes, counts = [], [], {}
    for d in visible_dispatches:
        finished = d["finished_at"] if d["finished_at"] and d["finished_at"] <= t else None
        status = d["status"] if finished else "IN_FLIGHT"
        err = json.loads(d["error_json"]).get("code") if finished and d["error_json"] else None
        if finished and err is None and status not in ("WOULD_PUBLISH",):
            # outcomes such as MISSED / ABORTED carry their code as the recorded reason of their audit row
            for r in vis:
                if r["action"] in DISPATCH_EVENTS and json.loads(r["detail_json"]).get("dispatch_id") == d["dispatch_id"]:
                    err = json.loads(r["detail_json"]).get("reason")
        disp_codes.append(err)
        verdict, reason = NA, None
        if d["finished_at"] and d["finished_at"] < d["claimed_at"]:
            verdict, reason = UNKNOWN, "DISPATCH_TIME_INCONSISTENT"
        elif not any(r["action"] == "dispatch_claimed" and json.loads(r["detail_json"]).get("dispatch_id")
                     == d["dispatch_id"] for r in vis):
            verdict, reason = UNKNOWN, "DISPATCH_TIME_INCONSISTENT"
        elif status == "WOULD_PUBLISH":
            reason = _trace_check(ctx, d)
            verdict = UNKNOWN if reason else VERIFIED
        counts[status] = counts.get(status, 0) + 1
        dispatches.append({"dispatch_id": d["dispatch_id"], "story_id": d["story_id"], "platform": d["platform"],
                           "status_at_as_of": status, "error_code": err,
                           "trace_sha256": d["trace_sha256"] if status == "WOULD_PUBLISH" else None,
                           "evidence": verdict, "evidence_reason": reason})

    wp = [d for d in visible_dispatches if (d["finished_at"] or "~") <= t and d["status"] == "WOULD_PUBLISH"]
    group = lambda key: sorted([k, n] for k, n in _count(wp, key).items() if n > 1)
    dups = {"idempotency_key": group(lambda d: d["idempotency_key"]),
            "story_platform": group(lambda d: f"{d['story_id']}:{d['platform']}"),
            "dispatch_id": sorted([k, n] for k, n in _count(visible_dispatches, lambda d: str(d["dispatch_id"])).items()
                                  if n > 1),
            "payload_sha256": sorted([k, n] for k, n in _count(all_scheds, lambda s: s["payload_sha256"]).items()
                                     if n > 1)}

    proposals = []
    for platform in sorted(ctx.cfg["platforms"]):
        row = ctx.conn.execute("SELECT * FROM slot_proposals WHERE platform=? AND created_at_utc <= ?"
                               " ORDER BY as_of_utc DESC, proposal_id DESC LIMIT 1", (platform, t)).fetchone()
        if row is None:
            continue
        stored = json.loads(row["proposal_json"])
        entry = {"proposal_id": row["proposal_id"], "platform": platform, "as_of_utc": row["as_of_utc"]}
        if sha256_json(stored) != row["proposal_sha256"]:
            proposals.append({**entry, "verdict": UNKNOWN, "reason": "PROPOSAL_TAMPERED"})
            continue
        if stored.get("algorithm_version") != ALGORITHM:
            proposals.append({**entry, "verdict": UNKNOWN, "reason": "CONDITIONS_NOT_REPRODUCIBLE"})
            continue
        try:
            again = evaluate(ctx, platform, parse_aware(row["as_of_utc"]))
        except AutoPublishError as exc:
            proposals.append({**entry, "verdict": UNKNOWN, "reason": exc.code})
            continue
        if again["input_sha256"] != row["input_sha256"]:
            # data / config / slots differ from the proposal's own conditions: not comparable
            proposals.append({**entry, "verdict": UNKNOWN, "reason": "CONDITIONS_NOT_REPRODUCIBLE"})
        else:
            same = sha256_json(again) == row["proposal_sha256"]
            proposals.append({**entry, "verdict": VERIFIED if same else VIOLATION,
                              "reason": None if same else "PROPOSAL_NONDETERMINISTIC"})

    controls_at = {}
    for r in vis:
        if r["entity_type"] == "control":
            controls_at[r["entity_id"]] = r["to_state"]
    kill = {"paused": controls_at.get("global.paused") == "1",
            "platforms_enabled": {p: (controls_at[f"platform.{p}.enabled"] == "1"
                                      if f"platform.{p}.enabled" in controls_at else bool(pc.get("enabled", False)))
                                  for p, pc in sorted(ctx.cfg["platforms"].items())}}
    ids = {s["story_id"] for s in stories}
    events = {}
    day_start = iso_utc(datetime.fromisoformat(session_date).replace(tzinfo=JST))
    for r in vis:
        if r["entity_type"] == "schedule" and r["entity_id"].split(":")[0] in ids and r["action"] in DISPATCH_EVENTS:
            det = json.loads(r["detail_json"])
            key = f"{r['action']}:{det.get('reason') or (det.get('error') or {}).get('code')}"
            events[key] = events.get(key, 0) + 1
        elif r["action"] == "dispatch_run_blocked" and r["ts_utc"] >= day_start:
            events["dispatch_run_blocked:PAUSE_ALL"] = events.get("dispatch_run_blocked:PAUSE_ALL", 0) + 1

    chain = audit.verify_chain(ctx.conn)
    trace_verdicts = [d["evidence"] for d in dispatches if d["evidence"] != NA]
    comp = [s["content"]["compliance_violations"] for s in stories if s["content"]]

    def worst(vs, empty=NA):
        return VIOLATION if VIOLATION in vs else UNKNOWN if UNKNOWN in vs else (VERIFIED if vs else empty)
    checks = {
        "audit_chain": VERIFIED if chain["ok"] else VIOLATION,
        "audit_time": UNKNOWN if evidence_problems else VERIFIED,
        "trace_integrity": worst(trace_verdicts),
        "duplicates": VIOLATION if any(dups.values()) else VERIFIED,
        "proposal_determinism": worst([p["verdict"] for p in proposals]),
        "human_approval": worst([v for v in approval_verdicts if v != NA]),
        "compliance": (VIOLATION if any(comp) else VERIFIED) if comp else NA,
    }
    day = VIOLATION if VIOLATION in checks.values() else UNKNOWN if UNKNOWN in checks.values() else "OK"
    evidence_codes = evidence_problems + [s["human_approval_reason"] for s in stories] + \
        [d["evidence_reason"] for d in dispatches] + [p.get("reason") for p in proposals]
    return {
        "contract": CONTRACT, "session_date": session_date, "observation_as_of_utc": t,
        "dry_run": True, "network": "none", "sent": False,
        "session": session, "stories": stories, "dispatches": dispatches,
        "dispatch_counts": counts, "duplicates": dups, "proposals": proposals, "kill_switch": kill,
        "dispatch_events": events,
        "fail_closed": {"session": _codes([s_fail]), "stories": _codes(story_codes),
                        "dispatches": _codes(disp_codes), "evidence": _codes(evidence_codes)},
        "audit": {"chain_ok": chain["ok"], "head_at_as_of": tl["head_at_as_of"],
                  "non_monotonic_seqs": tl["non_monotonic"], "future_seqs": tl["future"]},
        "checks": checks, "day_status": day,
        "attention": {k: counts.get(k, 0) for k in ("BLOCKED", "IN_FLIGHT", "MISSED", "UNKNOWN")},
    }


def _count(items, key) -> dict:
    out: dict = {}
    for it in items:
        k = key(it)
        out[k] = out.get(k, 0) + 1
    return out


def record(ctx: Ctx, session_date: str, observation_as_of: datetime) -> dict:
    """Append-only. Identity = (session_date, observation_as_of, contract): identical re-run is a
    no-op; a different result for the same identity is refused (SHADOW_DAY_CONFLICT)."""
    rep = build(ctx, session_date, observation_as_of)
    sha = report_hash(rep)
    gen = iso_utc(ctx.clock.now())
    with transaction(ctx.conn):
        prev = ctx.conn.execute("SELECT record_id, report_sha256, generated_at_utc FROM shadow_days"
                                " WHERE session_date=? AND observation_as_of_utc=? AND contract=?",
                                (session_date, rep["observation_as_of_utc"], CONTRACT)).fetchone()
        if prev:
            if prev["report_sha256"] != sha:
                raise ValidationError("a shadow day record for this session and observation_as_of already exists"
                                      " with different content", code="SHADOW_DAY_CONFLICT",
                                      details={"record_id": prev["record_id"], "stored": prev["report_sha256"],
                                               "new": sha})
            return {"record_id": prev["record_id"], "report_sha256": sha, "generated_at_utc": prev["generated_at_utc"],
                    "noop": True, "report": rep}
        cur = ctx.conn.execute(
            "INSERT INTO shadow_days(session_date, observation_as_of_utc, contract, generated_at_utc, report_json,"
            " report_sha256, day_status) VALUES (?,?,?,?,?,?,?)",
            (session_date, rep["observation_as_of_utc"], CONTRACT, gen, canonical_json(rep), sha, rep["day_status"]))
        audit.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="shadow_day", entity_id=session_date,
                     action="shadow_day_recorded", to_state="RECORDED",
                     detail={"record_id": cur.lastrowid, "observation_as_of_utc": rep["observation_as_of_utc"],
                             "report_sha256": sha, "day_status": rep["day_status"]})
    return {"record_id": cur.lastrowid, "report_sha256": sha, "generated_at_utc": gen, "noop": False, "report": rep}


def summary(ctx: Ctx, date_from: str, date_to: str) -> dict:
    """Aggregate STORED shadow_day.v1 records only (latest observation per session). Never re-evaluates
    the pipeline, so past shadow results cannot be rewritten by the current DB state."""
    days = []
    for r in ctx.conn.execute(
            "SELECT s.* FROM shadow_days s WHERE s.contract=? AND s.session_date BETWEEN ? AND ?"
            " AND s.observation_as_of_utc = (SELECT MAX(observation_as_of_utc) FROM shadow_days t"
            " WHERE t.session_date = s.session_date AND t.contract = s.contract) ORDER BY s.session_date",
            (CONTRACT, date_from, date_to)):
        rep = json.loads(r["report_json"])
        if report_hash(rep) != r["report_sha256"]:
            raise ValidationError(f"shadow day {r['session_date']} record hash mismatch", code="SHADOW_RECORD_TAMPERED")
        subs = [s["content"]["ja_subtitles"]["suspected_midword_breaks"] for s in rep["stories"]
                if s["content"] and s["content"]["ja_subtitles"]]
        days.append({"session_date": r["session_date"], "record_id": r["record_id"],
                     "observation_as_of_utc": r["observation_as_of_utc"], "report_sha256": r["report_sha256"],
                     "day_status": rep["day_status"],
                     "non_ok_checks": sorted(k for k, v in rep["checks"].items() if v not in (VERIFIED, NA)),
                     "stories": len(rep["stories"]),
                     "would_publish": rep["dispatch_counts"].get("WOULD_PUBLISH", 0), **rep["attention"],
                     "proposal_differs": sum(s["proposal_differs"] for x in rep["stories"] for s in x["schedules"]),
                     "ja_suspected_midword_breaks_heuristic": sum(subs)})
    tot = lambda k: sum(d[k] for d in days)
    status = {s: sum(d["day_status"] == s for d in days) for s in ("OK", "UNKNOWN", "VIOLATION")}
    return {"contract": SUMMARY_CONTRACT, "input_contract": CONTRACT, "from": date_from, "to": date_to,
            "days": days,
            "totals": {"days": len(days), **{f"days_{k.lower()}": v for k, v in status.items()},
                       **{k: tot(k) for k in ("stories", "would_publish", "BLOCKED", "IN_FLIGHT", "MISSED", "UNKNOWN",
                                              "proposal_differs", "ja_suspected_midword_breaks_heuristic")}}}
