"""Kill-switch drill: prove that PAUSE ALL, DISABLE PLATFORM and CANCEL stop
every would_publish, and that a kill switch hit mid-flight aborts the attempt.

Runs in a fresh temporary home (never the operator's state), on fixture data only
(session must be labelled fixture, else DRILL_REQUIRES_FIXTURE). Network-free.
The drill advances its own fixed clock through the dispatch windows.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from .. import audit, controls, logs, pipeline
from ..clock import FixedClock, parse_aware
from ..config import Paths
from ..context import Ctx
from ..db import connect
from ..errors import ValidationError
from ..ingest.ingest import ingest, validate
from .simulator import run_due

DRILL_APPROVER = "kill-switch-drill"


def _count(ctx: Ctx, status: str, platform: str | None = None) -> int:
    q = "SELECT COUNT(*) FROM dispatches WHERE status = ?" + (" AND platform = ?" if platform else "")
    return ctx.conn.execute(q, (status, platform) if platform else (status,)).fetchone()[0]


def run_drill(cfg: dict, input_dir: str | os.PathLike, renderer=None, keep_home: str | None = None) -> dict:
    root = Path(keep_home) if keep_home else Path(tempfile.mkdtemp(prefix="ap_drill_"))
    import json
    summary = json.loads((Path(input_dir) / "daily_summary.json").read_text(encoding="utf-8"))
    clock = FixedClock(parse_aware(summary["generated_at"]) + timedelta(minutes=30))
    cfg = {**cfg, "max_stories_per_session": 1}
    paths = Paths(root / "home")
    conn = connect(paths.db)
    logs.configure(paths.logs, clock)
    ctx = Ctx(conn=conn, clock=clock, cfg=cfg, paths=paths, actor="drill")
    checks: list[dict] = []

    def check(name: str, ok: bool, **info) -> None:
        checks.append({"check": name, "ok": bool(ok), **info})

    try:
        res = ingest(ctx, input_dir)
        validate(ctx, res["session_date"])
        if not conn.execute("SELECT fixture FROM sessions").fetchone()[0]:
            raise ValidationError("the kill-switch drill runs on fixture data only", code="DRILL_REQUIRES_FIXTURE")
        (story,) = pipeline.build_drafts(ctx, res["session_date"], renderer)
        sid = story["story_id"]
        pipeline.approve(ctx, sid, DRILL_APPROVER)
        sched = pipeline.schedule(ctx, sid)["schedules"]
        slots = sorted({s["publish_at_utc"] for s in sched})
        by_platform = {s["platform"]: s["publish_at_utc"] for s in sched}

        # 1. PAUSE ALL at the first slot: nothing is evaluated
        clock.set(parse_aware(slots[0]))
        controls.pause_all(conn, clock, "drill", "drill: pause all")
        r = run_due(ctx)
        check("pause_all_blocks_run", r.get("blocked") == "PAUSE_ALL" and not r["results"]
              and _count(ctx, "WOULD_PUBLISH") == 0, due=r.get("due"))

        # 2. kill switch hit mid-flight (after claim, before record): attempt ABORTED, schedule kept
        controls.resume_all(conn, clock, "drill", "drill: resume")
        first = [p for p, t in by_platform.items() if t == slots[0]][0]

        def pause_mid_flight(point, info):
            if point == "before_record" and info["platform"] == first:
                controls.pause_all(conn, clock, "drill", "drill: mid-flight pause")
        r = run_due(ctx, hook=pause_mid_flight)
        mine = [x for x in r["results"] if x["platform"] == first]
        check("mid_flight_kill_switch_aborts", mine and mine[0]["status"] == "ABORTED"
              and _count(ctx, "WOULD_PUBLISH", first) == 0, results=r["results"])
        controls.resume_all(conn, clock, "drill", "drill: resume")

        # 3. DISABLE PLATFORM: that platform is skipped, others proceed
        controls.set_platform_enabled(conn, clock, first, False, "drill", "drill: disable")
        r = run_due(ctx)
        check("disabled_platform_skipped", _count(ctx, "WOULD_PUBLISH", first) == 0
              and any(x["platform"] == first and x["status"] == "SKIPPED" for x in r["results"]),
              results=r["results"])
        controls.set_platform_enabled(conn, clock, first, True, "drill", "drill: enable")

        # 4. CANCEL before the remaining slots: nothing further becomes would_publish
        before = _count(ctx, "WOULD_PUBLISH")
        pipeline.cancel(ctx, sid, "drill: cancel")
        clock.set(parse_aware(slots[-1]))
        r = run_due(ctx)
        check("cancel_stops_everything", _count(ctx, "WOULD_PUBLISH") == before and not r["results"],
              would_publish_before_cancel=before)

        chain = audit.verify_chain(conn)
        check("audit_chain_intact", chain["ok"], rows=chain["rows_checked"])
        return {"ok": all(c["ok"] for c in checks), "dry_run": True, "network": "none", "story_id": sid,
                "checks": checks, "home": str(root) if keep_home else None}
    finally:
        conn.close()
        if not keep_home:
            for dp, _d, fs in os.walk(root):
                for f in fs:
                    try:
                        os.chmod(os.path.join(dp, f), 0o644)
                    except OSError:
                        pass
            shutil.rmtree(root, ignore_errors=True)
