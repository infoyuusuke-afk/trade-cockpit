"""STORY_SELECT: score candidate stories from validated facts.

Evidence completeness is weighted above raw magnitude, so a dramatic move with
thin evidence ranks below a smaller move with complete evidence (spec §8).
A candidate needs at least ``min_facts_per_story`` evidence-backed bullets.
"""
from __future__ import annotations

import json

from ..clock import iso_utc
from .. import audit as audit_mod
from ..context import Ctx
from ..db import transaction
from ..errors import ValidationError
from ..hashing import canonical_json, sha256_text
from ..logs import log
from ..state_machine import SessionState, StoryState

WEIGHTS = {
    "magnitude": 0.25,
    "volume_anomaly": 0.15,
    "radar_quality": 0.15,
    "evidence_completeness": 0.35,
    "learning_value": 0.10,
}
REPEAT_PENALTY = 0.30
EVIDENCE_KINDS = ("close", "volume", "radar", "paper")


def _load_facts(ctx: Ctx, session_date: str) -> dict[str, list[dict]]:
    by_topic: dict[str, list[dict]] = {}
    for r in ctx.conn.execute(
        "SELECT fact_id, kind, topic, basis, pointer, value_json FROM facts WHERE session_date = ? ORDER BY fact_id",
        (session_date,),
    ):
        f = dict(r)
        f["value"] = json.loads(f.pop("value_json"))
        by_topic.setdefault(f["topic"], []).append(f)
    return by_topic


def build_candidate(topic: str, facts: list[dict], min_facts: int) -> dict | None:
    movers = [f for f in facts if f["kind"] == "mover"]
    if len(movers) != 1:
        return None
    mover = movers[0]
    mv = mover["value"]
    radar = sorted((f for f in facts if f["kind"] == "radar_event"), key=lambda f: (f["value"]["time_jst"], f["fact_id"]))
    paper = sorted((f for f in facts if f["kind"] == "paper_trade"), key=lambda f: f["fact_id"])

    bullets: list[dict] = [{"type": "close", "fact_ids": [mover["fact_id"]]}]
    if radar:
        bullets.append({"type": "radar", "fact_ids": [radar[0]["fact_id"]]})
    if paper:  # learning value: a labelled paper result beats a second market statistic
        bullets.append({"type": "paper", "fact_ids": [paper[0]["fact_id"]]})
    if "volume_ratio" in mv:
        bullets.append({"type": "volume", "fact_ids": [mover["fact_id"]]})
    for extra in radar[1:]:
        bullets.append({"type": "radar", "fact_ids": [extra["fact_id"]]})

    kinds_present = {b["type"] for b in bullets}
    features = {
        "magnitude": min(abs(float(mv["change_pct"])) / 10.0, 1.0),
        "volume_anomaly": max(0.0, min((float(mv.get("volume_ratio", 1.0)) - 1.0) / 4.0, 1.0)),
        "radar_quality": min(len(radar) / 2.0, 1.0),
        "evidence_completeness": len(kinds_present & set(EVIDENCE_KINDS)) / len(EVIDENCE_KINDS),
        "learning_value": 1.0 if paper else 0.0,
    }
    eligible = len(bullets) >= min_facts
    return {
        "topic": topic,
        "eligible": eligible,
        "reject_reason": None if eligible else f"only {len(bullets)} evidence-backed bullets (< {min_facts})",
        "features": features,
        "plan": {"hook": {"type": "hook", "fact_ids": [mover["fact_id"]]}, "bullets": bullets[:3]},
    }


def score(features: dict, repeat: bool) -> tuple[float, dict]:
    breakdown = {k: round(WEIGHTS[k] * features[k], 6) for k in WEIGHTS}
    breakdown["repeat_topic_penalty"] = -REPEAT_PENALTY if repeat else 0.0
    return round(sum(breakdown.values()), 6), breakdown


def story_id_for(session_date: str, topic: str, plan: dict) -> str:
    """Stable id: same session + topic + evidence plan => same story_id on every run."""
    return "st_" + sha256_text(f"{session_date}|{topic}|{canonical_json(plan)}")[:16]


def select_stories(ctx: Ctx, session_date: str) -> list[str]:
    sess = ctx.conn.execute("SELECT state, fixture FROM sessions WHERE session_date = ?", (session_date,)).fetchone()
    if sess is None or sess["state"] != SessionState.VALIDATED.value:
        raise ValidationError(f"session {session_date} is not VALIDATED", code="SESSION_NOT_VALIDATED")

    existing = [r["story_id"] for r in ctx.conn.execute(
        "SELECT story_id FROM stories WHERE session_date = ? ORDER BY score DESC, story_id", (session_date,))]
    if existing:
        log("story_select.idempotent_noop", session_date=session_date, stories=existing)
        return existing

    min_facts = int(ctx.cfg["min_facts_per_story"])
    lookback = int(ctx.cfg["repeat_topic_lookback_sessions"])
    recent_sessions = [r["session_date"] for r in ctx.conn.execute(
        "SELECT session_date FROM sessions WHERE session_date < ? ORDER BY session_date DESC LIMIT ?",
        (session_date, lookback))]
    recent_topics = set()
    if recent_sessions:
        q = ",".join("?" * len(recent_sessions))
        recent_topics = {r["topic"] for r in ctx.conn.execute(
            f"SELECT DISTINCT topic FROM stories WHERE session_date IN ({q}) AND state != 'CANCELLED'", recent_sessions)}

    candidates = []
    for topic, facts in sorted(_load_facts(ctx, session_date).items()):
        c = build_candidate(topic, facts, min_facts)
        if c is None:
            continue
        c["score"], c["breakdown"] = score(c["features"], topic in recent_topics)
        candidates.append(c)
    eligible = sorted((c for c in candidates if c["eligible"]), key=lambda c: (-c["score"], c["topic"]))
    chosen = eligible[: int(ctx.cfg["max_stories_per_session"])]

    now = iso_utc(ctx.clock.now())
    ids = []
    with transaction(ctx.conn):
        # Re-check under the write lock: a concurrent runner may have selected already.
        raced = [r["story_id"] for r in ctx.conn.execute(
            "SELECT story_id FROM stories WHERE session_date = ? ORDER BY score DESC, story_id", (session_date,))]
        if raced:
            return raced
        for c in chosen:
            sid = story_id_for(session_date, c["topic"], c["plan"])
            ctx.conn.execute(
                "INSERT INTO stories(story_id, session_date, topic, state, score, score_breakdown_json, plan_json, fixture,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, session_date, c["topic"], StoryState.SELECTED.value, c["score"], canonical_json(c["breakdown"]),
                 canonical_json(c["plan"]), sess["fixture"], now, now),
            )
            audit_mod.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="story", entity_id=sid,
                             action="select", to_state=StoryState.SELECTED.value,
                             detail={"topic": c["topic"], "score": c["score"], "breakdown": c["breakdown"]})
            ids.append(sid)
        audit_mod.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="session", entity_id=session_date,
                         action="story_select",
                         detail={"selected": ids,
                                 "rejected": [{"topic": c["topic"], "score": c["score"],
                                               "reason": c["reject_reason"] or "ranked below cutoff"}
                                              for c in candidates if c not in chosen]})
    log("story_select.done", session_date=session_date, selected=ids, candidates=len(candidates))
    return ids
