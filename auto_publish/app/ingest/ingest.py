"""INGEST and VALIDATE stages (session level).

Input contract (read-only export dropped by the owner after the close):

    content_drop/YYYY-MM-DD/
        daily_summary.json          (required, schema auto_publish.daily_summary.v1)
        paper_trade_history.json    (optional; entries for other dates are ignored)
        *.png / *.jpg / other       (optional attachments; hashed as evidence only)

The publisher never reaches back into AI Cockpit: the directory path is the
only coupling.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import audit
from ..clock import iso_utc, parse_aware
from ..context import Ctx
from ..db import transaction
from ..errors import EvidenceError, FailClosedError, ValidationError
from ..evidence import store as ev
from ..hashing import canonical_json, sha256_file, sha256_text
from ..logs import log
from ..state_machine import SessionState, transition_session

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_FILE_BYTES = 200 * 1024 * 1024
SUMMARY_FILE = "daily_summary.json"
PAPER_FILE = "paper_trade_history.json"
SUMMARY_SCHEMA = "auto_publish.daily_summary.v1"
ALLOWED_SOURCES = {"ai_cockpit_export", "manual", "TEST_FIXTURE"}
RADAR_EVENTS = {"volume_spike", "vwap_reclaim", "or15_breakout", "gap_fill", "block_trade_print"}


def _kind(rel: str) -> str:
    if rel == SUMMARY_FILE:
        return "daily_summary"
    if rel == PAPER_FILE:
        return "paper_trade_history"
    return "attachment"


def _scan(input_dir: Path) -> list[tuple[str, Path]]:
    files = []
    for p in sorted(input_dir.rglob("*")):
        rel = p.relative_to(input_dir).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if p.is_symlink():
            raise EvidenceError(f"symlinks are not accepted as evidence: {rel}", code="EVIDENCE_SYMLINK")
        if p.is_dir():
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            raise EvidenceError(f"{rel} exceeds {MAX_FILE_BYTES} bytes", code="EVIDENCE_TOO_LARGE")
        files.append((rel, p))
    return files


def ingest(ctx: Ctx, input_dir: str | Path, *, session_date: str | None = None) -> dict:
    """Hash + lock every input file. Idempotent for identical input; refuses changed input."""
    input_dir = Path(input_dir).resolve()
    if not input_dir.is_dir():
        raise ValidationError(f"input directory not found: {input_dir}", code="INPUT_MISSING")
    if session_date is None:
        if not DATE_RE.match(input_dir.name):
            raise ValidationError("input directory must be named YYYY-MM-DD or --date must be given",
                                  code="SESSION_DATE_UNKNOWN")
        session_date = input_dir.name
    if not DATE_RE.match(session_date):
        raise ValidationError(f"bad session date {session_date!r}")
    if DATE_RE.match(input_dir.name) and input_dir.name != session_date:
        raise ValidationError(f"directory {input_dir.name} does not match session {session_date}",
                              code="DATE_MISMATCH")

    files = _scan(input_dir)
    if not any(rel == SUMMARY_FILE for rel, _ in files):
        raise EvidenceError(f"required {SUMMARY_FILE} missing in {input_dir}", code="EVIDENCE_MISSING")
    hashed = []
    for rel, p in files:
        st = p.stat()
        hashed.append({
            "rel_path": rel, "path": p, "sha256": sha256_file(p), "size_bytes": st.st_size,
            "source_mtime_utc": iso_utc(datetime.fromtimestamp(st.st_mtime).astimezone()),
            "kind": _kind(rel),
        })

    existing = ctx.conn.execute("SELECT * FROM sessions WHERE session_date = ?", (session_date,)).fetchone()
    if existing is not None:
        locked = {r["rel_path"]: r["sha256"] for r in ctx.conn.execute(
            "SELECT rel_path, sha256 FROM evidence WHERE session_date = ?", (session_date,))}
        incoming = {h["rel_path"]: h["sha256"] for h in hashed}
        if locked == incoming:
            log("ingest.idempotent_noop", session_date=session_date)
            return {"session_date": session_date, "state": existing["state"], "files": len(locked),
                    "manifest_sha256": existing["manifest_sha256"], "noop": True}
        changed = sorted(k for k in set(locked) | set(incoming) if locked.get(k) != incoming.get(k))
        raise EvidenceError(
            f"session {session_date} is already locked and the input differs; refusing to overwrite evidence",
            code="EVIDENCE_CHANGED_AFTER_LOCK", details={"changed": changed},
        )

    now = iso_utc(ctx.clock.now())
    with transaction(ctx.conn):
        ctx.conn.execute(
            "INSERT INTO sessions(session_date, input_dir, state, created_at, updated_at) VALUES (?,?,?,?,?)",
            (session_date, str(input_dir), SessionState.INGESTED.value, now, now),
        )
        for h in hashed:
            dest = ev.store_copy(h["path"], ctx.paths.evidence_store, h["sha256"])
            ctx.conn.execute(
                "INSERT INTO evidence(session_date, rel_path, sha256, size_bytes, source_mtime_utc, kind, store_path, ingested_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (session_date, h["rel_path"], h["sha256"], h["size_bytes"], h["source_mtime_utc"], h["kind"], str(dest), now),
            )
        m, msha = ev.manifest(ctx.conn, session_date)
        ctx.conn.execute("UPDATE sessions SET manifest_sha256 = ? WHERE session_date = ?", (msha, session_date))
        audit.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="session", entity_id=session_date,
                     action="ingest", to_state=SessionState.INGESTED.value,
                     detail={"manifest_sha256": msha, "files": m["files"]})
    log("ingest.locked", session_date=session_date, files=len(hashed), manifest_sha256=msha)
    return {"session_date": session_date, "state": SessionState.INGESTED.value, "files": len(hashed),
            "manifest_sha256": msha, "noop": False}


# ---------------------------------------------------------------- VALIDATE


def _finite_number(v, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValidationError(f"{where} must be a finite number", code="SCHEMA_INVALID")
    return float(v)


def _fact_id(session_date: str, rel_path: str, pointer: str) -> str:
    return "f_" + sha256_text(f"{session_date}|{rel_path}|{pointer}")[:16]


def validate(ctx: Ctx, session_date: str) -> dict:
    row = ctx.conn.execute("SELECT * FROM sessions WHERE session_date = ?", (session_date,)).fetchone()
    if row is None:
        raise ValidationError(f"session {session_date} not ingested", code="SESSION_MISSING")
    if row["state"] == SessionState.VALIDATED.value:
        ev.verify_session(ctx.conn, session_date)  # still re-check the lock
        return {"session_date": session_date, "state": row["state"], "noop": True}
    if row["state"] != SessionState.INGESTED.value:
        raise ValidationError(f"session {session_date} is {row['state']}", code="SESSION_NOT_VALIDATABLE")
    try:
        facts, fixture = _validate_and_extract(ctx, session_date)
    except FailClosedError as exc:
        transition_session(ctx.conn, ctx.clock, session_date, SessionState.INGESTED, SessionState.FAILED,
                           actor=ctx.actor, reason=exc.code,
                           extra_updates={"last_error": canonical_json(exc.to_dict())}, detail=exc.to_dict())
        log("validate.failed", session_date=session_date, **exc.to_dict())
        raise
    with transaction(ctx.conn):
        for f in facts:
            ctx.conn.execute(
                "INSERT INTO facts(fact_id, session_date, evidence_id, pointer, kind, topic, basis, value_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f["fact_id"], session_date, f["evidence_id"], f["pointer"], f["kind"], f["topic"], f["basis"],
                 canonical_json(f["value"])),
            )
        transition_session(ctx.conn, ctx.clock, session_date, SessionState.INGESTED, SessionState.VALIDATED,
                           actor=ctx.actor, reason="validated",
                           extra_updates={"fixture": int(fixture)}, detail={"facts": len(facts)})
    log("validate.ok", session_date=session_date, facts=len(facts), fixture=fixture)
    return {"session_date": session_date, "state": SessionState.VALIDATED.value, "facts": len(facts),
            "fixture": fixture, "noop": False}


def _validate_and_extract(ctx: Ctx, session_date: str) -> tuple[list[dict], bool]:
    ev.verify_session(ctx.conn, session_date)
    tz = ZoneInfo(ctx.cfg["market_timezone"])
    sess = date.fromisoformat(session_date)
    if sess.weekday() >= 5:
        raise ValidationError(f"{session_date} is a weekend; not a trading session", code="NOT_TRADING_DAY")

    rows = {r["rel_path"]: r for r in ctx.conn.execute(
        "SELECT * FROM evidence WHERE session_date = ?", (session_date,))}
    summary_row = rows.get(SUMMARY_FILE)
    if summary_row is None:
        raise EvidenceError("daily_summary.json missing from evidence", code="EVIDENCE_MISSING")
    doc = ev.load_json(summary_row)
    if not isinstance(doc, dict) or doc.get("schema") != SUMMARY_SCHEMA:
        raise ValidationError(f"daily_summary.json must declare schema {SUMMARY_SCHEMA}", code="SCHEMA_INVALID")

    # --- date / freshness (fail-closed on mismatch or stale evidence)
    if doc.get("session_date") != session_date:
        raise ValidationError(
            f"daily_summary session_date {doc.get('session_date')!r} != {session_date}", code="DATE_MISMATCH")
    try:
        generated = parse_aware(str(doc.get("generated_at", "")))
    except ValueError as exc:
        raise ValidationError(f"generated_at invalid: {exc}", code="SCHEMA_INVALID") from exc
    hh, mm = map(int, ctx.cfg["market_close_jst"].split(":"))
    close_at = datetime.combine(sess, time(hh, mm), tzinfo=tz)
    stale_after = close_at + timedelta(hours=float(ctx.cfg["max_evidence_age_hours"]))
    if generated < close_at:
        raise ValidationError(f"summary generated {generated.isoformat()} before market close {close_at.isoformat()}",
                              code="EVIDENCE_PREMATURE")
    if generated > ctx.clock.now():
        raise ValidationError(f"summary generated_at {generated.isoformat()} is in the future", code="EVIDENCE_FUTURE")
    if ctx.clock.now() > stale_after:
        raise ValidationError(
            f"evidence for {session_date} is stale (now {ctx.clock.now().isoformat()} > {stale_after.isoformat()})",
            code="EVIDENCE_STALE")

    source = doc.get("source")
    if source not in ALLOWED_SOURCES:
        raise ValidationError(f"unknown source {source!r}", code="SCHEMA_INVALID")
    fixture = source == "TEST_FIXTURE"
    data_class = doc.get("data_class", "fixture" if fixture else None)
    if (fixture and data_class != "fixture") or (not fixture and data_class != "real"):
        raise ValidationError(f"data_class {data_class!r} inconsistent with source {source!r}", code="SCHEMA_INVALID")

    facts: list[dict] = []
    movers = doc.get("movers")
    if not isinstance(movers, list) or not movers:
        raise ValidationError("daily_summary.movers must be a non-empty list", code="SCHEMA_INVALID")
    tickers = set()
    for i, m in enumerate(movers):
        where = f"movers[{i}]"
        if not isinstance(m, dict):
            raise ValidationError(f"{where} must be an object", code="SCHEMA_INVALID")
        for key in ("ticker", "name_en", "name_ja"):
            if not isinstance(m.get(key), str) or not m[key].strip():
                raise ValidationError(f"{where}.{key} required", code="SCHEMA_INVALID")
        _finite_number(m.get("close"), f"{where}.close")
        _finite_number(m.get("change_pct"), f"{where}.change_pct")
        if "volume_ratio" in m:
            if _finite_number(m["volume_ratio"], f"{where}.volume_ratio") < 0:
                raise ValidationError(f"{where}.volume_ratio negative", code="SCHEMA_INVALID")
        if m["ticker"] in tickers:
            raise ValidationError(f"duplicate mover {m['ticker']}", code="SCHEMA_INVALID")
        tickers.add(m["ticker"])
        ptr = f"/movers/{i}"
        facts.append({"fact_id": _fact_id(session_date, SUMMARY_FILE, ptr), "evidence_id": summary_row["evidence_id"],
                      "pointer": ptr, "kind": "mover", "topic": m["ticker"], "basis": "observed", "value": m})

    for j, e in enumerate(doc.get("radar_events", []) or []):
        where = f"radar_events[{j}]"
        if not isinstance(e, dict) or e.get("ticker") not in tickers:
            raise ValidationError(f"{where} must reference a listed mover", code="SCHEMA_INVALID")
        if e.get("event") not in RADAR_EVENTS:
            raise ValidationError(f"{where}.event {e.get('event')!r} unsupported", code="SCHEMA_INVALID")
        if not re.match(r"^\d{2}:\d{2}$", str(e.get("time_jst", ""))):
            raise ValidationError(f"{where}.time_jst must be HH:MM", code="SCHEMA_INVALID")
        ptr = f"/radar_events/{j}"
        facts.append({"fact_id": _fact_id(session_date, SUMMARY_FILE, ptr), "evidence_id": summary_row["evidence_id"],
                      "pointer": ptr, "kind": "radar_event", "topic": e["ticker"], "basis": "observed", "value": e})

    paper_row = rows.get(PAPER_FILE)
    if paper_row is not None:
        trades = ev.load_json(paper_row)
        if not isinstance(trades, list):
            raise ValidationError("paper_trade_history.json must be a list", code="SCHEMA_INVALID")
        for k, t in enumerate(trades):
            if not isinstance(t, dict) or t.get("date") != session_date:
                continue  # other sessions are not evidence for this one
            if t.get("ticker") not in tickers or not t.get("triggered"):
                continue
            _finite_number(t.get("entry"), f"paper[{k}].entry")
            if t.get("basis", "paper") != "paper":
                raise ValidationError(f"paper[{k}] basis must be 'paper'", code="SCHEMA_INVALID")
            if "closed" in t and not isinstance(t["closed"], bool):
                raise ValidationError(f"paper[{k}].closed must be boolean", code="SCHEMA_INVALID")
            if t.get("closed") is True and t.get("r") is None:
                raise ValidationError(f"paper[{k}] closed trade without r", code="SCHEMA_INVALID")
            if t.get("r") is not None:
                _finite_number(t["r"], f"paper[{k}].r")
            ptr = f"/{k}"
            facts.append({"fact_id": _fact_id(session_date, PAPER_FILE, ptr), "evidence_id": paper_row["evidence_id"],
                          "pointer": ptr, "kind": "paper_trade", "topic": t["ticker"], "basis": "paper", "value": t})
    return facts, fixture
