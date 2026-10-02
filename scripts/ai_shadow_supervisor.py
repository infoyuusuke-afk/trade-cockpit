"""Background AI SHADOW supervisor.

The cockpit page does not own this process. The V9 controller starts one
Python process; the browser only reads the status the process publishes.

This module does not call scripts/shadow_execution.py. Collector rows do not
carry an Intent, RiskDecision, or PermissionTicket, and fabricating that
lineage would violate the existing fail-closed contract. Virtual entries use
only prices and signals the collector already published. They are not broker
fills and not Fill Model v0.1 fills.

real_submit_allowed is always false on every record this module writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = "ai-shadow-supervisor-1"
CANONICAL_SOURCE = "MarketSpeed II RSS / local PC"
CANONICAL_WORKBOOK = "Kioxia_MS2_RSS_Live_Signals.xlsx"
MAX_AGE_SECONDS = 60
STATUS_STALE_SECONDS = 30

LONG_ENTRY_SIGNALS = frozenset({"初動買い候補", "買いサイン", "持ち越しロング確定"})
SHORT_ENTRY_SIGNALS = frozenset({"初動ショート候補", "空売りサイン", "持ち越しショート確定"})
ENTRY_SIGNALS = LONG_ENTRY_SIGNALS | SHORT_ENTRY_SIGNALS

STATES = ("RUNNING", "PAUSED_FAIL_CLOSED", "RECOVERING", "STOPPED")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and value not in (float("inf"), float("-inf"))


def parse_timestamp(value, tz) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("JST"):
        text = text[:-3].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=tz)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def assess_live_payload(payload, *, file_mtime: datetime | None, now: datetime, max_age_seconds: int = MAX_AGE_SECONDS) -> dict:
    """Same fail-closed idea as the gateway/collector price gate.

    Unknown, stale, sample, conflicting, or non-canonical input is not tradable.
    A passing verdict still forces real_submit_allowed false.
    """
    reasons: list[str] = []
    if now.tzinfo is None or now.utcoffset() is None:
        reasons.append("NOW_NOT_TIMEZONE_AWARE")
    if not isinstance(payload, dict):
        reasons.append("MISSING_PAYLOAD")
        return _verdict(reasons)

    if payload.get("real_submit_allowed") is not False:
        reasons.append("REAL_SUBMIT_NOT_FALSE")
    if payload.get("live_values_available") is not True:
        reasons.append("LIVE_VALUES_UNAVAILABLE")
    status = payload.get("price_source_status")
    if status != "OK":
        if isinstance(status, str) and status and status != "OK":
            reasons.append(status)
        else:
            reasons.append("MISSING_PRICE_DIAGNOSTICS")
    if payload.get("source") != CANONICAL_SOURCE:
        reasons.append("CACHED_OR_SAMPLE_PAYLOAD")
    if payload.get("source_mode") != "MS2_RSS_WORKBOOK":
        reasons.append("WRONG_SOURCE_WORKBOOK")
    if payload.get("data_conflict") is True:
        reasons.append("DATA_CONFLICT")
    if payload.get("stale") is not False:
        reasons.append("STALE_OR_MISSING_TIMESTAMP")

    diag = payload.get("live_price_diagnostics")
    if not isinstance(diag, dict):
        reasons.append("MISSING_PRICE_DIAGNOSTICS")
    else:
        if diag.get("price_source_status") != "OK":
            reasons.append("MISSING_PRICE_DIAGNOSTICS")
        if diag.get("source_mode") != "MS2_RSS_WORKBOOK":
            reasons.append("WRONG_SOURCE_WORKBOOK")
        if diag.get("workbook_name") != CANONICAL_WORKBOOK:
            reasons.append("WRONG_SOURCE_WORKBOOK")
        if diag.get("data_conflict") is True:
            reasons.append("DATA_CONFLICT")
        if diag.get("duplicate_collector") is True:
            reasons.append("DUPLICATE_COLLECTOR")
        if diag.get("duplicate_watcher") is True:
            reasons.append("DUPLICATE_WATCHER")
        collector_count = diag.get("collector_count")
        if collector_count is None:
            reasons.append("COLLECTOR_PROCESS_UNVERIFIED")
        elif not isinstance(collector_count, int) or isinstance(collector_count, bool) or collector_count != 1:
            reasons.append("DUPLICATE_COLLECTOR" if isinstance(collector_count, int) and collector_count > 1 else "COLLECTOR_PROCESS_UNVERIFIED")
        watcher_count = diag.get("watcher_count")
        if watcher_count is None:
            reasons.append("DUPLICATE_PROCESS_CHECK_UNAVAILABLE")
        elif not isinstance(watcher_count, int) or isinstance(watcher_count, bool) or watcher_count < 0 or watcher_count > 1:
            reasons.append("DUPLICATE_WATCHER")
        if isinstance(diag.get("stale_reason"), str) and diag.get("stale_reason"):
            reasons.append(str(diag.get("stale_reason")))

    if not isinstance(payload.get("all_targets"), list):
        reasons.append("MISSING_BOARD")

    tz = now.tzinfo if now.tzinfo is not None and now.utcoffset() is not None else timezone.utc
    updated = parse_timestamp(payload.get("updated_at"), tz)
    if updated is None:
        reasons.append("STALE_OR_MISSING_TIMESTAMP")
    else:
        age = (now - updated).total_seconds()
        if age < 0 or age > max_age_seconds:
            reasons.append("STALE_OR_MISSING_TIMESTAMP")
    if file_mtime is None or file_mtime.tzinfo is None or file_mtime.utcoffset() is None:
        reasons.append("STALE_OR_MISSING_TIMESTAMP")
    else:
        mage = (now - file_mtime.astimezone(tz)).total_seconds()
        if mage < 0 or mage > max_age_seconds:
            reasons.append("STALE_OR_MISSING_TIMESTAMP")
    return _verdict(reasons)


def _verdict(reasons: list[str]) -> dict:
    unique = sorted(set(reasons))
    return {"ok": not unique, "reasons": unique, "real_submit_allowed": False}


def board_fingerprint(payload: dict) -> str:
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    compact = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                compact.append(None)
                continue
            compact.append({
                "ticker": row.get("ticker"),
                "signal": row.get("signal"),
                "strategy": row.get("strategy"),
                "price": row.get("price"),
                "entry_price": row.get("entry_price"),
                "stop_price": row.get("stop_price"),
                "target1": row.get("target1"),
                "target2": row.get("target2"),
                "source_timestamp": row.get("source_timestamp"),
                "data": row.get("data"),
            })
    encoded = json.dumps({
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "rows": compact,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _side_of(signal: str) -> str | None:
    if signal in LONG_ENTRY_SIGNALS:
        return "LONG"
    if signal in SHORT_ENTRY_SIGNALS:
        return "SHORT"
    return None


def _geometry_ok(side: str, entry, stop) -> bool:
    if not (_finite(entry) and _finite(stop) and entry > 0 and stop > 0):
        return False
    if side == "LONG":
        return stop < entry
    return stop > entry


def _row_price_ok(row: dict) -> bool:
    return _finite(row.get("price")) and row.get("price") > 0 and row.get("data") == "LIVE"


def entry_candidate(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    signal = row.get("signal")
    side = _side_of(signal) if isinstance(signal, str) else None
    if side is None or not _row_price_ok(row) or not _geometry_ok(side, row.get("entry_price"), row.get("stop_price")):
        return None
    ticker = row.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None
    return {
        "ticker": ticker,
        "side": side,
        "signal": signal,
        "strategy": row.get("strategy") if isinstance(row.get("strategy"), str) else "",
        "price": row.get("price"),
        "entry_price": row.get("entry_price"),
        "stop_price": row.get("stop_price"),
        "target1": row.get("target1") if _finite(row.get("target1")) else None,
        "target2": row.get("target2") if _finite(row.get("target2")) else None,
        "source_timestamp": row.get("source_timestamp"),
    }


def position_key(ticker: str, side: str) -> str:
    return ticker + "|" + side


def _rationale(row_like: dict) -> str:
    parts = [str(row_like.get("signal") or ""), str(row_like.get("strategy") or "")]
    parts.append("entry " + str(row_like.get("entry_price")))
    parts.append("stop " + str(row_like.get("stop_price")))
    if row_like.get("target1") is not None:
        parts.append("target1 " + str(row_like.get("target1")))
    parts.append("price " + str(row_like.get("price")))
    if row_like.get("source_timestamp"):
        parts.append("source_timestamp " + str(row_like.get("source_timestamp")))
    return " / ".join(p for p in parts if p)


def _pnl_per_share(side: str, entry, exit_price):
    if not (_finite(entry) and _finite(exit_price)):
        return None
    if side == "LONG":
        return exit_price - entry
    if side == "SHORT":
        return entry - exit_price
    return None


def _r_multiple(side: str, entry, stop, exit_price):
    pnl = _pnl_per_share(side, entry, exit_price)
    if pnl is None or not _finite(stop) or not _finite(entry) or entry == stop:
        return None
    risk = abs(entry - stop)
    if risk == 0:
        return None
    return pnl / risk


def count_invalidated_entries(payload) -> int:
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return 0
    count = 0
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("signal"), str) and row.get("signal") in ENTRY_SIGNALS:
            count += 1
    return count


def fresh_state(*, now: datetime) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "STOPPED",
        "reason": "",
        "resume_blocked": False,
        "block_reason": "",
        "last_seq": 0,
        "seen_board_fingerprints": [],
        "open_incident_id": None,
        "engine_started_at": now.isoformat(),
        "real_submit_allowed": False,
        "pid": os.getpid(),
    }


def _read_jsonl(path: Path) -> tuple[list[dict] | None, str]:
    if not path.exists():
        return [], ""
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, "LEDGER_UNREADABLE"
    if text == "":
        return [], ""
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return None, "LEDGER_CORRUPT"
        if not isinstance(item, dict):
            return None, "LEDGER_CORRUPT"
        rows.append(item)
    return rows, ""


def replay_ledger(events: list[dict]) -> tuple[dict, str]:
    open_positions: dict[str, dict] = {}
    for index, event in enumerate(events, start=1):
        if event.get("seq") != index or event.get("real_submit_allowed") is not False:
            return {}, "LEDGER_CORRUPT"
        kind = event.get("record_class")
        if kind != "shadow_observation":
            return {}, "LEDGER_CORRUPT"
        event_type = event.get("event_type")
        if event_type == "board_judgment":
            continue
        if event_type == "virtual_entry":
            key = event.get("position_key")
            if not isinstance(key, str) or key in open_positions:
                return {}, "LEDGER_CORRUPT"
            open_positions[key] = event
            continue
        if event_type == "virtual_exit":
            key = event.get("position_key")
            if not isinstance(key, str) or key not in open_positions:
                return {}, "LEDGER_CORRUPT"
            del open_positions[key]
            continue
        return {}, "LEDGER_CORRUPT"
    return open_positions, ""


def _operations_incidents_only(incidents: list[dict] | None) -> bool:
    """A diary of operations incidents is not a shadow trade ledger.

    Missing trade state still blocks when any observation ledger exists.
    Incident rows alone must be readable operations records, or the engine
    stays fail-closed.
    """
    if not incidents:
        return False
    for item in incidents:
        if not isinstance(item, dict) or item.get("record_class") != "operations_incident":
            return False
        if item.get("real_submit_allowed") is not False or item.get("fail_closed") is not True:
            return False
    return True


def load_engine(data_dir: Path, *, now: datetime) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / "state.json"
    ledger_path = data_dir / "ledger.jsonl"
    incident_path = data_dir / "incidents.jsonl"
    state = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {"resume_blocked": True, "block_reason": "STATE_UNREADABLE", "last_seq": -1}
        if not isinstance(state, dict):
            state = {"resume_blocked": True, "block_reason": "STATE_UNREADABLE", "last_seq": -1}
    ledger, ledger_error = _read_jsonl(ledger_path)
    incidents, incident_error = _read_jsonl(incident_path)
    engine = {
        "state": fresh_state(now=now) if state is None and not ledger_path.exists() and not incident_path.exists() else (state or fresh_state(now=now)),
        "ledger": ledger or [],
        "incidents": incidents or [],
        "open_positions": {},
        "clean_boot": state is None and not ledger_path.exists() and not incident_path.exists(),
        "incident_history_only": False,
    }
    engine["state"]["real_submit_allowed"] = False
    if ledger_error or incident_error:
        _block(engine, ledger_error or incident_error)
        return engine
    if state is None and ledger_path.exists():
        _block(engine, "STATE_MISSING")
        return engine
    if state is None and incident_path.exists():
        if not _operations_incidents_only(incidents):
            _block(engine, "STATE_MISSING")
            return engine
        engine["incident_history_only"] = True
        engine["state"] = fresh_state(now=now)
        engine["state"]["real_submit_allowed"] = False
        engine["incidents"] = incidents or []
    if state is not None and not ledger_path.exists() and int(state.get("last_seq") or 0) > 0:
        _block(engine, "LEDGER_MISSING")
        return engine
    if state is not None and not incident_path.exists() and state.get("open_incident_id"):
        _block(engine, "INCIDENT_LOG_MISSING")
        return engine
    if ledger is None:
        _block(engine, "LEDGER_MISSING")
        return engine
    open_positions, replay_error = replay_ledger(ledger)
    if replay_error:
        _block(engine, replay_error)
        return engine
    last_seq = int(engine["state"].get("last_seq") or 0)
    if last_seq > len(ledger):
        _block(engine, "LEDGER_STATE_MISMATCH")
        return engine
    if last_seq < len(ledger):
        engine["state"]["last_seq"] = len(ledger)
    engine["open_positions"] = open_positions
    if engine["state"].get("resume_blocked") is True:
        engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
        return engine
    previous = engine["state"].get("state")
    if previous not in STATES:
        _block(engine, "UNKNOWN_STATE")
        return engine
    if not engine["clean_boot"]:
        engine["state"]["state"] = "RECOVERING"
        engine["state"]["reason"] = "PROCESS_RESTART"
    return engine


def _block(engine: dict, reason: str) -> None:
    engine["state"]["resume_blocked"] = True
    engine["state"]["block_reason"] = reason
    engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
    engine["state"]["reason"] = reason
    engine["state"]["real_submit_allowed"] = False
    engine["open_positions"] = {}


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _primary_reason(reasons: list[str]) -> str:
    if not reasons:
        return "UNKNOWN"
    preferred = (
        "PRICE_SOURCE_MISMATCH", "DATA_CONFLICT", "STALE_OR_MISSING_TIMESTAMP",
        "CACHED_OR_SAMPLE_PAYLOAD", "WRONG_SOURCE_WORKBOOK", "WRONG_SYMBOL_MAPPING",
        "DUPLICATE_COLLECTOR", "DUPLICATE_WATCHER", "LIVE_VALUES_UNAVAILABLE",
        "MISSING_PAYLOAD", "REAL_SUBMIT_NOT_FALSE",
    )
    for code in preferred:
        if code in reasons:
            return code
    return reasons[0]


def _component_for(reason: str) -> str:
    if reason in {"DUPLICATE_COLLECTOR", "COLLECTOR_PROCESS_UNVERIFIED"}:
        return "collector"
    if reason == "DUPLICATE_WATCHER":
        return "watcher"
    if reason in {"STALE_OR_MISSING_TIMESTAMP", "MISSING_PAYLOAD", "INSUFFICIENT_COVERAGE"}:
        return "live_ms2"
    if reason in {"PRICE_SOURCE_MISMATCH", "WRONG_SOURCE_WORKBOOK", "WRONG_SYMBOL_MAPPING", "CACHED_OR_SAMPLE_PAYLOAD", "DATA_CONFLICT"}:
        return "price_source"
    return "ai_shadow"


def _open_incident(engine: dict, data_dir: Path, *, now: datetime, reasons: list[str], invalidated: int) -> None:
    if engine["state"].get("open_incident_id"):
        for incident in engine["incidents"]:
            if incident.get("incident_id") == engine["state"]["open_incident_id"] and incident.get("recovery_at") is None:
                incident["invalidated_signal_count"] = int(incident.get("invalidated_signal_count") or 0) + invalidated
                incident["symptom"] = ",".join(reasons)
                _rewrite_incidents(data_dir, engine["incidents"])
                return
    reason = _primary_reason(reasons)
    recurrence_key = _component_for(reason) + "|" + reason
    prior = sum(1 for item in engine["incidents"] if item.get("recurrence_key") == recurrence_key)
    incident = {
        "record_class": "operations_incident",
        "incident_id": "inc-" + hashlib.sha256((now.isoformat() + "|" + recurrence_key).encode("utf-8")).hexdigest()[:16],
        "occurrence_at": now.isoformat(),
        "recovery_at": None,
        "duration_seconds": None,
        "component": _component_for(reason),
        "error_code": reason,
        "symptom": ",".join(reasons),
        "suspected_cause": reason,
        "confirmed_cause": None,
        "impact_scope": "ai_shadow_observations",
        "real_trade_impact": "NONE_REAL_SUBMIT_REMAINS_FALSE",
        "shadow_impact": "PAUSED_FAIL_CLOSED",
        "fail_closed": True,
        "invalidated_signal_count": invalidated,
        "recovery_mode": None,
        "actions": ["new shadow signals invalidated", "virtual entry and exit suspended"],
        "recurrence_key": recurrence_key,
        "recurrence_count": prior + 1,
        "log_refs": ["ledger.jsonl", "incidents.jsonl", "live_ms2.json"],
        "real_submit_allowed": False,
    }
    engine["incidents"].append(incident)
    engine["state"]["open_incident_id"] = incident["incident_id"]
    _append_jsonl(data_dir / "incidents.jsonl", incident)


def _rewrite_incidents(data_dir: Path, incidents: list[dict]) -> None:
    path = data_dir / "incidents.jsonl"
    temporary = path.with_suffix(".jsonl.tmp")
    body = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for item in incidents)
    temporary.write_text(body, encoding="utf-8")
    os.replace(temporary, path)


def _close_incident(engine: dict, data_dir: Path, *, now: datetime, recovery_mode: str) -> None:
    incident_id = engine["state"].get("open_incident_id")
    if not incident_id:
        return
    for incident in engine["incidents"]:
        if incident.get("incident_id") != incident_id or incident.get("recovery_at"):
            continue
        started = parse_timestamp(incident.get("occurrence_at"), now.tzinfo)
        incident["recovery_at"] = now.isoformat()
        incident["duration_seconds"] = None if started is None else max(0, int((now - started).total_seconds()))
        incident["recovery_mode"] = recovery_mode
        incident["shadow_impact"] = "AUTO_RESUMED" if recovery_mode == "AUTO" else "MANUAL_RESUMED"
        incident["actions"] = list(incident.get("actions") or []) + ["safety check PASS", "AI SHADOW resumed without duplicating open observations"]
        incident["confirmed_cause"] = None
        break
    engine["state"]["open_incident_id"] = None
    _rewrite_incidents(data_dir, engine["incidents"])


def _next_event(engine: dict, *, now: datetime, event_type: str, payload: dict) -> dict:
    engine["state"]["last_seq"] = int(engine["state"].get("last_seq") or 0) + 1
    record = {
        "record_class": "shadow_observation",
        "schema_version": SCHEMA_VERSION,
        "seq": engine["state"]["last_seq"],
        "event_type": event_type,
        "at": now.isoformat(),
        "real_submit_allowed": False,
        "pricing": "collector_published_price_not_fill_model",
    }
    record.update(payload)
    return record


def _contaminated(engine: dict, opened_at: str, now: datetime) -> bool:
    opened = parse_timestamp(opened_at, now.tzinfo)
    if opened is None:
        return True
    for incident in engine["incidents"]:
        start = parse_timestamp(incident.get("occurrence_at"), now.tzinfo)
        if start is None:
            return True
        end = parse_timestamp(incident.get("recovery_at"), now.tzinfo) if incident.get("recovery_at") else now
        if end is None:
            return True
        if start < now and end > opened:
            return True
    return False


def apply_cycle(engine: dict, payload, verdict: dict, *, now: datetime, data_dir: Path, recovery_mode: str = "AUTO") -> dict:
    """One supervisor cycle. Fail-closed input never creates or closes a virtual trade."""
    engine["state"]["real_submit_allowed"] = False
    if engine["state"].get("resume_blocked") is True:
        engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
        engine["state"]["reason"] = engine["state"].get("block_reason") or "UNKNOWN_STATE"
        _persist(engine, data_dir)
        return engine

    fingerprint = board_fingerprint(payload) if isinstance(payload, dict) else "missing-payload"
    seen = set(engine["state"].get("seen_board_fingerprints") or [])

    if not verdict.get("ok"):
        engine["state"]["state"] = "PAUSED_FAIL_CLOSED"
        engine["state"]["reason"] = _primary_reason(list(verdict.get("reasons") or ["UNKNOWN"]))
        if fingerprint not in seen:
            invalidated = count_invalidated_entries(payload)
            _open_incident(engine, data_dir, now=now, reasons=list(verdict.get("reasons") or ["UNKNOWN"]), invalidated=invalidated)
            seen.add(fingerprint)
            engine["state"]["seen_board_fingerprints"] = sorted(seen)
        _persist(engine, data_dir)
        return engine

    if engine["state"].get("state") in {"PAUSED_FAIL_CLOSED", "STOPPED", "RECOVERING"}:
        mode = recovery_mode if engine["state"].get("state") == "PAUSED_FAIL_CLOSED" and engine["state"].get("open_incident_id") else "AUTO"
        if engine["state"].get("open_incident_id"):
            _close_incident(engine, data_dir, now=now, recovery_mode=mode)
        engine["state"]["state"] = "RECOVERING"
        engine["state"]["reason"] = "SAFETY_CHECK_PASS"

    if fingerprint in seen:
        engine["state"]["state"] = "RUNNING"
        engine["state"]["reason"] = ""
        _persist(engine, data_dir)
        return engine

    rows = payload.get("all_targets") if isinstance(payload, dict) else []
    by_key = {}
    judgments = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = entry_candidate(row)
        ticker = row.get("ticker") if isinstance(row.get("ticker"), str) else ""
        if candidate is not None:
            by_key[position_key(candidate["ticker"], candidate["side"])] = candidate
        judgments.append({
            "ticker": ticker,
            "signal": row.get("signal"),
            "strategy": row.get("strategy") if isinstance(row.get("strategy"), str) else "",
            "entry_candidate": candidate is not None,
        })

    exits = []
    for key, position in list(engine["open_positions"].items()):
        ticker, side = key.split("|", 1)
        current = None
        for row in rows:
            if isinstance(row, dict) and row.get("ticker") == ticker:
                current = row
                break
        if current is None or not _row_price_ok(current):
            continue
        still_same_side = _side_of(current.get("signal")) == side if isinstance(current.get("signal"), str) else False
        if still_same_side:
            continue
        exit_price = current.get("price")
        opened_at = position.get("at")
        bucket = "contaminated_by_data_outage" if _contaminated(engine, opened_at, now) else "clean_strategy"
        event = _next_event(engine, now=now, event_type="virtual_exit", payload={
            "position_key": key,
            "ticker": ticker,
            "side": side,
            "strategy": position.get("strategy") or "",
            "signal": current.get("signal"),
            "entry_price": position.get("entry_price"),
            "exit_price": exit_price,
            "pnl_per_share_yen": _pnl_per_share(side, position.get("entry_price"), exit_price),
            "r_multiple": _r_multiple(side, position.get("entry_price"), position.get("stop_price"), exit_price),
            "quantity": None,
            "performance_bucket": bucket,
            "exit_reason": "collector_signal_left_entry_set",
            "decision_rationale": _rationale({
                "signal": current.get("signal"),
                "strategy": current.get("strategy"),
                "entry_price": position.get("entry_price"),
                "stop_price": position.get("stop_price"),
                "price": exit_price,
                "source_timestamp": current.get("source_timestamp"),
            }),
            "related_entry_seq": position.get("seq"),
        })
        engine["ledger"].append(event)
        _append_jsonl(data_dir / "ledger.jsonl", event)
        del engine["open_positions"][key]
        exits.append(event["seq"])

    entries = []
    for key, candidate in by_key.items():
        if key in engine["open_positions"]:
            continue
        event = _next_event(engine, now=now, event_type="virtual_entry", payload={
            "position_key": key,
            "ticker": candidate["ticker"],
            "side": candidate["side"],
            "strategy": candidate["strategy"],
            "signal": candidate["signal"],
            "entry_price": candidate["entry_price"],
            "stop_price": candidate["stop_price"],
            "target1": candidate["target1"],
            "target2": candidate["target2"],
            "published_price": candidate["price"],
            "source_timestamp": candidate["source_timestamp"],
            "quantity": None,
            "performance_bucket": "open_unrealized_not_marked",
            "decision_rationale": _rationale(candidate),
        })
        engine["ledger"].append(event)
        _append_jsonl(data_dir / "ledger.jsonl", event)
        engine["open_positions"][key] = event
        entries.append(event["seq"])

    judgment = _next_event(engine, now=now, event_type="board_judgment", payload={
        "board_fingerprint": fingerprint,
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "entry_seqs": entries,
        "exit_seqs": exits,
        "judgments": judgments,
    })
    engine["ledger"].append(judgment)
    _append_jsonl(data_dir / "ledger.jsonl", judgment)
    seen.add(fingerprint)
    engine["state"]["seen_board_fingerprints"] = sorted(seen)
    engine["state"]["state"] = "RUNNING"
    engine["state"]["reason"] = ""
    _persist(engine, data_dir)
    return engine


def _persist(engine: dict, data_dir: Path) -> None:
    engine["state"]["real_submit_allowed"] = False
    engine["state"]["pid"] = os.getpid()
    _write_json(data_dir / "state.json", engine["state"])


def _clip_duration(incident: dict, start: datetime, end: datetime) -> int:
    opened = parse_timestamp(incident.get("occurrence_at"), start.tzinfo)
    if opened is None:
        return 0
    closed = parse_timestamp(incident.get("recovery_at"), start.tzinfo) if incident.get("recovery_at") else end
    if closed is None:
        return 0
    left = max(opened, start)
    right = min(closed, end)
    if right <= left:
        return 0
    return int((right - left).total_seconds())


def summarize_operations(engine: dict, *, now: datetime) -> dict:
    started = parse_timestamp(engine["state"].get("engine_started_at"), now.tzinfo)
    trades = [event for event in engine["ledger"] if event.get("event_type") == "virtual_exit"]

    def window(label: str, seconds: int) -> dict:
        if started is None:
            return _empty_window(label)
        begin = max(started, now - timedelta(seconds=seconds))
        elapsed = int((now - begin).total_seconds())
        incidents = [item for item in engine["incidents"] if parse_timestamp(item.get("occurrence_at"), now.tzinfo) and parse_timestamp(item.get("occurrence_at"), now.tzinfo) >= begin]
        downtime = sum(_clip_duration(item, begin, now) for item in engine["incidents"])
        recovered = [item for item in incidents if item.get("recovery_at")]
        durations = [item.get("duration_seconds") for item in recovered if isinstance(item.get("duration_seconds"), int)]
        freshness = sum(1 for item in incidents if item.get("error_code") in {"STALE_OR_MISSING_TIMESTAMP", "INSUFFICIENT_COVERAGE", "MISSING_PAYLOAD"})
        mismatches = sum(1 for item in incidents if item.get("error_code") in {"PRICE_SOURCE_MISMATCH", "WRONG_SOURCE_WORKBOOK", "WRONG_SYMBOL_MAPPING", "DATA_CONFLICT", "CACHED_OR_SAMPLE_PAYLOAD"})
        auto_count = sum(1 for item in recovered if item.get("recovery_mode") == "AUTO")
        manual_count = sum(1 for item in recovered if item.get("recovery_mode") == "MANUAL")
        in_window_trades = []
        for trade in trades:
            at = parse_timestamp(trade.get("at"), now.tzinfo)
            if at is not None and begin <= at <= now:
                in_window_trades.append(trade)
        clean = [trade for trade in in_window_trades if trade.get("performance_bucket") == "clean_strategy"]
        dirty = [trade for trade in in_window_trades if trade.get("performance_bucket") == "contaminated_by_data_outage"]
        uptime = None if elapsed <= 0 else max(0.0, min(1.0, (elapsed - downtime) / elapsed))
        mttr = None if not durations else sum(durations) / len(durations)
        recurrence = {}
        for item in incidents:
            key = item.get("recurrence_key") or ""
            recurrence[key] = max(int(item.get("recurrence_count") or 0), recurrence.get(key, 0))
        return {
            "label": label,
            "error_count": len(incidents),
            "total_downtime_seconds": downtime,
            "shadow_uptime_ratio": uptime,
            "freshness_anomaly_count": freshness,
            "price_mismatch_count": mismatches,
            "auto_recovery_count": auto_count,
            "manual_response_count": manual_count,
            "mttr_seconds": mttr,
            "recurrence": recurrence,
            "clean_strategy_pnl_per_share_yen": _sum_pnl(clean),
            "contaminated_pnl_per_share_yen": _sum_pnl(dirty),
            "clean_strategy_exit_count": len(clean),
            "contaminated_exit_count": len(dirty),
        }

    return {
        "daily": window("daily", 86400),
        "weekly": window("weekly", 7 * 86400),
        "monthly": window("monthly", 31 * 86400),
    }


def _empty_window(label: str) -> dict:
    return {
        "label": label,
        "error_count": None,
        "total_downtime_seconds": None,
        "shadow_uptime_ratio": None,
        "freshness_anomaly_count": None,
        "price_mismatch_count": None,
        "auto_recovery_count": None,
        "manual_response_count": None,
        "mttr_seconds": None,
        "recurrence": {},
        "clean_strategy_pnl_per_share_yen": None,
        "contaminated_pnl_per_share_yen": None,
        "clean_strategy_exit_count": None,
        "contaminated_exit_count": None,
    }


def _sum_pnl(trades: list[dict]):
    total = 0.0
    seen = False
    for trade in trades:
        value = trade.get("pnl_per_share_yen")
        if _finite(value):
            total += value
            seen = True
    return total if seen else None


def status_snapshot(engine: dict, *, now: datetime) -> dict:
    ops = summarize_operations(engine, now=now)
    latest = None
    for incident in reversed(engine["incidents"]):
        latest = {
            "incident_id": incident.get("incident_id"),
            "occurrence_at": incident.get("occurrence_at"),
            "recovery_at": incident.get("recovery_at"),
            "duration_seconds": incident.get("duration_seconds"),
            "component": incident.get("component"),
            "error_code": incident.get("error_code"),
            "symptom": incident.get("symptom"),
            "suspected_cause": incident.get("suspected_cause"),
            "confirmed_cause": incident.get("confirmed_cause"),
            "shadow_impact": incident.get("shadow_impact"),
            "fail_closed": incident.get("fail_closed"),
            "invalidated_signal_count": incident.get("invalidated_signal_count"),
            "recovery_mode": incident.get("recovery_mode"),
            "recurrence_count": incident.get("recurrence_count"),
            "real_trade_impact": incident.get("real_trade_impact"),
        }
        break
    return {
        "schema_version": SCHEMA_VERSION,
        "state": engine["state"].get("state"),
        "reason": engine["state"].get("reason") or engine["state"].get("block_reason") or "",
        "updated_at": now.isoformat(),
        "real_submit_allowed": False,
        "ui_independent": True,
        "open_observation_count": len(engine["open_positions"]),
        "resume_blocked": engine["state"].get("resume_blocked") is True,
        "engine_pid": os.getpid(),
        "latest_incident": latest,
        "ops": ops,
    }


def publish_status(engine: dict, status_path: Path, *, now: datetime) -> None:
    _write_json(status_path, status_snapshot(engine, now=now))


def pid_alive(pid: int) -> bool | None:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        if getattr(error, "winerror", None) == 87:
            return False
        if getattr(error, "errno", None) in {1, 3}:
            return True if error.errno == 1 else None
        return None
    else:
        return True


def _exclusive_lock(lock_path: Path, payload: dict) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(lock_path, flags)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def acquire_singleton(lock_path: Path, *, pid: int, now: datetime, alive=pid_alive, stale_seconds: int = STATUS_STALE_SECONDS) -> str:
    """Return ACQUIRED, ALREADY_RUNNING, or REFUSED_LOCK_UNKNOWN.

    A second live process must not trade. An unknown lock is not treated as free.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": pid, "heartbeat_at": now.isoformat(), "script": "ai_shadow_supervisor.py", "real_submit_allowed": False}
    if not lock_path.exists():
        return "ACQUIRED" if _exclusive_lock(lock_path, payload) else "REFUSED_LOCK_UNKNOWN"
    try:
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "REFUSED_LOCK_UNKNOWN"
    if not isinstance(existing, dict):
        return "REFUSED_LOCK_UNKNOWN"
    owner = existing.get("pid")
    state = alive(owner) if isinstance(owner, int) and not isinstance(owner, bool) else False
    if state is None:
        return "REFUSED_LOCK_UNKNOWN"
    if state is True and owner == pid:
        _write_json(lock_path, payload)
        return "ACQUIRED"
    if state is True:
        heartbeat = parse_timestamp(existing.get("heartbeat_at"), now.tzinfo)
        fresh = heartbeat is not None and abs((now - heartbeat).total_seconds()) <= stale_seconds
        if fresh:
            return "ALREADY_RUNNING"
        return "REFUSED_LOCK_UNKNOWN"
    try:
        lock_path.unlink()
    except OSError:
        return "REFUSED_LOCK_UNKNOWN"
    return "ACQUIRED" if _exclusive_lock(lock_path, payload) else "ALREADY_RUNNING"


def touch_lock(lock_path: Path, *, pid: int, now: datetime) -> None:
    _write_json(lock_path, {"pid": pid, "heartbeat_at": now.isoformat(), "script": "ai_shadow_supervisor.py", "real_submit_allowed": False})


def read_manual_recovery(data_dir: Path) -> str:
    path = data_dir / "manual_recovery.json"
    if not path.exists():
        return "AUTO"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "AUTO"
    if isinstance(payload, dict) and payload.get("action") == "acknowledge":
        return "MANUAL"
    return "AUTO"


def run_once(data_dir: Path, live_path: Path, status_path: Path, *, now: datetime | None = None) -> dict:
    moment = now or datetime.now().astimezone()
    engine = load_engine(data_dir, now=moment)
    payload = None
    file_mtime = None
    if live_path.exists():
        try:
            payload = json.loads(live_path.read_text(encoding="utf-8"))
            file_mtime = datetime.fromtimestamp(live_path.stat().st_mtime, tz=moment.tzinfo)
        except (OSError, json.JSONDecodeError, ValueError):
            payload = None
            file_mtime = None
    verdict = assess_live_payload(payload, file_mtime=file_mtime, now=moment)
    apply_cycle(engine, payload, verdict, now=moment, data_dir=data_dir, recovery_mode=read_manual_recovery(data_dir))
    publish_status(engine, status_path, now=moment)
    return engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI SHADOW background supervisor")
    parser.add_argument("--live", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)
    live_path = Path(args.live)
    status_path = Path(args.status)
    lock_path = data_dir / "supervisor.lock.json"
    now = datetime.now().astimezone()
    lock = acquire_singleton(lock_path, pid=os.getpid(), now=now)
    if lock == "ALREADY_RUNNING":
        print("ALREADY_RUNNING")
        return 0
    if lock != "ACQUIRED":
        print("REFUSED_LOCK_UNKNOWN")
        return 2
    try:
        if args.once:
            run_once(data_dir, live_path, status_path, now=now)
            return 0
        while True:
            moment = datetime.now().astimezone()
            touch_lock(lock_path, pid=os.getpid(), now=moment)
            run_once(data_dir, live_path, status_path, now=moment)
            time.sleep(max(1.0, args.interval))
    finally:
        if lock_path.exists():
            try:
                current = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = None
            if isinstance(current, dict) and current.get("pid") == os.getpid():
                lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
