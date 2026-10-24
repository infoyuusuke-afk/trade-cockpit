"""Read-only input bridge from Issue #282 (the coordination ledger) for the three specialists.

PROJECT_ITEM_ID: P0-100B-THREE-ANALYST-BRAIN-BIDIRECTIONAL-20261022 (Phase 1)

Input: the issue's comments as fetched by the operator, e.g.
  gh api --paginate "repos/<owner>/<repo>/issues/282/comments?per_page=100" > comments.json
(a JSON array, or one JSON object per line). This module never calls the
network, never writes to GitHub and never posts on anyone's behalf.

From each comment it reads only the public audit metadata of a
``[100B_COORD_V1]`` / ``[100B_REPORT_DELIVERY_V1]`` block (``key: value`` lines):
message_id, event_type, source_role, recipient_role, project_item_id,
in_reply_to, state and the comment URL/time. REPORTs from, and ACKs to,
pre_next, supply_sq (alias supply_demand_analyst) and revenue_hunter are stored
once per message_id in a private SQLite file with the fetch time. Bodies are not
stored; values that are not in the comment stay absent, never filled in.

The return direction to the ChatGPT scheduled tasks has no authorized write
path here, so it is reported as HANDOFF_PENDING, never as delivered.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys

MARKERS = ("[100B_COORD_V1]", "[100B_REPORT_DELIVERY_V1]")
ROLES = {"pre_next": "pre_next", "supply_sq": "supply_sq", "supply_demand_analyst": "supply_sq",
         "revenue_hunter": "revenue_hunter"}
FIELDS = ("message_id", "event_type", "source_role", "recipient_role", "project_item_id", "in_reply_to", "state")
LINE = re.compile(r"^([a-z_]+):\s*(.+?)\s*$")
MESSAGE_ID = re.compile(r"^[A-Za-z0-9_.:-]{3,160}$")


def parse_block(body: str) -> dict | None:
    if not isinstance(body, str) or not any(m in body for m in MARKERS):
        return None
    out = {}
    for line in body.splitlines():
        m = LINE.match(line.strip())
        if m and m.group(1) in FIELDS and m.group(1) not in out:
            out[m.group(1)] = m.group(2)[:200]
    if not MESSAGE_ID.fullmatch(out.get("message_id", "")) or not out.get("event_type"):
        return None
    return out


def relevant(meta: dict) -> tuple[str, str] | None:
    """(role, direction) for a REPORT from a specialist or an ACK to one."""
    event = meta.get("event_type", "")
    src = ROLES.get(meta.get("source_role", ""))
    rcpt = [ROLES[r.strip()] for r in meta.get("recipient_role", "").split(",") if r.strip() in ROLES]
    if event.startswith("REPORT") and src:
        return src, "REPORT_FROM_SPECIALIST"
    if event.startswith("ACK") and rcpt:
        return rcpt[0], "ACK_TO_SPECIALIST"
    if event.startswith("ACK") and src:
        return src, "ACK_FROM_SPECIALIST"
    return None


def load_comments(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except ValueError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=10, isolation_level=None)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS coord_messages ("
        " message_id TEXT PRIMARY KEY, role TEXT NOT NULL, direction TEXT NOT NULL, event_type TEXT NOT NULL,"
        " comment_id INTEGER NOT NULL, comment_url TEXT, created_at TEXT NOT NULL, fetched_at TEXT NOT NULL,"
        " source_role TEXT, recipient_role TEXT, project_item_id TEXT, in_reply_to TEXT, state TEXT)")
    return conn


def ingest(comments: list[dict], db: Path, *, fetched_at: datetime) -> dict:
    """Store new relevant messages once; a repeated message_id is counted, never stored twice."""
    new, duplicate = 0, 0
    with closing(_connect(db)) as conn:
        for c in comments:
            meta = parse_block(c.get("body", ""))
            hit = relevant(meta) if meta else None
            if not hit:
                continue
            if conn.execute("SELECT 1 FROM coord_messages WHERE message_id = ?", (meta["message_id"],)).fetchone():
                duplicate += 1
                continue
            conn.execute(
                "INSERT INTO coord_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (meta["message_id"], hit[0], hit[1], meta["event_type"], int(c.get("id") or 0),
                 c.get("html_url") or "", str(c.get("created_at") or ""), fetched_at.astimezone(timezone.utc).isoformat(),
                 meta.get("source_role"), meta.get("recipient_role"), meta.get("project_item_id"),
                 meta.get("in_reply_to"), meta.get("state")))
            new += 1
    return {"new": new, "duplicate": duplicate, "status": status(db)}


def status(db: Path) -> dict:
    """Per role: the latest REPORT, whether an ACK answered it, and the return direction."""
    out = {}
    with closing(_connect(db)) as conn:
        for role in sorted(set(ROLES.values())):
            rep = conn.execute("SELECT message_id, created_at, state FROM coord_messages WHERE role = ? AND"
                               " direction = 'REPORT_FROM_SPECIALIST' ORDER BY created_at DESC LIMIT 1", (role,)).fetchone()
            ack = None
            if rep:
                ack = conn.execute("SELECT message_id, created_at FROM coord_messages WHERE direction = 'ACK_TO_SPECIALIST'"
                                   " AND in_reply_to = ?", (rep[0],)).fetchone()
            out[role] = {
                "latest_report": rep[0] if rep else None,
                "latest_report_at": rep[1] if rep else None,
                "latest_report_state": rep[2] if rep else None,
                "coordinator_ack": ack[0] if ack else None,
                "report_direction": "READ_VERIFIED" if rep else "NO_REPORT_SEEN",
                # No authorized write path to the ChatGPT scheduled tasks exists here.
                "return_direction": "HANDOFF_PENDING",
            }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only Issue #282 specialist REPORT/ACK ingest (no network)")
    ap.add_argument("--comments-json", required=True, type=Path)
    ap.add_argument("--db", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        got = ingest(load_comments(args.comments_json), args.db, fetched_at=datetime.now(timezone.utc))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"state": "BLOCKED", "reason": type(exc).__name__, "real_submit_allowed": False}))
        return 2
    print(json.dumps(dict(got, real_submit_allowed=False), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
