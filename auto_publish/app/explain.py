"""`explain <story_id>`: why was this story selected, and where does every claim come from?

Local, operator-facing output. It may show INTERNAL radar values (indicator
readings, guard flags, collector labels) -- those are clearly labelled and are
never written into posts, captions, video or dry-run payloads.
"""
from __future__ import annotations

import json

from .context import Ctx
from .errors import ValidationError
from .evidence import store as ev


def _internal_radar(ctx: Ctx, session_date: str) -> dict:
    row = ctx.conn.execute(
        "SELECT * FROM evidence WHERE session_date = ? AND rel_path = 'internal/radar_internal.json'",
        (session_date,)).fetchone()
    if row is None:
        return {}
    doc = ev.load_json(row)  # re-verifies the SHA256 lock
    return {e["event_id"]: e for e in doc.get("events", [])}


def explain(ctx: Ctx, story_id: str) -> dict:
    story = ctx.conn.execute("SELECT * FROM stories WHERE story_id = ?", (story_id,)).fetchone()
    if story is None:
        raise ValidationError(f"unknown story {story_id}", code="STORY_NOT_FOUND")
    plan = json.loads(story["plan_json"])
    session = ctx.conn.execute("SELECT * FROM sessions WHERE session_date = ?", (story["session_date"],)).fetchone()
    sel = ctx.conn.execute(
        "SELECT detail_json FROM audit_log WHERE entity_type='session' AND entity_id=? AND action='story_select'"
        " ORDER BY seq DESC LIMIT 1", (story["session_date"],)).fetchone()
    internal = _internal_radar(ctx, story["session_date"])

    def fact_chain(fid: str) -> dict:
        f = ctx.conn.execute(
            "SELECT f.*, e.rel_path, e.sha256 AS evidence_sha256 FROM facts f JOIN evidence e"
            " ON e.evidence_id = f.evidence_id WHERE f.fact_id = ?", (fid,)).fetchone()
        value = json.loads(f["value_json"])
        chain = {
            "fact_id": fid, "kind": f["kind"], "basis": f["basis"],
            "content_drop": {"file": f["rel_path"], "sha256": f["evidence_sha256"], "pointer": f["pointer"]},
            "original_source": value.get("source_ref") if isinstance(value, dict) else None,
        }
        if f["kind"] == "radar_event" and isinstance(value, dict):
            chain["event_id"] = value.get("event_id")
            chain["public_event"] = {k: value.get(k) for k in ("ticker", "time_jst", "event", "direction",
                                                               "vwap_relation", "basis", "source")}
            rec = internal.get(value.get("event_id"))
            if rec:
                chain["INTERNAL_never_published"] = rec
        return chain

    segments = [{"segment": "hook", "type": "hook", "facts": [fact_chain(f) for f in plan["hook"]["fact_ids"]]}]
    for i, b in enumerate(plan["bullets"], start=1):
        segments.append({"segment": f"b{i}", "type": b["type"], "facts": [fact_chain(f) for f in b["fact_ids"]]})
    return {
        "visibility": "internal (operator explanation; not publishable)",
        "story_id": story_id, "topic": story["topic"], "session_date": story["session_date"],
        "state": story["state"], "data_class": "fixture" if story["fixture"] else "real",
        "why_selected": {"score": story["score"], "breakdown": json.loads(story["score_breakdown_json"]),
                         "session_selection": json.loads(sel["detail_json"]) if sel else None},
        "evidence_manifest_sha256": session["manifest_sha256"],
        "segments": segments,
    }
