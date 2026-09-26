"""Stage runner: STORY_SELECT -> ... -> APPROVAL -> SCHEDULE (stop; no PUBLISH in R1).

Failure policy
--------------
* FailClosedError / unexpected exception -> story FAILED (records the state it
  failed from, so ``retry`` can re-enter exactly that stage).
* TransientError -> attempts += 1; the story stays put while attempts remain,
  and becomes FAILED once ``max_attempts`` is reached.
* Every stage is idempotent: re-running a finished stage is a no-op, and a
  crashed stage can be re-run because artifacts are written atomically and
  deterministically.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import audit, controls
from .clock import iso_utc
from .compliance import rules as compliance
from .context import Ctx
from .db import transaction
from .errors import (
    ApprovalError, AutoPublishError, ComplianceError, ControlBlockedError, EvidenceError, FactCheckError,
    FailClosedError, SchedulingError, StateConflictError, TransientError, ValidationError,
)
from .evidence import store as ev
from .hashing import canonical_json, sha256_file, sha256_json, sha256_text, write_atomic, write_json_atomic
from .localization.localize import LANGS, localize
from .logs import log
from .publishers.base import PostBundle
from .publishers.registry import get_adapter
from .render.ffmpeg_render import CAPTIONS, COVER, MASTER, FfmpegRenderer, build_srt, captions_file, variant_outputs
from .scheduler.slots import compute_slot
from .state_machine import StoryState as S, transition_story
from .story import factcheck
from .story.script import build_script
from .story.select import select_stories
from .tts import narration as tts

NON_RETRYABLE = (ComplianceError, EvidenceError, FactCheckError, ValidationError, ApprovalError)
AUTO_STATES = (S.SELECTED, S.FACT_CHECKED, S.SCRIPTED, S.LOCALIZED, S.RENDERED)
# Stories rendered before TTS/multilingual captions (R1 acceptance) carry exactly this set.
LEGACY_ARTIFACT_FILES = ("story.json", "post_en.json", "post_ja.json", "evidence.json", CAPTIONS, MASTER, COVER,
                         "render_manifest.json")
# Every story rendered now carries at least this set. Narration audio and extra render
# variants are added per story and declared in render_manifest.json["artifact_set"].
ARTIFACT_FILES = LEGACY_ARTIFACT_FILES + (tts.TTS_MANIFEST,) + tuple(captions_file(lang) for lang in LANGS)


def _story(ctx: Ctx, story_id: str) -> dict:
    row = ctx.conn.execute("SELECT * FROM stories WHERE story_id = ?", (story_id,)).fetchone()
    if row is None:
        raise ValidationError(f"unknown story {story_id}", code="STORY_NOT_FOUND")
    return dict(row)


def story_dir(ctx: Ctx, story: dict) -> Path:
    return ctx.paths.artifacts / story["session_date"] / story["story_id"]


def _save_draft(ctx: Ctx, story_id: str, lang: str, body: dict) -> str:
    sha = sha256_json(body)
    ctx.conn.execute(
        "INSERT INTO drafts(story_id, lang, body_json, sha256) VALUES (?,?,?,?)"
        " ON CONFLICT(story_id, lang) DO UPDATE SET body_json=excluded.body_json, sha256=excluded.sha256",
        (story_id, lang, canonical_json(body), sha),
    )
    return sha


def _draft(ctx: Ctx, story_id: str, lang: str) -> dict:
    row = ctx.conn.execute("SELECT body_json, sha256 FROM drafts WHERE story_id = ? AND lang = ?",
                           (story_id, lang)).fetchone()
    if row is None:
        raise FactCheckError(f"{story_id}: draft {lang} missing", code="DRAFT_MISSING")
    body = json.loads(row["body_json"])
    if sha256_json(body) != row["sha256"]:
        raise EvidenceError(f"{story_id}: stored draft {lang} hash mismatch", code="DRAFT_TAMPERED")
    return body


# ------------------------------------------------------------------ stages

def _stage_fact_check(ctx: Ctx, story: dict, renderer) -> tuple[S, dict, dict]:
    refs = factcheck.check_story(ctx, story)
    return S.FACT_CHECKED, {}, {"verified_refs": [{"fact_id": r["fact_id"], "sha256": r["sha256"]} for r in refs]}


def _stage_script(ctx: Ctx, story: dict, renderer) -> tuple[S, dict, dict]:
    refs = factcheck.source_refs(ctx, story)
    script = build_script(story, refs)
    with transaction(ctx.conn):
        sha = _save_draft(ctx, story["story_id"], "canonical", script)
    return S.SCRIPTED, {}, {"script_sha256": sha}


def _stage_localize(ctx: Ctx, story: dict, renderer) -> tuple[S, dict, dict]:
    script = _draft(ctx, story["story_id"], "canonical")
    posts = [localize(script, lang) for lang in LANGS]
    compliance.enforce(posts, story["session_date"])
    shas = {}
    with transaction(ctx.conn):
        for p in posts:
            shas[p["lang"]] = _save_draft(ctx, story["story_id"], p["lang"], p)
    return S.LOCALIZED, {}, {"drafts": shas}


def _stage_render(ctx: Ctx, story: dict, renderer) -> tuple[S, dict, dict]:
    ev.verify_session(ctx.conn, story["session_date"])
    sdir = story_dir(ctx, story)
    sdir.mkdir(parents=True, exist_ok=True)
    script = _draft(ctx, story["story_id"], "canonical")
    post_en = _draft(ctx, story["story_id"], "en-US")
    post_ja = _draft(ctx, story["story_id"], "ja-JP")
    posts = {"en-US": post_en, "ja-JP": post_ja}
    compliance.enforce([post_en, post_ja], story["session_date"])
    session = ctx.conn.execute("SELECT manifest_sha256 FROM sessions WHERE session_date = ?",
                               (story["session_date"],)).fetchone()
    write_json_atomic(sdir / "story.json", script)
    write_json_atomic(sdir / "post_en.json", post_en)
    write_json_atomic(sdir / "post_ja.json", post_ja)
    write_json_atomic(sdir / "evidence.json", {
        "schema": "auto_publish.evidence.v1",
        "story_id": story["story_id"],
        "session_date": story["session_date"],
        "evidence_manifest_sha256": session["manifest_sha256"],
        "source_refs": script["source_refs"],
    })

    # narration (TTS) -> audio-driven timeline per language; fail-closed on length/provider
    seg_s = int(ctx.cfg["render"]["segment_seconds"])
    narrations = [tts.narrate(posts[lang], ctx.cfg["tts"], seg_s) for lang in LANGS]
    extra: list[str] = []
    for n in narrations:
        if n.wav is not None:
            write_atomic(sdir / n.file, n.wav)
            extra.append(n.file)
    tts_manifest = tts.build_manifest(story["story_id"], narrations)
    write_json_atomic(sdir / tts.TTS_MANIFEST, tts_manifest)

    # subtitles per language, from the same boundaries as the narration
    for n in narrations:
        srt = build_srt(n.timeline, n.lang)
        violations = compliance.check_captions_srt(srt, n.lang)
        if violations:
            raise ComplianceError("caption check failed", violations)
        write_atomic(sdir / captions_file(n.lang), srt.encode("utf-8"))
        if n.lang == "en-US":
            write_atomic(sdir / CAPTIONS, srt.encode("utf-8"))   # R1 name, kept for compatibility

    variants = list(ctx.cfg["render"].get("variants", ["en_primary"]))
    plan = {"variants": variants, "posts": posts,
            "timelines": {n.lang: n.timeline for n in narrations},
            "narration": {n.lang: n.file for n in narrations}}
    manifest = renderer.render(sdir, post_en, plan)
    extra += [f for f in variant_outputs(variants) if f not in ARTIFACT_FILES]
    manifest["artifact_set"] = sorted(set(ARTIFACT_FILES + tuple(extra)) - {"render_manifest.json"})
    write_json_atomic(sdir / "render_manifest.json", manifest)

    hashes = {}
    with transaction(ctx.conn):
        for name in (*ARTIFACT_FILES, *extra):
            p = sdir / name
            if not p.is_file():
                raise FailClosedError(f"artifact {name} missing after render", code="ARTIFACT_MISSING")
            sha = sha256_file(p)
            hashes[name] = sha
            ctx.conn.execute(
                "INSERT INTO artifacts(story_id, name, rel_path, sha256, size_bytes) VALUES (?,?,?,?,?)"
                " ON CONFLICT(story_id, name) DO UPDATE SET rel_path=excluded.rel_path, sha256=excluded.sha256,"
                " size_bytes=excluded.size_bytes",
                (story["story_id"], name, str(p.relative_to(ctx.paths.artifacts)), sha, p.stat().st_size),
            )
        stale = [r["name"] for r in ctx.conn.execute("SELECT name FROM artifacts WHERE story_id = ?",
                                                     (story["story_id"],)) if r["name"] not in hashes]
        for name in stale:   # e.g. a variant dropped between a failed attempt and this one
            ctx.conn.execute("DELETE FROM artifacts WHERE story_id = ? AND name = ?", (story["story_id"], name))
    content_sha = sha256_json(hashes)
    tts_summary = {lang: {k: m[k] for k in ("provider", "voice", "timing", "total_seconds", "narration_sha256")}
                   for lang, m in tts_manifest["langs"].items()}
    return S.RENDERED, {"content_sha256": content_sha}, {"content_sha256": content_sha, "artifacts": hashes,
                                                          "tts": tts_summary}


def verify_artifacts(ctx: Ctx, story: dict) -> str:
    """Re-hash every artifact on disk; return the content hash. Raises on any drift."""
    rows = {r["name"]: r for r in ctx.conn.execute("SELECT * FROM artifacts WHERE story_id = ?", (story["story_id"],))}
    if "render_manifest.json" not in rows:
        raise EvidenceError(f"{story['story_id']}: artifact set incomplete", code="ARTIFACT_MISSING")
    hashes = {}
    for name, r in rows.items():
        p = ctx.paths.artifacts / r["rel_path"]
        if not p.is_file():
            raise EvidenceError(f"{name} missing on disk", code="ARTIFACT_MISSING")
        actual = sha256_file(p)
        if actual != r["sha256"]:
            raise EvidenceError(f"{name} changed after render", code="ARTIFACT_TAMPERED",
                                details={"name": name, "expected": r["sha256"], "actual": actual})
        hashes[name] = actual
    # the declared set lives in the (hash-verified) render manifest; rows must match it exactly
    manifest = json.loads((ctx.paths.artifacts / rows["render_manifest.json"]["rel_path"]).read_text(encoding="utf-8"))
    declared = manifest.get("artifact_set")
    expected = set(LEGACY_ARTIFACT_FILES) if declared is None else set(declared) | {"render_manifest.json"}
    if declared is not None and not set(ARTIFACT_FILES) <= expected:
        raise EvidenceError(f"{story['story_id']}: declared artifact set lacks required files", code="ARTIFACT_MISSING")
    if set(rows) != expected:
        raise EvidenceError(f"{story['story_id']}: artifact set incomplete", code="ARTIFACT_MISSING",
                            details={"missing": sorted(expected - set(rows)), "unexpected": sorted(set(rows) - expected)})
    content = sha256_json(hashes)
    if story.get("content_sha256") and content != story["content_sha256"]:
        raise EvidenceError("content hash drift", code="ARTIFACT_TAMPERED")
    return content


def _stage_request_approval(ctx: Ctx, story: dict, renderer) -> tuple[S, dict, dict]:
    content = verify_artifacts(ctx, story)
    return S.AWAITING_APPROVAL, {}, {"content_sha256": content}


STAGES = {
    S.SELECTED: ("FACT_CHECK", _stage_fact_check),
    S.FACT_CHECKED: ("SCRIPT", _stage_script),
    S.SCRIPTED: ("LOCALIZE", _stage_localize),
    S.LOCALIZED: ("ASSET_RENDER", _stage_render),
    S.RENDERED: ("APPROVAL_REQUEST", _stage_request_approval),
}


# ------------------------------------------------------------------ failure handling

def _fail(ctx: Ctx, story: dict, exc: BaseException, stage: str) -> None:
    err = exc.to_dict() if isinstance(exc, AutoPublishError) else {
        "type": type(exc).__name__, "code": "UNEXPECTED", "message": str(exc), "retryable": False, "details": {}}
    err["stage"] = stage
    frm = S(story["state"])
    transition_story(ctx.conn, ctx.clock, story["story_id"], frm, S.FAILED, actor=ctx.actor,
                     reason=err["code"], detail={"error": err},
                     extra_updates={"last_error": canonical_json(err), "failed_from_state": frm.value})
    log("stage.failed_closed", story_id=story["story_id"], stage=stage, **{k: err[k] for k in ("code", "message")})


def _transient(ctx: Ctx, story: dict, exc: TransientError, stage: str) -> bool:
    """Record a transient failure. Returns True if the story was moved to FAILED."""
    attempts = story["attempts"] + 1
    err = {**exc.to_dict(), "stage": stage, "attempt": attempts}
    if attempts >= int(ctx.cfg["max_attempts"]):
        with transaction(ctx.conn):
            ctx.conn.execute("UPDATE stories SET attempts = ? WHERE story_id = ?", (attempts, story["story_id"]))
            transition_story(ctx.conn, ctx.clock, story["story_id"], S(story["state"]), S.FAILED, actor=ctx.actor,
                             reason="MAX_ATTEMPTS_EXCEEDED", detail={"error": err},
                             extra_updates={"last_error": canonical_json(err), "failed_from_state": story["state"]})
        log("stage.retries_exhausted", story_id=story["story_id"], stage=stage, attempts=attempts)
        return True
    with transaction(ctx.conn):
        ctx.conn.execute("UPDATE stories SET attempts = ?, last_error = ?, updated_at = ? WHERE story_id = ?",
                         (attempts, canonical_json(err), iso_utc(ctx.clock.now()), story["story_id"]))
        audit.append(ctx.conn, ctx.clock, actor=ctx.actor, entity_type="story", entity_id=story["story_id"],
                      action="transient_error", from_state=story["state"], to_state=story["state"], detail=err)
    log("stage.transient_error", story_id=story["story_id"], stage=stage, attempt=attempts, message=str(exc))
    return False


def run_stage(ctx: Ctx, story_id: str, renderer) -> dict:
    story = _story(ctx, story_id)
    state = S(story["state"])
    if state not in STAGES:
        return {"story_id": story_id, "state": state.value, "ran": None}
    stage, fn = STAGES[state]
    try:
        nxt, updates, detail = fn(ctx, story, renderer)
    except StateConflictError:
        raise
    except TransientError as exc:
        failed = _transient(ctx, story, exc, stage)
        return {"story_id": story_id, "state": S.FAILED.value if failed else state.value, "ran": stage,
                "error": exc.to_dict()}
    except Exception as exc:  # FailClosedError and anything unexpected
        _fail(ctx, story, exc, stage)
        return {"story_id": story_id, "state": S.FAILED.value, "ran": stage,
                "error": exc.to_dict() if isinstance(exc, AutoPublishError) else {"code": "UNEXPECTED", "message": str(exc)}}
    transition_story(ctx.conn, ctx.clock, story_id, state, nxt, actor=ctx.actor, reason=f"{stage} ok",
                     extra_updates=updates, detail=detail)
    log("stage.ok", story_id=story_id, stage=stage, to_state=nxt.value)
    return {"story_id": story_id, "state": nxt.value, "ran": stage}


def advance(ctx: Ctx, story_id: str, renderer) -> dict:
    """Run automatic stages until the story needs a human (AWAITING_APPROVAL),
    fails, or hits a transient error."""
    result = {"story_id": story_id, "state": _story(ctx, story_id)["state"], "ran": None}
    for _ in range(len(STAGES) + 1):
        if S(result["state"]) not in STAGES:
            break
        result = run_stage(ctx, story_id, renderer)
        if "error" in result:
            break
    return result


def build_drafts(ctx: Ctx, session_date: str, renderer=None) -> list[dict]:
    controls.require_not_paused(ctx.conn, "build-drafts")
    renderer = renderer or FfmpegRenderer(ctx.cfg)
    ids = select_stories(ctx, session_date)
    return [advance(ctx, sid, renderer) for sid in ids]


# ------------------------------------------------------------------ human gates

def approve(ctx: Ctx, story_id: str, approver: str) -> dict:
    approver = (approver or "").strip()
    if not approver or approver.lower() in {"system", "auto", "cron", "scheduler"}:
        raise ApprovalError("approval requires a named human approver (--by)", code="APPROVER_REQUIRED")
    story = _story(ctx, story_id)
    if story["state"] == S.APPROVED.value or story["state"] == S.SCHEDULED.value:
        return {"story_id": story_id, "state": story["state"], "noop": True}
    if story["state"] != S.AWAITING_APPROVAL.value:
        raise ApprovalError(f"{story_id} is {story['state']}, not AWAITING_APPROVAL", code="NOT_AWAITING_APPROVAL")
    try:
        content = verify_artifacts(ctx, story)
        sdir = story_dir(ctx, story)
        posts = [json.loads((sdir / f).read_text(encoding="utf-8")) for f in ("post_en.json", "post_ja.json")]
        compliance.enforce(posts, story["session_date"])
        tts.verify(sdir, posts)
    except FailClosedError as exc:
        _fail(ctx, story, exc, "APPROVAL")
        raise
    transition_story(ctx.conn, ctx.clock, story_id, S.AWAITING_APPROVAL, S.APPROVED, actor=approver,
                     reason="human approval",
                     extra_updates={"approved_content_sha256": content, "approved_by": approver,
                                    "approved_at": iso_utc(ctx.clock.now())},
                     detail={"approved_content_sha256": content})
    log("approval.granted", story_id=story_id, approver=approver, content_sha256=content)
    return {"story_id": story_id, "state": S.APPROVED.value, "approved_content_sha256": content, "noop": False}


def idempotency_key(story_id: str, platform: str, approved_content_sha256: str) -> str:
    return sha256_text(f"{story_id}|{platform}|{approved_content_sha256}")[:32]


def post_bundle(story: dict, platform: str, sdir: Path, post_en: dict, post_ja: dict, manifest: dict, content: str,
                evidence_manifest_sha256: str, idem: str, slot_info: dict) -> PostBundle:
    """The single place a PostBundle is assembled (SCHEDULE and WOULD_PUBLISH must agree byte-for-byte)."""
    return PostBundle(
        story_id=story["story_id"], session_date=story["session_date"], platform=platform, story_dir=sdir,
        post_en=post_en, post_ja=post_ja, render_manifest=manifest, content_sha256=content,
        approved_by=story["approved_by"], evidence_manifest_sha256=evidence_manifest_sha256,
        fixture=bool(story["fixture"]), idempotency_key=idem, extra={"slot": slot_info},
    )


def schedule(ctx: Ctx, story_id: str) -> dict:
    controls.require_not_paused(ctx.conn, "schedule")
    story = _story(ctx, story_id)
    if story["state"] == S.SCHEDULED.value:
        rows = [dict(r) for r in ctx.conn.execute("SELECT * FROM schedules WHERE story_id = ? ORDER BY platform",
                                                  (story_id,))]
        return {"story_id": story_id, "state": story["state"], "schedules": rows, "noop": True}
    if story["state"] != S.APPROVED.value:
        raise ApprovalError(f"{story_id} is {story['state']}; schedule requires APPROVED (human approval first)",
                            code="APPROVAL_REQUIRED")
    if not story["approved_by"] or not story["approved_content_sha256"]:
        raise ApprovalError("approval record incomplete", code="APPROVAL_REQUIRED")

    enabled = [p for p, pc in sorted(ctx.cfg["platforms"].items())
               if controls.platform_enabled(ctx.conn, p, pc.get("enabled", False))]
    if not enabled:
        raise ControlBlockedError("all platforms are disabled; nothing scheduled")

    try:
        ev.verify_session(ctx.conn, story["session_date"])
        content = verify_artifacts(ctx, story)
        if content != story["approved_content_sha256"]:
            raise EvidenceError("artifacts differ from the approved version", code="APPROVED_CONTENT_CHANGED")
        sdir = story_dir(ctx, story)
        post_en = json.loads((sdir / "post_en.json").read_text(encoding="utf-8"))
        post_ja = json.loads((sdir / "post_ja.json").read_text(encoding="utf-8"))
        compliance.enforce([post_en, post_ja], story["session_date"])
        tts.verify(sdir, [post_en, post_ja])
        manifest = json.loads((sdir / "render_manifest.json").read_text(encoding="utf-8"))
        session = ctx.conn.execute("SELECT manifest_sha256 FROM sessions WHERE session_date = ?",
                                   (story["session_date"],)).fetchone()

        planned = []
        taken_by_platform: dict[str, set[str]] = {}
        for platform in enabled:
            adapter = get_adapter(platform, ctx.cfg)
            idem = idempotency_key(story_id, platform, story["approved_content_sha256"])
            taken = {r["publish_at_utc"] for r in ctx.conn.execute(
                "SELECT publish_at_utc FROM schedules WHERE platform = ? AND status = 'SCHEDULED'", (platform,))}
            taken |= taken_by_platform.setdefault(platform, set())
            slot = compute_slot(platform=platform, platform_cfg=ctx.cfg["platforms"][platform],
                                waves_cfg=ctx.cfg["waves"], session_date=story["session_date"], now=ctx.clock.now(),
                                taken_utc=taken, interval_minutes=int(ctx.cfg["schedule"]["slot_interval_minutes"]),
                                min_lead_minutes=int(ctx.cfg["schedule"]["min_lead_minutes"]))
            taken_by_platform[platform].add(slot.publish_at_utc)
            slot_info = {"wave": slot.wave, "publish_at_utc": slot.publish_at_utc, "publish_at_jst": slot.publish_at_jst,
                         "audience_tz": slot.audience_tz, "audience_local": slot.audience_local}
            bundle = post_bundle(story, platform, sdir, post_en, post_ja, manifest, content,
                                 session["manifest_sha256"], idem, slot_info)
            adapter.validate_credentials()
            adapter.validate_asset(bundle)
            written = adapter.schedule(bundle, slot.publish_at)
            planned.append({"platform": platform, "adapter": adapter.name, "idempotency_key": idem, **slot_info,
                            "payload_path": str(Path(written["payload_path"]).relative_to(ctx.paths.artifacts)),
                            "payload_sha256": written["payload_sha256"]})
        write_json_atomic(sdir / "schedule.json", {"schema": "auto_publish.schedule.v1", "story_id": story_id,
                                                   "release_gate": "R1", "dry_run": True, "entries": planned})
        now = iso_utc(ctx.clock.now())
        with transaction(ctx.conn):
            for p in planned:
                ctx.conn.execute(
                    "INSERT INTO schedules(story_id, platform, adapter, wave, publish_at_utc, publish_at_jst, audience_tz,"
                    " audience_local, status, idempotency_key, payload_path, payload_sha256, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?, 'SCHEDULED', ?,?,?,?)",
                    (story_id, p["platform"], p["adapter"], p["wave"], p["publish_at_utc"], p["publish_at_jst"],
                     p["audience_tz"], p["audience_local"], p["idempotency_key"], p["payload_path"],
                     p["payload_sha256"], now),
                )
            transition_story(ctx.conn, ctx.clock, story_id, S.APPROVED, S.SCHEDULED, actor=ctx.actor,
                             reason="dry-run schedule written", detail={"entries": planned})
    except StateConflictError:
        raise
    except ControlBlockedError:
        raise
    except Exception as exc:
        _fail(ctx, story, exc, "SCHEDULE")
        raise
    log("schedule.dry_run_written", story_id=story_id, platforms=[p["platform"] for p in planned])
    return {"story_id": story_id, "state": S.SCHEDULED.value, "schedules": planned, "noop": False}


def cancel(ctx: Ctx, story_id: str, reason: str) -> dict:
    story = _story(ctx, story_id)
    if story["state"] == S.CANCELLED.value:
        return {"story_id": story_id, "state": story["state"], "noop": True}
    with transaction(ctx.conn):
        n = ctx.conn.execute("UPDATE schedules SET status = 'CANCELLED' WHERE story_id = ? AND status = 'SCHEDULED'",
                             (story_id,)).rowcount
        transition_story(ctx.conn, ctx.clock, story_id, S(story["state"]), S.CANCELLED, actor=ctx.actor,
                         reason=reason or "cancelled", detail={"cancelled_schedules": n})
    return {"story_id": story_id, "state": S.CANCELLED.value, "cancelled_schedules": n, "noop": False}


def _non_retryable_names() -> set[str]:
    """NON_RETRYABLE classes and all their subclasses (e.g. NarrationLengthError)."""
    names, todo = set(), list(NON_RETRYABLE)
    while todo:
        c = todo.pop()
        if c.__name__ not in names:
            names.add(c.__name__)
            todo.extend(c.__subclasses__())
    return names


def retry(ctx: Ctx, story_id: str, reason: str, renderer=None) -> dict:
    controls.require_not_paused(ctx.conn, "retry")
    story = _story(ctx, story_id)
    if story["state"] != S.FAILED.value:
        raise ValidationError(f"{story_id} is {story['state']}; only FAILED stories can be retried", code="NOT_FAILED")
    err = json.loads(story["last_error"] or "{}")
    if err.get("type") in _non_retryable_names():
        raise ValidationError(
            f"{story_id} failed with {err.get('code')} ({err.get('type')}); this class of failure is fail-closed"
            " and cannot be retried -- fix the input and ingest a new session, or cancel", code="NOT_RETRYABLE")
    if story["attempts"] >= int(ctx.cfg["max_attempts"]):
        raise ValidationError(f"{story_id} has used {story['attempts']} attempts (max {ctx.cfg['max_attempts']})",
                              code="MAX_ATTEMPTS_EXCEEDED")
    target = S(story["failed_from_state"])
    with transaction(ctx.conn):
        ctx.conn.execute("UPDATE stories SET attempts = attempts + 1 WHERE story_id = ?", (story_id,))
        transition_story(ctx.conn, ctx.clock, story_id, S.FAILED, target, actor=ctx.actor,
                         reason=f"retry: {reason}", detail={"previous_error": err})
    if target == S.APPROVED:
        return schedule(ctx, story_id)
    return advance(ctx, story_id, renderer or FfmpegRenderer(ctx.cfg))
