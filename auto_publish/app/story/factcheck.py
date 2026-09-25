"""FACT_CHECK: every fact a story cites is re-read from the locked evidence copy
(hash re-verified) and must still equal the value recorded at VALIDATE."""
from __future__ import annotations

import json
import math

from ..context import Ctx
from ..errors import EvidenceError, FactCheckError
from ..evidence import store as ev
from ..hashing import canonical_json


def plan_fact_ids(plan: dict) -> list[str]:
    ids = list(plan["hook"]["fact_ids"])
    for b in plan["bullets"]:
        ids.extend(b["fact_ids"])
    return sorted(set(ids))


def source_refs(ctx: Ctx, story: dict) -> list[dict]:
    """Verified source references for a story (raises fail-closed on any problem)."""
    plan = json.loads(story["plan_json"])
    refs = []
    for fid in plan_fact_ids(plan):
        row = ctx.conn.execute(
            "SELECT f.*, e.rel_path, e.sha256, e.store_path, e.session_date AS ev_session, e.evidence_id AS eid"
            " FROM facts f JOIN evidence e ON e.evidence_id = f.evidence_id WHERE f.fact_id = ?",
            (fid,),
        ).fetchone()
        if row is None:
            raise FactCheckError(f"{story['story_id']}: cited fact {fid} has no evidence", code="MISSING_SOURCE_REFS")
        if row["session_date"] != story["session_date"] or row["ev_session"] != story["session_date"]:
            raise FactCheckError(f"fact {fid} belongs to another session", code="DATE_MISMATCH")
        if row["basis"] == "real":
            raise FactCheckError(f"fact {fid} is real-account data; not publishable in R1", code="REAL_ACCOUNT_DATA")
        try:
            doc = ev.load_json(row)  # re-hashes the locked copy
            actual = ev.resolve_pointer(doc, row["pointer"])
        except EvidenceError as exc:
            raise FactCheckError(f"fact {fid}: {exc}", code=exc.code, details=exc.details) from exc
        if canonical_json(actual) != row["value_json"]:
            raise FactCheckError(f"fact {fid} no longer matches its evidence", code="FACT_MISMATCH")
        refs.append({
            "fact_id": fid,
            "kind": row["kind"],
            "basis": row["basis"],
            "session_date": row["session_date"],
            "rel_path": row["rel_path"],
            "sha256": row["sha256"],
            "pointer": row["pointer"],
            "value": actual,
        })
    return refs


def check_story(ctx: Ctx, story: dict) -> list[dict]:
    refs = source_refs(ctx, story)
    by_id = {r["fact_id"]: r for r in refs}
    plan = json.loads(story["plan_json"])
    if len(plan["bullets"]) < int(ctx.cfg["min_facts_per_story"]):
        raise FactCheckError("story has fewer evidence-backed bullets than required", code="INSUFFICIENT_EVIDENCE")
    for b in plan["bullets"]:
        vals = [by_id[f]["value"] for f in b["fact_ids"]]
        if b["type"] == "volume":
            v = vals[0].get("volume_ratio")
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise FactCheckError("volume bullet lacks a numeric volume_ratio", code="FACT_MISMATCH")
        if b["type"] == "paper" and by_id[b["fact_ids"][0]]["basis"] != "paper":
            raise FactCheckError("paper bullet must cite a paper-basis fact", code="BASIS_MISMATCH")
    return refs
