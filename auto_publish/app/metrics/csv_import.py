"""Read-only importer for owner-exported post metrics (CSV contract v1).

The raw CSV is never modified: it is read once as bytes, hashed, copied into a
read-only content-addressed store (``metrics_store/``) and parsed from those
bytes. Importing the same file again is a no-op. The whole file is validated
before anything is written; any error rejects the entire import (fail-closed).

Point-in-time: a row's ``known_at_utc`` is the time it was first imported. A
later snapshot of the same post (later ``observed_at``) is appended as a new row;
the same (post, observed_at) with different numbers is a conflict and is refused,
so past knowledge can never be rewritten by a later file.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from .. import audit
from ..clock import iso_utc, parse_aware
from ..context import Ctx
from ..db import transaction
from ..errors import ValidationError
from ..evidence.store import store_copy
from ..hashing import sha256_bytes, sha256_json

CONTRACT = "auto_publish.post_metrics_csv.v1"
HEADER = ("platform", "post_ref", "story_id", "published_at", "observed_at", "impressions", "views",
          "watch_time_seconds", "completion_rate", "likes", "comments", "shares", "saves", "follows_gained",
          "video_duration_seconds")
INT_COLS = ("impressions", "views", "watch_time_seconds", "likes", "comments", "shares", "saves", "follows_gained")
METRIC_COLS = INT_COLS + ("completion_rate", "video_duration_seconds")
PLATFORMS = ("youtube_shorts", "tiktok", "x")
POST_REF = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")
STORY_ID = re.compile(r"^st_[0-9a-f]{16}$")
INT = re.compile(r"^\d{1,15}$")
DEC = re.compile(r"^\d{1,9}(\.\d{1,9})?$")
MAX_ROWS = 100_000
MAX_ERRORS = 25


class MetricsError(ValidationError):
    code = "METRICS_CSV_INVALID"


def _ts(value: str, field: str, errs: list, n: int) -> datetime | None:
    try:
        return parse_aware(value)
    except (ValueError, TypeError) as exc:
        errs.append({"row": n, "field": field, "error": f"timestamp with timezone required ({exc})"})
        return None


def parse_rows(text: str, platform: str, now: datetime) -> list[dict]:
    """Validate and normalise every row. Raises MetricsError listing the problems."""
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows or tuple(h.strip() for h in rows[0]) != HEADER:
        raise MetricsError("CSV header does not match the contract", code="METRICS_CSV_HEADER",
                           details={"expected": list(HEADER), "got": rows[0] if rows else None})
    body = [r for r in rows[1:] if any(c.strip() for c in r)]
    if not body:
        raise MetricsError("CSV has no data rows", code="METRICS_CSV_EMPTY")
    if len(body) > MAX_ROWS:
        raise MetricsError(f"CSV has more than {MAX_ROWS} rows", code="METRICS_CSV_TOO_LARGE")
    errs: list[dict] = []
    out: list[dict] = []
    for n, raw in enumerate(body, start=2):
        if len(raw) != len(HEADER):
            errs.append({"row": n, "error": f"expected {len(HEADER)} columns, got {len(raw)}"})
            continue
        r = {k: v.strip() for k, v in zip(HEADER, raw)}
        if r["platform"] != platform:
            errs.append({"row": n, "field": "platform", "error": f"{r['platform']!r} != --platform {platform!r}",
                         "code": "PLATFORM_MISMATCH"})
        if not POST_REF.match(r["post_ref"]):
            errs.append({"row": n, "field": "post_ref", "error": "malformed"})
        if r["story_id"] and not STORY_ID.match(r["story_id"]):
            errs.append({"row": n, "field": "story_id", "error": "malformed"})
        pub = _ts(r["published_at"], "published_at", errs, n)
        obs = _ts(r["observed_at"], "observed_at", errs, n)
        if pub and obs:
            if obs < pub:
                errs.append({"row": n, "error": "observed_at is before published_at"})
            if pub > now or obs > now:
                errs.append({"row": n, "error": "timestamp is in the future", "code": "FUTURE_TIMESTAMP"})
        vals: dict = {}
        for c in INT_COLS:
            if r[c] == "":
                vals[c] = None
            elif INT.match(r[c]):
                vals[c] = int(r[c])
            else:
                errs.append({"row": n, "field": c, "error": f"non-negative integer required, got {r[c]!r}"})
        for c in ("completion_rate", "video_duration_seconds"):
            if r[c] == "":
                vals[c] = None
            elif DEC.match(r[c]):
                vals[c] = float(r[c])
            else:
                errs.append({"row": n, "field": c, "error": f"non-negative decimal required, got {r[c]!r}"})
        if vals.get("completion_rate") is not None and not 0.0 <= vals["completion_rate"] <= 1.0:
            errs.append({"row": n, "field": "completion_rate", "error": "must be within 0..1"})
        if vals.get("video_duration_seconds") == 0.0:
            errs.append({"row": n, "field": "video_duration_seconds", "error": "must be > 0 when given"})
        if vals.get("views") is None and vals.get("impressions") is None:
            errs.append({"row": n, "error": "views or impressions is required"})
        if None not in (vals.get("views"), vals.get("impressions")) and vals["views"] > vals["impressions"]:
            errs.append({"row": n, "error": "views > impressions", "code": "INCONSISTENT"})
        if len(errs) >= MAX_ERRORS:
            break
        if pub and obs:
            out.append({"platform": platform, "post_ref": r["post_ref"], "story_id": r["story_id"] or None,
                        "published_at_utc": iso_utc(pub), "observed_at_utc": iso_utc(obs), **vals, "_row": n})
    if errs:
        raise MetricsError(f"{len(errs)} invalid row(s); nothing imported", details={"errors": errs[:MAX_ERRORS]})
    return out


def _key(r: dict) -> tuple:
    return (r["platform"], r["post_ref"], r["observed_at_utc"])


def _values(r: dict) -> dict:
    return {k: r[k] for k in ("story_id", "published_at_utc", *METRIC_COLS)}


def import_csv(ctx: Ctx, platform: str, path: str | Path, actor: str | None = None) -> dict:
    if platform not in PLATFORMS:
        raise MetricsError(f"unknown platform {platform!r}", code="PLATFORM_UNKNOWN")
    src = Path(path)
    data = src.read_bytes()                                   # the raw file is only ever read
    sha = sha256_bytes(data)
    prev = ctx.conn.execute("SELECT import_id FROM metrics_imports WHERE platform=? AND sha256=?",
                            (platform, sha)).fetchone()
    if prev:
        return {"import_id": prev["import_id"], "sha256": sha, "noop": True}
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MetricsError(f"CSV is not UTF-8: {exc}", code="METRICS_CSV_ENCODING") from exc
    now = ctx.clock.now()
    rows = parse_rows(text, platform, now)

    # duplicates / conflicts inside the file
    errs, seen, new = [], {}, []
    for r in rows:
        k = _key(r)
        if k in seen:
            if _values(seen[k]) != _values(r):
                errs.append({"row": r["_row"], "error": f"conflicting duplicate of row {seen[k]['_row']}",
                             "code": "DUPLICATE_CONFLICT"})
            continue
        seen[k] = r
    posts: dict[str, dict] = {}
    for r in seen.values():
        p = posts.setdefault(r["post_ref"], r)
        if (p["published_at_utc"], p["story_id"]) != (r["published_at_utc"], r["story_id"]):
            errs.append({"row": r["_row"], "error": f"post {r['post_ref']} has inconsistent published_at/story_id",
                         "code": "INCONSISTENT"})
    # against what is already known
    dup = 0
    for k, r in seen.items():
        known = ctx.conn.execute("SELECT * FROM post_metrics WHERE platform=? AND post_ref=? AND observed_at_utc=?",
                                 k).fetchone()
        if known is not None:
            if {c: known[c] for c in _values(r)} != _values(r):
                errs.append({"row": r["_row"], "error": "differs from the already-imported observation",
                             "code": "METRICS_CONFLICT"})
            dup += 1
            continue
        other = ctx.conn.execute("SELECT published_at_utc, story_id FROM post_metrics WHERE platform=? AND post_ref=?"
                                 " LIMIT 1", (platform, r["post_ref"])).fetchone()
        if other is not None and (other["published_at_utc"], other["story_id"]) != (r["published_at_utc"],
                                                                                    r["story_id"]):
            errs.append({"row": r["_row"], "error": "published_at/story_id differ from earlier imports",
                         "code": "INCONSISTENT"})
        new.append(r)
    dup += len(rows) - len(seen)
    if errs:
        codes = {e.get("code") for e in errs}
        code = "METRICS_CONFLICT" if "METRICS_CONFLICT" in codes else (
            "DUPLICATE_CONFLICT" if "DUPLICATE_CONFLICT" in codes else "METRICS_CSV_INVALID")
        raise MetricsError(f"{len(errs)} conflicting row(s); nothing imported", code=code,
                           details={"errors": errs[:MAX_ERRORS]})

    stored = store_copy(src, ctx.paths.home / "metrics_store", sha)
    if stored.read_bytes() != data:
        raise MetricsError("raw CSV changed while importing", code="METRICS_CSV_CHANGED")
    now_s = iso_utc(now)
    with transaction(ctx.conn):
        cur = ctx.conn.execute(
            "INSERT INTO metrics_imports(platform, source_name, sha256, size_bytes, contract, rows_total, rows_new,"
            " rows_duplicate, store_path, imported_at_utc, imported_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (platform, src.name, sha, len(data), CONTRACT, len(rows), len(new), dup, str(stored), now_s,
             actor or ctx.actor))
        import_id = cur.lastrowid
        for r in sorted(new, key=_key):
            body = {k: r[k] for k in ("platform", "post_ref", "observed_at_utc", *_values(r))}
            ctx.conn.execute(
                "INSERT INTO post_metrics(import_id, platform, post_ref, story_id, published_at_utc, observed_at_utc,"
                f" known_at_utc, {', '.join(METRIC_COLS)}, row_sha256)"
                f" VALUES ({', '.join('?' * (8 + len(METRIC_COLS)))})",
                (import_id, platform, r["post_ref"], r["story_id"], r["published_at_utc"], r["observed_at_utc"], now_s,
                 *[r[c] for c in METRIC_COLS], sha256_json(body)))
        audit.append(ctx.conn, ctx.clock, actor=actor or ctx.actor, entity_type="metrics_import",
                     entity_id=str(import_id), action="import", to_state="IMPORTED",
                     detail={"platform": platform, "sha256": sha, "contract": CONTRACT, "rows_total": len(rows),
                             "rows_new": len(new), "rows_duplicate": dup})
    return {"import_id": import_id, "sha256": sha, "rows_total": len(rows), "rows_new": len(new),
            "rows_duplicate": dup, "noop": False}


def verify_imports(ctx: Ctx, import_ids: list[int]) -> None:
    """Re-hash the stored raw CSVs behind a dataset (fail-closed)."""
    from ..hashing import sha256_file
    for iid in sorted(set(import_ids)):
        row = ctx.conn.execute("SELECT store_path, sha256 FROM metrics_imports WHERE import_id=?", (iid,)).fetchone()
        p = Path(row["store_path"]) if row else None
        if p is None or not p.is_file() or sha256_file(p) != row["sha256"]:
            raise MetricsError(f"stored metrics CSV for import {iid} is missing or changed",
                               code="METRICS_STORE_TAMPERED", details={"import_id": iid})
