"""Auto Publish System -- R1 DRY-RUN command line.

    python -m auto_publish.cli ingest --input <content_drop/YYYY-MM-DD>
    python -m auto_publish.cli build-drafts --date YYYY-MM-DD
    python -m auto_publish.cli queue
    python -m auto_publish.cli show <story_id>          # exact final caption/script
    python -m auto_publish.cli show-evidence <story_id>
    python -m auto_publish.cli approve <story_id> --by <name>
    python -m auto_publish.cli schedule <story_id>
    python -m auto_publish.cli cancel <story_id> --reason ...
    python -m auto_publish.cli retry <story_id> --reason ...
    python -m auto_publish.cli pause-all | resume-all
    python -m auto_publish.cli disable-platform <p> | enable-platform <p>
    python -m auto_publish.cli audit-verify

Exit codes: 0 ok, 2 refused / fail-closed, 1 unexpected error.
Nothing in this CLI can publish: release gate R1 has no PUBLISH command.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from .app import audit, controls, logs, pipeline
from .app.clock import Clock, FixedClock, parse_aware
from .app.config import load_config, resolve_home
from .app.context import Ctx
from .app.db import connect
from .app.errors import AutoPublishError
from .app.ingest.ingest import ingest, validate


def _ctx(args) -> Ctx:
    cfg = load_config(args.config)
    paths = resolve_home(args.home)
    now = args.now or os.environ.get("AUTO_PUBLISH_NOW")
    clock: Clock = FixedClock(parse_aware(now)) if now else Clock()
    conn = connect(paths.db)
    logs.configure(paths.logs, clock)
    actor = args.actor or os.environ.get("AUTO_PUBLISH_ACTOR") or f"cli:{getpass.getuser()}"
    return Ctx(conn=conn, clock=clock, cfg=cfg, paths=paths, actor=actor)


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def cmd_ingest(ctx, a):
    res = ingest(ctx, a.input, session_date=a.date)
    res["validation"] = validate(ctx, res["session_date"])
    return res


def cmd_build(ctx, a):
    return {"session_date": a.date, "stories": pipeline.build_drafts(ctx, a.date)}


def cmd_queue(ctx, a):
    rows = []
    for r in ctx.conn.execute("SELECT * FROM stories ORDER BY session_date DESC, score DESC, story_id"):
        sch = [dict(s) for s in ctx.conn.execute(
            "SELECT platform, wave, publish_at_jst, audience_local, status FROM schedules WHERE story_id = ?"
            " ORDER BY platform", (r["story_id"],))]
        rows.append({"story_id": r["story_id"], "session_date": r["session_date"], "topic": r["topic"],
                     "state": r["state"], "score": r["score"], "fixture": bool(r["fixture"]),
                     "attempts": r["attempts"], "approved_by": r["approved_by"],
                     "last_error": json.loads(r["last_error"]) if r["last_error"] else None, "schedules": sch})
    return {"paused": controls.is_paused(ctx.conn),
            "platforms": {p: controls.platform_enabled(ctx.conn, p, pc.get("enabled", False))
                          for p, pc in ctx.cfg["platforms"].items()},
            "sessions": [dict(s) for s in ctx.conn.execute(
                "SELECT session_date, state, fixture, manifest_sha256 FROM sessions ORDER BY session_date DESC")],
            "stories": rows}


def cmd_show(ctx, a):
    story = pipeline._story(ctx, a.story_id)
    out = {"story_id": a.story_id, "state": story["state"], "drafts": {}}
    for lang in ("en-US", "ja-JP"):
        row = ctx.conn.execute("SELECT body_json FROM drafts WHERE story_id = ? AND lang = ?", (a.story_id, lang)).fetchone()
        if row:
            body = json.loads(row["body_json"])
            out["drafts"][lang] = {"title": body["title"], "script": [s["text"] for s in body["segments"]],
                                   "caption": body["caption"]}
    return out


def cmd_show_evidence(ctx, a):
    story = pipeline._story(ctx, a.story_id)
    p = pipeline.story_dir(ctx, story) / "evidence.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    from .app.story.factcheck import source_refs
    return {"story_id": a.story_id, "source_refs": source_refs(ctx, story)}


def cmd_approve(ctx, a):
    return pipeline.approve(ctx, a.story_id, a.by)


def cmd_schedule(ctx, a):
    return pipeline.schedule(ctx, a.story_id)


def cmd_cancel(ctx, a):
    return pipeline.cancel(ctx, a.story_id, a.reason)


def cmd_retry(ctx, a):
    return pipeline.retry(ctx, a.story_id, a.reason)


def cmd_pause(ctx, a):
    controls.pause_all(ctx.conn, ctx.clock, ctx.actor, a.reason)
    return {"paused": True}


def cmd_resume(ctx, a):
    controls.resume_all(ctx.conn, ctx.clock, ctx.actor, a.reason)
    return {"paused": False}


def cmd_platform(enabled: bool):
    def run(ctx, a):
        if a.platform not in ctx.cfg["platforms"]:
            raise AutoPublishError(f"unknown platform {a.platform}", code="UNKNOWN_PLATFORM")
        controls.set_platform_enabled(ctx.conn, ctx.clock, a.platform, enabled, ctx.actor, a.reason)
        return {"platform": a.platform, "enabled": enabled, "adapter": ctx.cfg["platforms"][a.platform]["adapter"]}
    return run


def cmd_audit_verify(ctx, a):
    return audit.verify_chain(ctx.conn)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="auto_publish", description="Auto Publish System (release gate R1: DRY-RUN)")
    p.add_argument("--home", help="state directory (default: auto_publish/var or $AUTO_PUBLISH_HOME)")
    p.add_argument("--config", help="JSON config overlay")
    p.add_argument("--now", help="override clock (ISO-8601 with timezone) for reproducible runs")
    p.add_argument("--actor", help="actor name recorded in the audit trail")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest"); s.add_argument("--input", required=True); s.add_argument("--date"); s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("build-drafts"); s.add_argument("--date", required=True); s.set_defaults(fn=cmd_build)
    s = sub.add_parser("queue"); s.set_defaults(fn=cmd_queue)
    s = sub.add_parser("show"); s.add_argument("story_id"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("show-evidence"); s.add_argument("story_id"); s.set_defaults(fn=cmd_show_evidence)
    s = sub.add_parser("approve"); s.add_argument("story_id"); s.add_argument("--by", required=True); s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("schedule"); s.add_argument("story_id"); s.set_defaults(fn=cmd_schedule)
    s = sub.add_parser("cancel"); s.add_argument("story_id"); s.add_argument("--reason", required=True); s.set_defaults(fn=cmd_cancel)
    s = sub.add_parser("retry"); s.add_argument("story_id"); s.add_argument("--reason", required=True); s.set_defaults(fn=cmd_retry)
    s = sub.add_parser("pause-all"); s.add_argument("--reason", default=""); s.set_defaults(fn=cmd_pause)
    s = sub.add_parser("resume-all"); s.add_argument("--reason", default=""); s.set_defaults(fn=cmd_resume)
    s = sub.add_parser("disable-platform"); s.add_argument("platform"); s.add_argument("--reason", default=""); s.set_defaults(fn=cmd_platform(False))
    s = sub.add_parser("enable-platform"); s.add_argument("platform"); s.add_argument("--reason", default=""); s.set_defaults(fn=cmd_platform(True))
    s = sub.add_parser("audit-verify"); s.set_defaults(fn=cmd_audit_verify)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ctx = _ctx(args)
    except AutoPublishError as exc:
        _out({"ok": False, "error": exc.to_dict()})
        return 2
    try:
        result = args.fn(ctx, args)
        _out({"ok": True, "result": result})
        return 0
    except AutoPublishError as exc:
        logs.log("cli.refused", command=args.cmd, **exc.to_dict())
        _out({"ok": False, "error": exc.to_dict()})
        return 2
    except Exception as exc:  # pragma: no cover - surfaced, never swallowed
        logs.log("cli.unexpected", command=args.cmd, error=repr(exc))
        _out({"ok": False, "error": {"type": type(exc).__name__, "code": "UNEXPECTED", "message": str(exc)}})
        return 1
    finally:
        ctx.conn.close()


if __name__ == "__main__":
    sys.exit(main())
