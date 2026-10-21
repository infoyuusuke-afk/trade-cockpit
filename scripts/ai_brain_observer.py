"""V10 independent local BRAIN observation engine (read-only, NO orders).

Consumes only the Controller's private live_ms2.json. Produces an isolated
local status file with coarse OR15/VWAP watch observations, not tradable
signals or verified profitability. Collector publication time is NOT a
verified exchange tick time.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import types

SCHEMA = "ai-brain-observer-1"
SOURCE = "MarketSpeed II RSS / local PC"
WORKBOOK = "Kioxia_MS2_RSS_Live_Signals.xlsx"
MAX_INPUT_BYTES = 8_000_000
MAX_AGE_SECONDS = 60
ALLOWED = {"OR15_ABOVE_VWAP_WATCH", "OR15_BELOW_VWAP_WATCH"}
MAX_OBSERVATIONS = 5

# Opt-in Agents SDK research receiver (P0-AGENTS-SDK-V10-BRAIN-INTEGRATION-20261021).
# Off unless the OWNER sets V10_AGENT_RESEARCH_INBOX (absolute private folder)
# plus both HMAC keys. When off, nothing below is imported or run and this
# observer behaves exactly as before. When on, the three modules are loaded
# only from bytes whose git blob SHA-1 equals the pins below (this file is
# itself pinned in the V10 release manifest), then the receiver runs in this
# process at most every 30 s. It writes only to the private inbox, never to the
# observer status, live data, Excel or any order path.
AGENT_INBOX_ENV = "V10_AGENT_RESEARCH_INBOX"
AGENT_RECEIVER_INTERVAL = timedelta(seconds=30)
AGENT_HOST_COMPONENT = "v10-ai-brain-observer"
AGENT_PACKAGE = "v10_pinned_agent"
AGENT_RECEIVER_MODULES = (
    ("agent_sdk_coordination_pilot", "c3423423cbe2742876f41e1aab9413a701d8991e"),
    ("agent_sdk_brain_handoff", "b936f22ecb086fa56d4fad3361f0fce87c03be35"),
    ("v10_brain_agent_research_receiver", "5269ad6bb8f048b4ff45b35ac2535c9612693614"),
)
AGENT_KNOWN_REASONS = ("PRIVATE_", "RECEIVER_", "INBOX_", "HANDOFF_", "STORED_ACK", "AGENT_RECEIVER_")

# Backtest expected value of the cockpit's own recorded signals (OWNER
# 2026-10-21). Rebuilt from RuntimeDir/records once per JST day after the close
# (or when missing) into RuntimeDir/signal_ev_table_v1.json, which the Gateway
# serves read-only for the REALTIME 5 ranking. The module is loaded only from
# bytes whose git blob equals the pin. It never touches live data or orders.
SIGNAL_EV_MODULE = ("v10_signal_ev_table", "7d613b60531a5b37db0802f76a2b942aca0ad77d")
SIGNAL_EV_FILE = "signal_ev_table_v1.json"
SIGNAL_EV_REBUILD_AFTER_JST = (15, 35)
# Night PTS -> next-morning watch candidates, rebuilt every 5 minutes from the
# Collector's PTS records into RuntimeDir/pts_pickup_v1.json (pinned module).
PTS_PICKUP_MODULE = ("v10_pts_pickup", "06fffac84925e5b66d2ec346eee387fc25d1ae3e")
PTS_PICKUP_FILE = "pts_pickup_v1.json"
PTS_PICKUP_INTERVAL = timedelta(minutes=5)
# Brain core (OWNER 2026-10-21 「全部やりたい」): every pass, score the lit live
# signals with the EV table and the rule Shadow, write the top picks to
# RuntimeDir/brain_pick_v1.json for the Gateway and log new picks to
# records/<day>/brain_picks.csv for the rule Shadow (pinned module, no orders).
BRAIN_CORE_MODULE = ("v10_brain_core", "eb6d6bb7b88451f8c74d48f8c1ea49c139dc18f9")


def _aware(value):
    if not isinstance(value, str) or not value:
        raise ValueError("TIMESTAMP_MISSING")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("TIMESTAMP_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("TIMESTAMP_TZ_MISSING")
    return result.astimezone(timezone.utc)


def _number(value):
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _safe_symbol(value):
    if not isinstance(value, str) or not (3 <= len(value) <= 20):
        return False
    return all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ.T" for c in value)


def analyze(snapshot, *, now, file_modified_at):
    """Strict data-quality gate plus deterministic informational observations."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("DECISION_TIME_WITHOUT_TZ")
    reasons = []
    if not isinstance(snapshot, dict):
        reasons.append("INPUT_NOT_OBJECT")
        snapshot = {}
    if snapshot.get("schema_version") != "ms2-common-1.0":
        reasons.append("WRONG_INPUT_SCHEMA")
    if snapshot.get("source") != SOURCE or snapshot.get("source_mode") != "MS2_RSS_WORKBOOK":
        reasons.append("SOURCE_IDENTITY_UNVERIFIED")
    if snapshot.get("real_submit_allowed") is not False:
        reasons.append("REAL_ORDER_FLAG_UNSAFE")
    if snapshot.get("data_conflict") is not False or snapshot.get("stale") is not False:
        reasons.append("DATA_CONFLICT_OR_STALE")
    if snapshot.get("live_values_available") is not True or snapshot.get("price_source_status") != "OK":
        reasons.append("PRICE_SOURCE_UNVERIFIED")
    if snapshot.get("timestamp_timezone") != "Asia/Tokyo":
        reasons.append("PUBLICATION_TIMEZONE_UNVERIFIED")
    publication_at = None
    try:
        publication_at = _aware(snapshot.get("observed_at_offset"))
        if publication_at.utcoffset() != timezone.utc.utcoffset(publication_at):
            raise ValueError("PUBLICATION_TIMESTAMP_ERROR")
        age = (now.astimezone(timezone.utc) - publication_at).total_seconds()
        if age < -1 or age > MAX_AGE_SECONDS:
            reasons.append("PUBLICATION_STALE_OR_FUTURE")
        # Offset of the original string, not the normalized UTC timestamp.
        original = datetime.fromisoformat(snapshot["observed_at_offset"].replace("Z", "+00:00"))
        if original.utcoffset().total_seconds() != 9 * 3600:
            reasons.append("PUBLICATION_JST_OFFSET_INVALID")
    except ValueError:
        reasons.append("PUBLICATION_TIMESTAMP_INVALID")
    if file_modified_at is None or file_modified_at.tzinfo is None or file_modified_at.utcoffset() is None:
        reasons.append("INPUT_FILE_TIME_UNVERIFIED")
    else:
        age = (now.astimezone(timezone.utc) - file_modified_at.astimezone(timezone.utc)).total_seconds()
        if age < -1 or age > MAX_AGE_SECONDS:
            reasons.append("INPUT_FILE_STALE_OR_FUTURE")
    diag = snapshot.get("live_price_diagnostics")
    if not isinstance(diag, dict):
        reasons.append("DIAGNOSTICS_MISSING")
    else:
        if diag.get("workbook_name") != WORKBOOK or diag.get("workbook_identity_verified") is not True:
            reasons.append("WORKBOOK_IDENTITY_UNVERIFIED")
        if diag.get("source_mode") != "MS2_RSS_WORKBOOK" or diag.get("price_source_status") != "OK":
            reasons.append("DIAGNOSTICS_SOURCE_UNVERIFIED")
        if diag.get("data_conflict") is not False or diag.get("live_values_available") is not True:
            reasons.append("DIAGNOSTICS_CONFLICT")
        for key in ("collector_count", "watcher_count"):
            if type(diag.get(key)) is not int or diag[key] != 1:
                reasons.append("PROCESS_COUNT_UNVERIFIED")
    rows = snapshot.get("all_targets")
    valid_count = snapshot.get("valid")
    if (not isinstance(rows, list) or len(rows) < 90 or len(rows) > 110 or
            type(valid_count) is not int or valid_count < 90 or valid_count > 110):
        reasons.append("UNIVERSE_COVERAGE_UNVERIFIED")
    unique = set()
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not _safe_symbol(row.get("ticker")):
                reasons.append("ROW_IDENTITY_INVALID")
                continue
            sym = row["ticker"]
            if sym in unique or row.get("sheet_code") != sym or row.get("data") != "LIVE":
                reasons.append("ROW_IDENTITY_INVALID")
            unique.add(sym)
    watch = []
    counts = {name: 0 for name in sorted(ALLOWED)}
    non_fresh_rows = 0
    if not reasons and isinstance(rows, list):
        for row in rows:
            # Only a row the Collector judged FRESH this cycle (own quote time,
            # same day, within 120 s) is observed; a stale, undated or
            # unknown row is counted and skipped, never read as current.
            if row.get("aggregate_row_fresh") is not True:
                non_fresh_rows += 1
                continue
            price, vwap, high, low = (row.get("price"), row.get("vwap"),
                                      row.get("or_high"), row.get("or_low"))
            # Incomplete OR15 and missing VWAP are not signs.
            if not all(_number(n) for n in (price, vwap, high, low)) or high <= low:
                continue
            kind = None
            if price > high and price > vwap:
                kind = "OR15_ABOVE_VWAP_WATCH"
            elif price < low and price < vwap:
                kind = "OR15_BELOW_VWAP_WATCH"
            if kind:
                counts[kind] += 1
                if len(watch) < MAX_OBSERVATIONS:
                    watch.append({"symbol": row["ticker"], "observation": kind})
    status = "OBSERVATION_ONLY" if not reasons else "BLOCKED"
    return {
        "state": status,
        "reasons": sorted(set(reasons)),
        "source_publication_at": publication_at.isoformat() if publication_at else None,
        "last_market_data_at": None,  # source_timestamp is time-only, not an absolute exchange-time receipt
        "exchange_tick_date_verified": False,
        "signal_provenance_verified": False,
        "tested_expectancy_available": False,
        "observed_rows": len(rows) - non_fresh_rows if status == "OBSERVATION_ONLY" else 0,
        "non_fresh_rows_skipped": non_fresh_rows if status == "OBSERVATION_ONLY" else 0,
        "watch_counts": counts if status == "OBSERVATION_ONLY" else {name: 0 for name in sorted(ALLOWED)},
        "watch_observations": watch,
    }


def status_snapshot(result, *, now, pid):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("DECISION_TIME_WITHOUT_TZ")
    return {
        "schema_version": SCHEMA,
        "component_role": "INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE",
        "engine_pid": pid,
        "updated_at": now.astimezone(timezone.utc).isoformat(),
        "state": result["state"],
        "reasons": result["reasons"],
        "source_publication_at": result["source_publication_at"],
        "last_market_data_at": None,
        "exchange_tick_date_verified": False,
        "signal_provenance_verified": False,
        "observed_rows": result["observed_rows"],
        "watch_counts": result["watch_counts"],
        "watch_observations": result["watch_observations"],
        "tested_expectancy_available": False,
        "source_authenticated": False,
        "cross_source_join_allowed": False,
        "promotion_eligible": False,
        "eligible_observed_n": 0,
        "real_submit_allowed": False,
    }


def read_snapshot(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("INPUT_FILE_UNAVAILABLE")
    stat = path.stat()
    if not 2 <= stat.st_size <= MAX_INPUT_BYTES:
        raise ValueError("INPUT_SIZE_INVALID")
    with path.open("r", encoding="utf-8-sig") as f:
        content = json.load(f)
    if not isinstance(content, dict):
        raise ValueError("INPUT_NOT_OBJECT")
    return content, datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)


def write_status(path: Path, status: dict):
    # Never touch original market CSV, Excel, or live_ms2.json.
    if not path.parent.is_dir() or path.parent.is_symlink() or path.is_symlink():
        raise ValueError("UNTRUSTED_STATUS_DESTINATION")
    if path.name != "ai_brain_observer_status_v1.json":
        raise ValueError("STATUS_PATH_NOT_CANONICAL")
    content = json.dumps(status, sort_keys=True, ensure_ascii=True).encode("ascii")
    if len(content) > 65536:
        raise ValueError("STATUS_TOO_LARGE")
    temp = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    if temp.exists() or temp.is_symlink():
        raise ValueError("TEMP_STATUS_FILE_EXISTS")
    try:
        with temp.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def git_blob_sha1(raw: bytes) -> str:
    """Git blob id of a checked-out file (CRLF from core.autocrlf normalised)."""
    data = raw.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def load_agent_receiver(script_dir: Path):
    """Load the receiver and its two dependencies from pinned bytes only."""
    package = sys.modules.get(AGENT_PACKAGE)
    if package is None:
        package = types.ModuleType(AGENT_PACKAGE)
        package.__path__ = []
        sys.modules[AGENT_PACKAGE] = package
    for name, pin in AGENT_RECEIVER_MODULES:
        qualified = AGENT_PACKAGE + "." + name
        if qualified in sys.modules:
            continue
        path = script_dir / (name + ".py")
        raw = path.read_bytes()
        if git_blob_sha1(raw) != pin:
            raise RuntimeError("AGENT_RECEIVER_MODULE_PIN_MISMATCH:" + name)
        module = types.ModuleType(qualified)
        module.__file__ = str(path)
        module.__package__ = AGENT_PACKAGE
        sys.modules[qualified] = module
        try:
            exec(compile(raw, str(path), "exec"), module.__dict__)
        except Exception:
            del sys.modules[qualified]
            raise
        setattr(package, name, module)
    return sys.modules[AGENT_PACKAGE + ".v10_brain_agent_research_receiver"]


def load_pinned_module(script_dir: Path, name: str, pin: str):
    path = Path(script_dir) / (name + ".py")
    raw = path.read_bytes()
    if git_blob_sha1(raw) != pin:
        raise RuntimeError("PINNED_MODULE_MISMATCH:" + name)
    module = types.ModuleType("v10_pinned_" + name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def signal_ev_pass(state: dict, live_path: Path, *, now=None, script_dir=None):
    """Rebuild the EV table (and rule Shadow) when missing, when it was built on an
    earlier JST day (the OWNER stops V10 right after the close, so the next morning's
    start picks up the previous session), and once after 15:35. Never raises."""
    now = now or datetime.now(timezone.utc)
    jst = now.astimezone(timezone(timedelta(hours=9)))
    target = Path(live_path).parent / SIGNAL_EV_FILE
    after_close = (jst.hour, jst.minute) >= SIGNAL_EV_REBUILD_AFTER_JST
    built_day = None
    try:
        built_day = datetime.fromisoformat(json.loads(target.read_text(encoding="utf-8"))["generated_at"]).astimezone(
            timezone(timedelta(hours=9))).date().isoformat()
    except Exception:
        built_day = None
    due = (built_day is None or built_day < jst.date().isoformat()
           or (after_close and state.get("built_after_close_for") != jst.date().isoformat()))
    if not due or (state.get("next_try") is not None and now < state["next_try"]):
        return None
    state["next_try"] = now + timedelta(minutes=10)
    try:
        module = state.get("module") or load_pinned_module(Path(script_dir or Path(__file__).resolve().parent), *SIGNAL_EV_MODULE)
        state["module"] = module
        table = module.write_table(Path(live_path).parent / "records", target, now=now)
        if after_close:
            state["built_after_close_for"] = jst.date().isoformat()
        summary = {"signal_ev": "BUILT", "days": len(table["days"]), "filled": table["counts"]["filled"]}
    except Exception as exc:  # fail closed, keep the observer running
        summary = {"signal_ev": "BLOCKED", "reason": str(exc) if str(exc).startswith("PINNED_MODULE_MISMATCH") else type(exc).__name__}
    summary["real_submit_allowed"] = False
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


def pts_pickup_pass(state: dict, live_path: Path, *, now=None, script_dir=None):
    """Rebuild the PTS watch list at most every 5 minutes. Never raises."""
    now = now or datetime.now(timezone.utc)
    if state.get("next_at") is not None and now < state["next_at"]:
        return None
    state["next_at"] = now + PTS_PICKUP_INTERVAL
    try:
        module = state.get("module") or load_pinned_module(Path(script_dir or Path(__file__).resolve().parent), *PTS_PICKUP_MODULE)
        state["module"] = module
        view = module.write_pickup(Path(live_path).parent / "records", Path(live_path).parent / PTS_PICKUP_FILE, now=now)
        summary = {"pts_pickup": "BUILT", "session": view["pts_session_date"], "rows": len(view["rows"])}
    except Exception as exc:  # fail closed, keep the observer running
        summary = {"pts_pickup": "BLOCKED", "reason": str(exc) if str(exc).startswith("PINNED_MODULE_MISMATCH") else type(exc).__name__}
    summary["real_submit_allowed"] = False
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


def brain_core_pass(state: dict, live_path: Path, *, now=None, script_dir=None):
    """Pick the top live signals once per observer pass. Never raises; prints only on a change of state."""
    now = now or datetime.now(timezone.utc)
    try:
        module = state.get("module") or load_pinned_module(Path(script_dir or Path(__file__).resolve().parent), *BRAIN_CORE_MODULE)
        state["module"] = module
        raw = Path(live_path).read_bytes()
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("INPUT_TOO_LARGE")
        live = json.loads(raw.decode("utf-8-sig"))
        view = module.write_pick(Path(live_path).parent, live, now=now, logged=state.setdefault("logged", set()))
        summary = {"brain_core": view["state"], "picks": len(view["picks"]), "logged_new": view["logged_new"]}
    except Exception as exc:  # fail closed, keep the observer running
        summary = {"brain_core": "BLOCKED", "reason": str(exc) if str(exc).startswith("PINNED_MODULE_MISMATCH") else type(exc).__name__}
    summary["real_submit_allowed"] = False
    if summary != state.get("last"):
        state["last"] = summary
        print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


def agent_receiver_pass(state: dict, *, now=None, script_dir=None):
    """Opt-in: receive signed agent research once per interval. Never raises."""
    inbox = os.environ.get(AGENT_INBOX_ENV, "")
    if not inbox:
        return None
    now = now or datetime.now(timezone.utc)
    if state.get("next_at") is not None and now < state["next_at"]:
        return None
    state["next_at"] = now + AGENT_RECEIVER_INTERVAL
    try:
        receiver = state.get("module") or load_agent_receiver(Path(script_dir or Path(__file__).resolve().parent))
        state["module"] = receiver
        out = receiver.receive_inbox(inbox, now=now, host_component=AGENT_HOST_COMPONENT)
        counts = {}
        for item in out["results"]:
            counts[item["state"]] = counts.get(item["state"], 0) + 1
        summary = {"agent_receiver": "PASS", "results": counts, "restored_acks": len(out["restored_acks"])}
    except Exception as exc:  # fail closed, keep the observer running
        text = str(exc)
        reason = text if text.startswith(AGENT_KNOWN_REASONS) else type(exc).__name__
        summary = {"agent_receiver": "BLOCKED", "reason": reason}
    summary["real_submit_allowed"] = False
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


def run_once(live_path: Path, status_path: Path, *, now=None, pid=None):
    now = now or datetime.now(timezone.utc)
    pid = pid if pid is not None else os.getpid()
    try:
        data, mtime = read_snapshot(live_path)
        result = analyze(data, now=now, file_modified_at=mtime)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        # Never reveal raw values or private paths in the status.
        result = analyze({}, now=now, file_modified_at=None)
        result["reasons"] = sorted(set(result["reasons"] + ["INPUT_UNAVAILABLE_OR_INVALID"]))
    status = status_snapshot(result, now=now, pid=pid)
    write_status(status_path, status)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only independent V10 BRAIN observation processor")
    parser.add_argument("--live", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if not 2 <= args.interval <= 60:
        parser.error("interval must be between 2 and 60 seconds")
    live, status_path = Path(args.live), Path(args.status)
    if args.once:
        run_once(live, status_path)
        return 0
    agent_state = {}
    ev_state = {}
    pts_state = {}
    brain_state = {}
    while True:
        run_once(live, status_path)
        agent_receiver_pass(agent_state)
        signal_ev_pass(ev_state, live)
        pts_pickup_pass(pts_state, live)
        brain_core_pass(brain_state, live)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
