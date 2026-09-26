"""Point-in-time dataset, allowed slots, per-platform aggregation and the sample gate.

Point-in-time (no lookahead): a dataset "as of T" only contains observations with
``known_at_utc <= T`` (imported by then) and ``observed_at_utc <= T`` (measured
by then). Each post is scored at a fixed age: the first snapshot taken between
``horizon_hours`` and ``horizon_hours + horizon_window_hours`` after publication.
Posts without such a snapshot, or published outside the allowed slots, are
excluded and counted. Platforms are never mixed and metrics are never summed
into one score.

Allowed slots are exactly the pre-approved baseline waves (config ``waves`` x
``schedule.slot_interval_minutes``) -- no new times are ever generated. The
baseline (current fixed) slot is the first slot of the platform's first wave,
which is what the scheduler uses.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..clock import JST, iso_utc, parse_aware
from ..context import Ctx
from ..errors import ValidationError
from ..hashing import sha256_json
from .csv_import import METRIC_COLS

DERIVED = ("engagement_rate", "follow_rate")
REPORT_METRICS = ("impressions", "views", "watch_time_seconds", "completion_rate", "engagement_rate",
                  "follow_rate", "likes", "comments", "shares", "saves", "follows_gained")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def allowed_slots(cfg: dict, platform: str) -> list[dict]:
    out = []
    step = int(cfg["schedule"]["slot_interval_minutes"])
    for wave_name in cfg["platforms"][platform]["waves"]:
        w = cfg["waves"][wave_name]
        sh, sm = (int(x) for x in w["start_jst"].split(":"))
        eh, em = (int(x) for x in w["end_jst"].split(":"))
        t, end = sh * 60 + sm, eh * 60 + em
        while t < end:
            out.append({"slot": f"{wave_name}@{t // 60:02d}:{t % 60:02d}", "wave": wave_name,
                        "jst": f"{t // 60:02d}:{t % 60:02d}", "minute": t, "audience_tz": w["audience_tz"]})
            t += step
    return out


def baseline_slot(cfg: dict, platform: str) -> str:
    return allowed_slots(cfg, platform)[0]["slot"]


def slot_of(published_utc: str, slots: list[dict], tolerance_min: int) -> dict | None:
    local = parse_aware(published_utc).astimezone(JST)
    m = local.hour * 60 + local.minute + local.second / 60
    for s in slots:
        if abs(m - s["minute"]) <= tolerance_min:
            return s
    return None


def _derived(r: dict) -> dict:
    v = r.get("views")
    eng = None
    if v and None not in (r.get("likes"), r.get("comments"), r.get("shares")):
        eng = (r["likes"] + r["comments"] + r["shares"] + (r.get("saves") or 0)) / v
    fol = r["follows_gained"] / v if v and r.get("follows_gained") is not None else None
    return {"engagement_rate": eng, "follow_rate": fol}


def require_past(ctx: Ctx, as_of: datetime) -> str:
    """as_of must be strictly before the current (trusted) second. Imports record known_at at second
    precision, so nothing imported at or after the evaluation second can ever join an as_of dataset."""
    as_of_s, now_s = iso_utc(as_of), iso_utc(ctx.clock.now())
    if as_of_s >= now_s:
        raise ValidationError(f"as_of {as_of_s} is not in the past (now {now_s}); point-in-time evaluation"
                              " requires as_of < current second", code="AS_OF_NOT_IN_PAST",
                              details={"as_of_utc": as_of_s, "now_utc": now_s})
    return as_of_s


def build_dataset(ctx: Ctx, platform: str, as_of: datetime) -> dict:
    ocfg = ctx.cfg["optimizer"]
    as_of_s = require_past(ctx, as_of)
    h = timedelta(hours=float(ocfg["horizon_hours"]))
    w = timedelta(hours=float(ocfg["horizon_window_hours"]))
    slots = allowed_slots(ctx.cfg, platform)
    rows = [dict(r) for r in ctx.conn.execute(
        "SELECT * FROM post_metrics WHERE platform=? AND known_at_utc <= ? AND observed_at_utc <= ?"
        " ORDER BY post_ref, observed_at_utc, obs_id", (platform, as_of_s, as_of_s))]
    by_post: dict[str, list[dict]] = {}
    for r in rows:
        by_post.setdefault(r["post_ref"], []).append(r)
    posts, excluded = [], {"out_of_allowed_slot": 0, "no_horizon_snapshot": 0}
    for ref, snaps in sorted(by_post.items()):
        pub = parse_aware(snaps[0]["published_at_utc"])
        s = slot_of(snaps[0]["published_at_utc"], slots, int(ocfg["slot_tolerance_minutes"]))
        if s is None:
            excluded["out_of_allowed_slot"] += 1
            continue
        snap = next((x for x in snaps if pub + h <= parse_aware(x["observed_at_utc"]) <= pub + h + w), None)
        if snap is None:
            excluded["no_horizon_snapshot"] += 1
            continue
        local = pub.astimezone(ZoneInfo(s["audience_tz"]))
        pj = pub.astimezone(JST)
        posts.append({
            "post_ref": ref, "story_id": snap["story_id"], "obs_id": snap["obs_id"], "import_id": snap["import_id"],
            "row_sha256": snap["row_sha256"], "published_at_utc": snap["published_at_utc"],
            "observed_at_utc": snap["observed_at_utc"], "slot": s["slot"], "wave": s["wave"],
            "jst_date": pj.date().isoformat(), "jst_weekday": WEEKDAYS[pj.weekday()],
            "audience_tz": s["audience_tz"], "audience_local": local.isoformat(),
            "audience_local_hour": local.hour, "audience_weekday": WEEKDAYS[local.weekday()],
            **{c: snap[c] for c in METRIC_COLS}, **_derived(snap),
        })
    days = sorted({p["jst_date"] for p in posts})
    input_sha = sha256_json({"platform": platform, "as_of_utc": as_of_s,
                             "rows": [(p["obs_id"], p["row_sha256"]) for p in posts], "slots": slots,
                             "optimizer": ocfg})
    return {"platform": platform, "as_of_utc": as_of_s, "posts": posts, "excluded": excluded,
            "days": days, "slots": slots, "baseline_slot": slots[0]["slot"], "input_sha256": input_sha,
            "import_ids": sorted({p["import_id"] for p in posts})}


def gate(ctx: Ctx, ds: dict) -> dict:
    """Minimum evidence before any optimisation: >= min_days distinct days AND >= min_posts posts,
    and the newest post not older than max_data_age_days. Otherwise UNKNOWN -> keep the fixed slots."""
    o = ctx.cfg["optimizer"]
    n, d = len(ds["posts"]), len(ds["days"])
    reasons = []
    if d < int(o["min_days"]):
        reasons.append(f"days {d} < {o['min_days']}")
    if n < int(o["min_posts"]):
        reasons.append(f"posts {n} < {o['min_posts']}")
    if ds["posts"]:
        newest = max(parse_aware(p["published_at_utc"]) for p in ds["posts"])
        if parse_aware(ds["as_of_utc"]) - newest > timedelta(days=int(o["max_data_age_days"])):
            reasons.append(f"newest post older than {o['max_data_age_days']} days (stale)")
    return {"ok": not reasons, "status": "READY" if not reasons else "UNKNOWN", "posts": n, "days": d,
            "reasons": reasons}


def summarize(values: list, min_n: int) -> dict:
    vals = [v for v in values if v is not None]
    if len(vals) < min_n:
        return {"n": len(vals), "status": "UNKNOWN"}
    return {"n": len(vals), "status": "OK", "mean": round(statistics.fmean(vals), 6),
            "median": round(statistics.median(vals), 6)}


def report(ctx: Ctx, platform: str, as_of: datetime) -> dict:
    """Per-platform aggregation by slot, JST weekday and audience-local hour; every metric separate."""
    ds = build_dataset(ctx, platform, as_of)
    min_n = int(ctx.cfg["optimizer"]["min_arm_samples"])

    def group(key):
        out = {}
        for k in sorted({p[key] for p in ds["posts"]}, key=str):
            ps = [p for p in ds["posts"] if p[key] == k]
            out[str(k)] = {"posts": len(ps), "metrics": {m: summarize([p[m] for p in ps], min_n)
                                                         for m in REPORT_METRICS}}
        return out
    return {"platform": platform, "as_of_utc": ds["as_of_utc"], "input_sha256": ds["input_sha256"],
            "gate": gate(ctx, ds), "excluded": ds["excluded"], "posts": len(ds["posts"]),
            "days": len(ds["days"]), "baseline_slot": ds["baseline_slot"],
            "allowed_slots": [s["slot"] for s in ds["slots"]],
            "by_slot": group("slot"), "by_jst_weekday": group("jst_weekday"),
            "by_audience_local_hour": group("audience_local_hour"),
            "evidence_type": "observational", "causal_claim": False}


def parse_as_of(value: str | None, ctx: Ctx) -> datetime:
    """Default: the last whole second before now (see require_past)."""
    return parse_aware(value) if value else ctx.clock.now().replace(microsecond=0) - timedelta(seconds=1)

