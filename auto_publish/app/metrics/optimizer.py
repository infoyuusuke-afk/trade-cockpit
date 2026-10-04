"""Slot proposals (Thompson sampling, proposal-only) and Shadow comparison.

Nothing here changes a schedule: proposals are stored in ``slot_proposals``
(append-only) and the scheduler never reads them. Evidence is observational --
posting time is confounded with content, market day and platform changes, so a
proposal never claims a causal effect.

Algorithm ``slot_ts_normal.v1`` (one platform at a time, one objective metric):
  y = log1p(objective metric at the fixed horizon) per post;
  each allowed slot = arm with Normal posterior: mean (k0*mu0 + n*ybar)/(k0+n),
  sd sqrt(s2/(k0+n)) where mu0/s2 are the platform's pooled mean/variance;
  P(best) and P(arm > baseline) among slots with >= min_arm_samples posts, from ``draws``
  seeded draws (seed = input hash); untested slots only receive exploration share.
Decision (fail-closed):
  gate not met / baseline slot has < min_arm_samples  -> UNKNOWN (nothing stored)
  only the baseline slot has data, or it is most likely best -> BASELINE_CONFIRMED
  another slot with P(best) >= threshold and P(> baseline) >= threshold
      and every guardrail metric not worse than baseline by > tolerance -> PROPOSED
  anything else (tie, conflicting evidence, guardrail missing/failed) -> INCONCLUSIVE (no plan)
Exploration (only with BASELINE_CONFIRMED / PROPOSED): at most ``max_exploration``
(<= 20%) of posts, spread over the other allowed slots by P(best).
"""
from __future__ import annotations

import json
import math
import random
import statistics
from datetime import datetime

from .. import audit
from ..clock import iso_utc, parse_aware
from ..context import Ctx
from ..db import transaction
from ..errors import ValidationError
from ..hashing import canonical_json, sha256_json
from .csv_import import verify_imports
from .dataset import build_dataset, gate, summarize

ALGORITHM = "slot_ts_normal.v1"
SCHEMA = "auto_publish.slot_proposal.v1"
SHADOW_SCHEMA = "auto_publish.shadow_evaluation.v1"
GUARD_METRICS = ("completion_rate", "engagement_rate", "follow_rate")
CONFOUNDERS = ["story content / market day (one post per story per platform)", "platform algorithm changes",
               "seasonality and news flow"]


def _arms(ctx: Ctx, ds: dict, objective: str) -> tuple[list[dict], int]:
    o = ctx.cfg["optimizer"]
    usable = [p for p in ds["posts"] if p.get(objective) is not None]
    ys = [math.log1p(p[objective]) for p in usable]
    mu0 = statistics.fmean(ys) if ys else 0.0
    s2 = statistics.variance(ys) if len(ys) > 1 else 1.0
    s2 = max(s2, 1e-6)
    k0 = float(o["prior_strength"])
    arms = []
    for s in ds["slots"]:
        ps = [p for p in usable if p["slot"] == s["slot"]]
        y = [math.log1p(p[objective]) for p in ps]
        n = len(y)
        ybar = statistics.fmean(y) if y else mu0
        arms.append({"slot": s["slot"], "wave": s["wave"], "jst": s["jst"], "n": n,
                     "objective_mean_log1p": round(ybar, 6) if y else None,
                     "posterior_mean": (k0 * mu0 + n * ybar) / (k0 + n), "posterior_sd": math.sqrt(s2 / (k0 + n)),
                     "metrics": {m: summarize([p[m] for p in ps], int(o["min_arm_samples"]))
                                 for m in ("views", "impressions", "watch_time_seconds", *GUARD_METRICS)}})
    return arms, len(usable)


def _draw(arms: list[dict], ref: int | None, seed: int, draws: int) -> tuple[list[float], list[float]]:
    """P(best) per arm and P(arm > arms[ref]) from seeded posterior draws (deterministic)."""
    rng = random.Random(seed)
    wins, beats = [0] * len(arms), [0] * len(arms)
    for _ in range(draws):
        x = [rng.gauss(a["posterior_mean"], a["posterior_sd"]) for a in arms]
        wins[max(range(len(arms)), key=lambda i: (x[i], -i))] += 1
        if ref is not None:
            for i in range(len(arms)):
                beats[i] += x[i] > x[ref]
    return [round(w / draws, 4) for w in wins], [round(b / draws, 4) for b in beats]


def _thompson(arms: list[dict], baseline: str, seed: int, draws: int, min_n: int) -> None:
    """Decision statistics use only slots with >= min_n posts; the all-slot draw (untested slots
    at the prior) is used only to spread the bounded exploration share."""
    tested = [a for a in arms if a["n"] >= min_n]
    ref = next(i for i, a in enumerate(tested) if a["slot"] == baseline)
    p_best, p_beat = _draw(tested, ref, seed, draws)
    for a, pb, pv in zip(tested, p_best, p_beat):
        a["p_best"] = pb
        a["p_better_than_baseline"] = pv if a["slot"] != baseline else None
    p_explore, _ = _draw(arms, None, seed ^ 0x5EED, draws)
    for a, pe in zip(arms, p_explore):
        a.setdefault("p_best", None)
        a.setdefault("p_better_than_baseline", None)
        a["p_explore"] = pe
        a["tested"] = a["n"] >= min_n
        a["posterior_mean"] = round(a["posterior_mean"], 6)
        a["posterior_sd"] = round(a["posterior_sd"], 6)


def _exploration(arms: list[dict], primary: str, share: float) -> dict:
    others = [a for a in arms if a["slot"] != primary]
    if not others or share <= 0:
        return {}
    weights = [a["p_explore"] for a in others]
    tot = sum(weights)
    if tot <= 0:
        weights, tot = [1.0] * len(others), float(len(others))
    return {a["slot"]: math.floor(share * w / tot * 10_000) / 10_000 for a, w in zip(others, weights)}


def _guardrails(ctx: Ctx, arms: list[dict], cand: str, baseline: str, platform: str) -> list[dict]:
    o = ctx.cfg["optimizer"]
    tol = float(o["guardrail_tolerance"])
    a = next(x for x in arms if x["slot"] == cand)
    b = next(x for x in arms if x["slot"] == baseline)
    out = []
    for m in o["guardrails"].get(platform, []):
        am, bm = a["metrics"][m], b["metrics"][m]
        if am["status"] != "OK" or bm["status"] != "OK":
            out.append({"metric": m, "ok": False, "status": "UNKNOWN", "reason": "insufficient data (fail-closed)"})
            continue
        ok = am["mean"] >= bm["mean"] * (1 - tol)
        out.append({"metric": m, "ok": ok, "candidate_mean": am["mean"], "baseline_mean": bm["mean"],
                    "tolerance": tol})
    return out


def evaluate(ctx: Ctx, platform: str, as_of: datetime) -> dict:
    """Pure evaluation (no writes). Same inputs => byte-identical result."""
    o = ctx.cfg["optimizer"]
    ds = build_dataset(ctx, platform, as_of)
    verify_imports(ctx, ds["import_ids"])
    g = gate(ctx, ds)
    objective = o["objective"][platform]
    base = {"schema": SCHEMA, "platform": platform, "as_of_utc": ds["as_of_utc"], "algorithm_version": ALGORITHM,
            "input_sha256": ds["input_sha256"], "applies_automatically": False, "evidence_type": "observational",
            "causal_claim": False, "confounders_not_adjusted": CONFOUNDERS,
            "baseline_slot": ds["baseline_slot"], "allowed_slots": [s["slot"] for s in ds["slots"]],
            "objective": {"metric": objective, "transform": "log1p", "horizon_hours": o["horizon_hours"]},
            "data": {"posts": len(ds["posts"]), "days": len(ds["days"]),
                     "first_published_utc": min((p["published_at_utc"] for p in ds["posts"]), default=None),
                     "last_published_utc": max((p["published_at_utc"] for p in ds["posts"]), default=None),
                     "excluded": ds["excluded"], "import_ids": ds["import_ids"]},
            "gate": g, "recommended_slot": None, "exploration": {}}
    if not g["ok"]:
        return {**base, "status": "UNKNOWN", "reason": "; ".join(g["reasons"])}
    arms, usable = _arms(ctx, ds, objective)
    base["data"]["posts_with_objective"] = usable
    min_n = int(o["min_arm_samples"])
    bl = next(a for a in arms if a["slot"] == ds["baseline_slot"])
    if bl["n"] < min_n:
        return {**base, "status": "UNKNOWN", "arms": arms,
                "reason": f"baseline slot has {bl['n']} posts with {objective} (< {min_n})"}
    seed = int(ds["input_sha256"][:16], 16)
    _thompson(arms, ds["baseline_slot"], seed, int(o["draws"]), min_n)
    base.update(arms=arms, seed=seed, draws=int(o["draws"]))
    thr, share = float(o["decision_threshold"]), float(o["max_exploration"])
    tested = [a for a in arms if a["n"] >= min_n]
    best = max(tested, key=lambda a: (a["p_best"], a["slot"] == ds["baseline_slot"]))
    if len(tested) == 1 or best["slot"] == ds["baseline_slot"]:
        return {**base, "status": "BASELINE_CONFIRMED",
                "reason": "only the fixed slot has enough data" if len(tested) == 1
                else "the fixed slot is the most likely best among tested slots",
                "exploration": _exploration(arms, ds["baseline_slot"], share)}
    rails = _guardrails(ctx, arms, best["slot"], ds["baseline_slot"], platform)
    decision = {"candidate": best["slot"], "p_best": best["p_best"],
                "p_better_than_baseline": best["p_better_than_baseline"], "threshold": thr, "guardrails": rails}
    if best["p_best"] >= thr and best["p_better_than_baseline"] >= thr and all(r["ok"] for r in rails):
        return {**base, "status": "PROPOSED", "decision": decision, "recommended_slot": best["slot"],
                "reason": f"{best['slot']} is best with P={best['p_best']} and beats the fixed slot with"
                          f" P={best['p_better_than_baseline']}; guardrails hold",
                "exploration": _exploration(arms, best["slot"], share)}
    return {**base, "status": "INCONCLUSIVE", "decision": decision,
            "reason": "evidence does not clear the threshold or a guardrail is missing/failed; fixed slot kept"}


def propose(ctx: Ctx, platform: str, as_of: datetime) -> dict:
    """Evaluate and store the proposal (append-only). UNKNOWN is audited but never stored as a proposal."""
    res = evaluate(ctx, platform, as_of)
    now_s = iso_utc(ctx.clock.now())
    sha = sha256_json(res)
    with transaction(ctx.conn):
        if res["status"] == "UNKNOWN":
            audit.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="slot_proposal", entity_id=platform,
                         action="proposal_withheld", to_state="UNKNOWN",
                         detail={"as_of_utc": res["as_of_utc"], "input_sha256": res["input_sha256"],
                                 "reason": res["reason"]})
            return {**res, "proposal_id": None, "proposal_sha256": None}
        prev = ctx.conn.execute(
            "SELECT proposal_id, input_sha256, proposal_sha256 FROM slot_proposals WHERE platform=? AND as_of_utc=?"
            " AND algorithm_version=?", (platform, res["as_of_utc"], ALGORITHM)).fetchone()
        if prev:
            # one proposal per (platform, as_of, algorithm): a re-evaluation must reproduce it exactly;
            # anything else is refused, never stored beside it and never written over it
            if prev["input_sha256"] != res["input_sha256"]:
                raise ValidationError("a proposal for this platform and as_of already exists with different input",
                                      code="PROPOSAL_AS_OF_CONFLICT",
                                      details={"proposal_id": prev["proposal_id"], "stored_input": prev["input_sha256"],
                                               "new_input": res["input_sha256"]})
            if prev["proposal_sha256"] != sha:
                raise ValidationError("re-evaluation differs from the stored proposal", code="PROPOSAL_NONDETERMINISTIC")
            return {**res, "proposal_id": prev["proposal_id"], "proposal_sha256": sha, "noop": True}
        cur = ctx.conn.execute(
            "INSERT INTO slot_proposals(platform, as_of_utc, status, algorithm_version, input_sha256, proposal_json,"
            " proposal_sha256, created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
            (platform, res["as_of_utc"], res["status"], ALGORITHM, res["input_sha256"], canonical_json(res), sha, now_s))
        audit.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="slot_proposal", entity_id=str(cur.lastrowid),
                     action="proposal_recorded", to_state=res["status"],
                     detail={"platform": platform, "as_of_utc": res["as_of_utc"], "input_sha256": res["input_sha256"],
                             "proposal_sha256": sha, "recommended_slot": res["recommended_slot"],
                             "applies_automatically": False})
    return {**res, "proposal_id": cur.lastrowid, "proposal_sha256": sha, "noop": False}


def load_proposal(ctx: Ctx, proposal_id: int) -> dict:
    row = ctx.conn.execute("SELECT * FROM slot_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None:
        raise ValidationError(f"unknown proposal {proposal_id}", code="PROPOSAL_NOT_FOUND")
    body = json.loads(row["proposal_json"])
    if sha256_json(body) != row["proposal_sha256"]:
        raise ValidationError("stored proposal hash mismatch", code="PROPOSAL_TAMPERED")
    return {**body, "proposal_id": row["proposal_id"], "proposal_sha256": row["proposal_sha256"]}


def shadow(ctx: Ctx, proposal_id: int, as_of: datetime) -> dict:
    """Compare, after the proposal date, posts in the fixed slot vs posts in the proposed slot(s).
    Observational only; per metric, per side; UNKNOWN when either side lacks samples."""
    p = load_proposal(ctx, proposal_id)
    if parse_aware(iso_utc(as_of)) <= parse_aware(p["as_of_utc"]):
        raise ValidationError("shadow as_of must be after the proposal's as_of", code="SHADOW_WINDOW_EMPTY")
    ds = build_dataset(ctx, p["platform"], as_of)
    verify_imports(ctx, ds["import_ids"])
    after = [x for x in ds["posts"] if x["published_at_utc"] > p["as_of_utc"]]
    min_n = int(ctx.cfg["optimizer"]["min_arm_samples"])
    proposed = [p["recommended_slot"]] if p["recommended_slot"] else sorted(p["exploration"])
    metrics = ("views", "impressions", "watch_time_seconds", *GUARD_METRICS)

    def side(slot):
        ps = [x for x in after if x["slot"] == slot]
        return {"slot": slot, "posts": len(ps), "metrics": {m: summarize([x[m] for x in ps], min_n) for m in metrics}}
    fixed = side(p["baseline_slot"])
    comps = []
    for s in proposed:
        prop = side(s)
        per = {}
        for m in metrics:
            f, q = fixed["metrics"][m], prop["metrics"][m]
            per[m] = ({"status": "UNKNOWN"} if f["status"] != "OK" or q["status"] != "OK" else
                      {"status": "OK", "proposed_minus_fixed_mean": round(q["mean"] - f["mean"], 6),
                       "proposed_over_fixed_median": round(q["median"] / f["median"], 6) if f["median"] else None})
        comps.append({"proposed": prop, "by_metric": per})
    input_sha = sha256_json({"proposal_sha256": p["proposal_sha256"], "as_of_utc": ds["as_of_utc"],
                             "rows": [(x["obs_id"], x["row_sha256"]) for x in after]})
    res = {"schema": SHADOW_SCHEMA, "proposal_id": proposal_id, "proposal_sha256": p["proposal_sha256"],
           "platform": p["platform"], "proposal_as_of_utc": p["as_of_utc"], "as_of_utc": ds["as_of_utc"],
           "window": {"from_exclusive": p["as_of_utc"], "to_inclusive": ds["as_of_utc"], "posts": len(after)},
           "fixed": fixed, "comparisons": comps, "input_sha256": input_sha, "evidence_type": "observational",
           "causal_claim": False, "applies_automatically": False}
    sha = sha256_json(res)
    with transaction(ctx.conn):
        prev = ctx.conn.execute("SELECT eval_id FROM shadow_evaluations WHERE proposal_id=? AND as_of_utc=?"
                                " AND input_sha256=?", (proposal_id, ds["as_of_utc"], input_sha)).fetchone()
        if prev:
            return {**res, "eval_id": prev["eval_id"], "result_sha256": sha, "noop": True}
        cur = ctx.conn.execute("INSERT INTO shadow_evaluations(proposal_id, as_of_utc, input_sha256, result_json,"
                               " result_sha256, created_at_utc) VALUES (?,?,?,?,?,?)",
                               (proposal_id, ds["as_of_utc"], input_sha, canonical_json(res), sha,
                                iso_utc(ctx.clock.now())))
        audit.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="shadow_evaluation",
                     entity_id=str(cur.lastrowid), action="shadow_recorded", to_state="RECORDED",
                     detail={"proposal_id": proposal_id, "as_of_utc": ds["as_of_utc"], "result_sha256": sha})
    return {**res, "eval_id": cur.lastrowid, "result_sha256": sha, "noop": False}
