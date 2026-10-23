#!/usr/bin/env python3
"""24h-capable local research daemon: zero LLM API tokens, NO auto-orders.

Explicit user start is required. Default is --once; --daemon is opt-in.
No broker, no network, no API-key access, no Excel/COM, no main/V10 write.
Only private input CSV (confirmed 15s bars) and private research output.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import sys
import time
from uuid import uuid4

from scripts.zero_token_strategy_lab import (
    MAX_INPUT_BYTES, MIN_ROUND_TRIP_COST_BPS, ResearchBlocked,
    load_bars_bytes,
)
from scripts.zero_token_strategy_history import append_and_analyze_history

REPORT = "strategy_lab_latest.json"
LEDGER = "strategy_lab_runs.sqlite3"
SCHEMA_VERSION = "zero_token_strategy_worker_v1"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _check_private(path, *, directory=False):
    """Refuse repo content, symlink ancestors, shared POSIX data directory."""
    p = Path(path)
    if not p.is_absolute() or ".." in p.parts:
        raise ResearchBlocked("PRIVATE_ABSOLUTE_PATH_REQUIRED")
    if not p.parent.is_dir():
        raise ResearchBlocked("PRIVATE_PARENT_MISSING")
    full = p.resolve(strict=False)
    if REPO_ROOT == full or REPO_ROOT in full.parents:
        raise ResearchBlocked("PUBLIC_REPO_PATH_FORBIDDEN")
    # Reject links and Windows reparse-point redirects; no checkout data.
    for part in (p, *p.parents):
        if part.exists() or part.is_symlink():
            inf = part.lstat()
            if stat.S_ISLNK(inf.st_mode) or (getattr(inf,"st_file_attributes",0) & 0x400):
                raise ResearchBlocked("SYMLINK_PATH_FORBIDDEN")
    if directory:
        if not p.is_dir():
            raise ResearchBlocked("OUTPUT_DIRECTORY_REQUIRED")
        if os.name != "nt" and p.stat().st_mode & 0o077:
            raise ResearchBlocked("PRIVATE_DIRECTORY_PERMISSIONS_UNSAFE")
    else:
        if not p.is_file():
            raise ResearchBlocked("INPUT_NOT_REGULAR_FILE")
        inf = p.lstat()
        if inf.st_nlink != 1:
            raise ResearchBlocked("HARDLINK_INPUT_FORBIDDEN")
    return p


def _read_unchanged(path: Path) -> bytes:
    before = path.stat()
    if not 0 < before.st_size <= MAX_INPUT_BYTES:
        raise ResearchBlocked("INPUT_SIZE_INVALID")
    with path.open("rb") as f:
        raw = f.read(MAX_INPUT_BYTES+1)
        opened = os.fstat(f.fileno())
    after = path.stat()
    identity = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink)
    if len(raw)!=before.st_size or identity(before)!=identity(opened) or identity(before)!=identity(after):
        raise ResearchBlocked("INPUT_CHANGED_DURING_READ")
    return raw


def _persist_atomic(folder: Path, name: str, obj: dict) -> str:
    raw=(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                    separators=(",",":"), allow_nan=False)+"\n").encode("utf-8")
    sha=hashlib.sha256(raw).hexdigest()
    dst=folder/name
    if dst.exists() and (dst.is_symlink() or not dst.is_file() or dst.stat().st_nlink != 1):
        raise ResearchBlocked("OUTPUT_FILE_UNSAFE")
    temp=folder/("."+name+"."+uuid4().hex+".tmp")
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd=os.open(str(temp),flags,0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp,dst)
    finally:
        if temp.exists():
            temp.unlink()
    # Fresh readback detects truncated/failed rename. This is not
    # authentication of the original market source.
    if hashlib.sha256(dst.read_bytes()).hexdigest()!=sha:
        raise ResearchBlocked("OUTPUT_READBACK_MISMATCH")
    return sha


def run_once(input_path, output_dir, *, base_cost_bps=18.0, clock=None) -> dict:
    """Skip unchanged datasets; exclusive local SQLite research journal."""
    if clock is None:
        clock=lambda:datetime.now(timezone.utc)
    if not isinstance(base_cost_bps,(int,float)) or base_cost_bps < MIN_ROUND_TRIP_COST_BPS:
        raise ResearchBlocked("COST_ASSUMPTION_TOO_LOW")
    out=_check_private(output_dir,directory=True)
    inp=Path(input_path)
    if not inp.exists():
        return {"state":"DATA_UNAVAILABLE","reason":"INPUT_CSV_MISSING",
                "llm_api_tokens_used":0,"real_submit_allowed":False}
    inp=_check_private(inp)
    if inp.parent==out and inp.name in (REPORT,LEDGER):
        raise ResearchBlocked("INPUT_IS_WORKER_OUTPUT")
    raw=_read_unchanged(inp)
    bars,fingerprint=load_bars_bytes(raw)
    ledger=out/LEDGER
    if ledger.exists() and (ledger.is_symlink() or not ledger.is_file() or ledger.stat().st_nlink != 1):
        raise ResearchBlocked("LEDGER_PATH_UNSAFE")
    con=sqlite3.connect(str(ledger),timeout=2,isolation_level=None)
    try:
        con.execute("PRAGMA busy_timeout=2000")
        con.execute("PRAGMA synchronous=FULL")
        con.execute(
            "CREATE TABLE IF NOT EXISTS runs("
            " input_sha256 TEXT NOT NULL, cost_bps REAL NOT NULL,"
            " report_sha256 TEXT NOT NULL, completed_at TEXT NOT NULL,"
            " PRIMARY KEY(input_sha256,cost_bps))"
        )
        con.execute("BEGIN IMMEDIATE")
        existing=con.execute(
            "SELECT report_sha256 FROM runs WHERE input_sha256=? AND cost_bps=?",
            (fingerprint,base_cost_bps),
        ).fetchone()
        if existing:
            con.execute("COMMIT")
            return {"state":"UNCHANGED_NO_NEW_ANALYSIS","input_sha256":fingerprint,
                    "llm_api_tokens_used":0,"real_submit_allowed":False}
        when=clock()
        if not isinstance(when,datetime) or when.tzinfo is None or when.utcoffset() is None:
            raise ResearchBlocked("LOCAL_CLOCK_INVALID")
        analysis=append_and_analyze_history(
            out,bars,base_cost_bps=base_cost_bps,now=when
        )
        pending=analysis["cumulative_history"]["pending_symbol_days"]
        report={
            "worker_schema":SCHEMA_VERSION,
            "completed_at_utc":when.astimezone(timezone.utc).isoformat(),
            "analysis":analysis,
            "input_is_private":True,
            "llm_api_tokens_used":0,
            "real_submit_allowed":False,
            "broker_connected":False,
            "paid_api_connected":False,
            "automatic_order_execution":False,
        }
        output_sha=_persist_atomic(out,REPORT,report)
        # Do not mark a CSV as exhausted while a session remains incomplete.
        # A stationary intraday input can become finalizable after 15:45 JST.
        # Re-analysis on the next poll is idempotent in the history DB.
        if pending==0:
            con.execute(
                "INSERT INTO runs VALUES(?,?,?,?)",
                (fingerprint,base_cost_bps,output_sha,report["completed_at_utc"])
            )
        con.execute("COMMIT")
        if pending==0:
            verified=con.execute(
                "SELECT report_sha256 FROM runs WHERE input_sha256=? AND cost_bps=?",
                (fingerprint,base_cost_bps),
            ).fetchone()
            if not verified or verified[0]!=output_sha:
                raise ResearchBlocked("LEDGER_READBACK_FAILED")
        return {"state":"RESEARCH_RECORDED","analysis_status":analysis["status"],
                "observed_days":analysis["observed_days"],
                "pending_symbol_days":pending,
                "candidate":((analysis.get("best_research_candidate") or {}).get("strategy") or {}).get("id"),
                "input_sha256":fingerprint,"report_sha256":output_sha,
                "llm_api_tokens_used":0,"real_submit_allowed":False}
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def main(argv=None):
    ap=argparse.ArgumentParser(description="24-hour local, zero-LLM-token strategy research. OFF by default.")
    ap.add_argument("--input",required=True,help="Absolute path to *private* confirmed 15-second bar CSV")
    ap.add_argument("--output-dir",required=True,help="Existing private directory OUTSIDE public repository")
    mode=ap.add_mutually_exclusive_group()
    mode.add_argument("--once",action="store_true",help="Run one pass (default)")
    mode.add_argument("--daemon",action="store_true",help="Run continuously until terminated")
    ap.add_argument("--poll-seconds",type=int,default=900)
    ap.add_argument("--roundtrip-cost-bps",type=float,default=18.0)
    args=ap.parse_args(argv)
    if args.daemon and not 300<=args.poll_seconds<=86400:
        ap.error("--poll-seconds must be between 300 and 86400")
    if not args.daemon and args.poll_seconds!=900:
        ap.error("--poll-seconds is valid only with --daemon")
    if args.roundtrip_cost_bps < MIN_ROUND_TRIP_COST_BPS:
        ap.error("roundtrip cost assumption < 10 bps is prohibited")
    while True:
        try:
            result=run_once(args.input,args.output_dir,
                            base_cost_bps=args.roundtrip_cost_bps)
            print(json.dumps(result,ensure_ascii=False,sort_keys=True),flush=True)
        except (ResearchBlocked,OSError,sqlite3.DatabaseError) as exc:
            print(json.dumps({"state":"BLOCKED","reason":str(exc),
                "llm_api_tokens_used":0,"real_submit_allowed":False},
                ensure_ascii=False),flush=True)
            if not args.daemon:
                return 2
        if not args.daemon:
            return 0
        try:
            time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            return 0


if __name__=="__main__":
    sys.exit(main())
