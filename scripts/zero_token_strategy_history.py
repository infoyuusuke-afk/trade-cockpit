"""Cumulative, offline, private strategy research history across daily CSV rotation.

Store only immutable early-session research results and day/source hashes;
not the original confidential MS2 bars. No cloud inference, broker,
network, Excel, service installer or scheduled task.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import stat

from scripts.zero_token_strategy_lab import (
    JST, ResearchBlocked, analyze_trade_records, variants, replay_one_day,
)

SCHEMA = "zero_token_strategy_history_v1"
HISTORY_DB = "strategy_lab_history.sqlite3"

_SQL = """
CREATE TABLE IF NOT EXISTS evidence_days(
    day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    early_sha256 TEXT NOT NULL,
    source TEXT NOT NULL,
    cost_bps REAL NOT NULL,
    PRIMARY KEY(day,symbol)
);
CREATE TABLE IF NOT EXISTS evidence_trades(
    day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    PRIMARY KEY(day,symbol,strategy_id)
);
"""


def _compact_day_digest(rows: list[dict]) -> str:
    """Only the early-session input can influence these OR/VWAP candidates."""
    # Candidates enter through 10:30 and exit within 80x15s (<=10:50).
    early=[(r["time"].isoformat(),r["available_at"].isoformat(),
            r["open"],r["high"],r["low"],r["close"],r["volume"],
            r["source"]) for r in rows
           if r["time"].timetz().replace(tzinfo=None)<=time(11,0)]
    raw=json.dumps(early,sort_keys=True,separators=(",",":"),
                   ensure_ascii=False,allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _complete(rows: list[dict], *, now: datetime) -> bool:
    """Require afternoon evidence and a later clock; never finalize intraday."""
    if not rows:
        return False
    day=rows[0]["time"].date()
    if now.astimezone(JST).date()<day:
        return False
    if now.astimezone(JST).date()==day and now.astimezone(JST).time()<time(15,45):
        return False
    if rows[-1]["time"].timetz().replace(tzinfo=None)<time(15,20):
        return False
    return all(r["available_at"]<=now for r in rows)


def _read_history(path, cost, source):
    con=sqlite3.connect(str(path),timeout=2)
    try:
        observations=con.execute(
            "SELECT day,symbol,early_sha256,source,cost_bps FROM evidence_days"
            " ORDER BY day,symbol"
        ).fetchall()
        trades=con.execute(
            "SELECT day,symbol,strategy_id,raw_json,raw_sha256 FROM evidence_trades"
            " ORDER BY day,symbol,strategy_id"
        ).fetchall()
    finally:
        con.close()
    days=sorted({row[0] for row in observations})
    by_id=defaultdict(list)
    for day,symbol,digest,s,cost_bps in observations:
        if s!=source or cost_bps!=cost or len(digest)!=64:
            raise ResearchBlocked("HISTORY_SOURCE_OR_COST_MISMATCH")
    for day,symbol,strategy_id,payload,payload_hash in trades:
        if hashlib.sha256(payload.encode("utf-8")).hexdigest()!=payload_hash:
            raise ResearchBlocked("HISTORY_TRADE_TAMPERED")
        try:
            item=json.loads(payload)
            if (item["date"]!=day or item["symbol"]!=symbol
                    or item["strategy_id"]!=strategy_id
                    or item["source"]!=source
                    or item["real_submit_allowed"] is not False):
                raise ResearchBlocked("HISTORY_TRADE_INTEGRITY_FAILURE")
        except (ValueError,KeyError,TypeError) as exc:
            raise ResearchBlocked("HISTORY_TRADE_INTEGRITY_FAILURE") from exc
        by_id[strategy_id].append(item)
    digest_payload=json.dumps(
        {"days":observations,
         "trade_hashes":[(d,s,st,h) for d,s,st,_,h in trades]},
        sort_keys=True,separators=(",",":"),allow_nan=False
    ).encode("utf-8")
    fingerprint=hashlib.sha256(digest_payload).hexdigest()
    return by_id,days,fingerprint,len(observations),len(trades)


def append_and_analyze_history(out_dir, bars, *, base_cost_bps, now: datetime):
    """Append only complete source/symbol-days and score cumulative research.

    Crash-safe SQLite commits; replay is idempotent. Conflicting early
    historical source rows are rejected rather than silently reoptimized.
    The output remains purely statistical and not live trade eligible.
    """
    if (not isinstance(now,datetime) or now.tzinfo is None
            or now.utcoffset() is None):
        raise ResearchBlocked("CLOCK_UNVERIFIED")
    path=Path(out_dir)/HISTORY_DB
    if (path.exists() or path.is_symlink()):
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
            raise ResearchBlocked("HISTORY_PATH_UNSAFE")
    source={x["source"] for x in bars}
    if len(source)!=1:
        raise ResearchBlocked("MIXED_SYNTHETIC_REAL_INPUT")
    source=next(iter(source))
    grouped=defaultdict(list)
    for r in bars:
        grouped[(r["date"],r["symbol"])].append(r)
    # Only finalized source/symbol-days enter research. This avoids rewriting
    # the day's historical "truth" as a live CSV appends new bars.
    completed={}
    for k,rs in grouped.items():
        rs.sort(key=lambda x:x["time"])
        if _complete(rs,now=now):
            completed[k]=(rs,_compact_day_digest(rs))
    con=sqlite3.connect(str(path),timeout=3,isolation_level=None)
    try:
        con.execute("PRAGMA busy_timeout=3000")
        con.execute("PRAGMA synchronous=FULL")
        con.executescript(_SQL)
        con.execute("BEGIN IMMEDIATE")
        already=con.execute("SELECT DISTINCT source,cost_bps FROM evidence_days").fetchall()
        if already and (len(already)!=1 or already[0]!=(source,base_cost_bps)):
            raise ResearchBlocked("HISTORY_SOURCE_OR_COST_MISMATCH")
        added_days=added_trades=0
        for (day,symbol),(rs,day_sha) in sorted(completed.items()):
            old=con.execute("SELECT early_sha256 FROM evidence_days WHERE day=? AND symbol=?",
                            (day,symbol)).fetchone()
            if old is not None:
                if old[0]!=day_sha:
                    raise ResearchBlocked("HISTORICAL_BAR_REVISION_CONFLICT")
                continue
            con.execute(
                "INSERT INTO evidence_days VALUES (?,?,?,?,?)",
                (day,symbol,day_sha,source,base_cost_bps)
            )
            added_days+=1
            for v in variants():
                trade=replay_one_day(rs,v,cost_bps=base_cost_bps)
                if trade is None:
                    continue
                raw=json.dumps(trade,sort_keys=True,separators=(",",":"),
                               ensure_ascii=False,allow_nan=False)
                digest=hashlib.sha256(raw.encode("utf-8")).hexdigest()
                con.execute(
                    "INSERT INTO evidence_trades VALUES (?,?,?,?,?)",
                    (day,symbol,v["id"],raw,digest)
                )
                added_trades+=1
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    # New connection: independent persisted readback, not a synthetic ACK
    # from a market-source provider. Source names remain untrusted claims.
    by_id,days,fingerprint,source_days,trade_count=_read_history(path,base_cost_bps,source)
    result=analyze_trade_records(
        by_id,days,input_sha256=fingerprint,source=source,
        base_cost_bps=base_cost_bps,
    )
    result["cumulative_history"]={
        "schema_version":SCHEMA,
        "completed_symbol_days":source_days,
        "recorded_trade_candidates":trade_count,
        "newly_finalized_symbol_days":added_days,
        "new_replayed_trades":added_trades,
        "private_history_sha256":fingerprint,
        "market_source_authenticated":False,
        "real_submit_allowed":False,
    }
    return result
