#!/usr/bin/env python3
"""Read-only Production Candidate bridge for AI BRAIN LIVE.

Reads only the Collector HTTP API, writes a research candidate sidecar and
Brain/Shadow presentation JSON. It never changes Collector signals and never
enables real submission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import brain_shadow_live
import ai_shadow_supervisor as shadow

STATE_FILE = "production_candidate_state.json"
SIDECAR_FILE = shadow.CANDIDATE_SIDECAR_FILENAME


def _read_json(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=4) as response:
        if response.status != 200:
            raise RuntimeError("COLLECTOR_HTTP_" + str(response.status))
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("COLLECTOR_PAYLOAD_INVALID")
    if payload.get("real_submit_allowed") is not False:
        raise RuntimeError("REAL_SUBMIT_NOT_FALSE")
    if payload.get("data_conflict") is True:
        raise RuntimeError("DATA_CONFLICT")
    if payload.get("source") != shadow.CANONICAL_SOURCE:
        raise RuntimeError("WRONG_SOURCE")
    return payload


def _candidate_key(row: dict, side: str) -> str:
    return "|".join([
        str(row.get("ticker") or ""),
        side,
        str(row.get("signal") or ""),
        str(row.get("strategy") or ""),
    ])


def _stable_id(root: Path, row: dict, side: str, now: datetime) -> str:
    state_path = root / STATE_FILE
    state = _read_json(state_path) or {}
    session_date = now.date().isoformat()
    key = _candidate_key(row, side)
    if (
        state.get("session_date") == session_date
        and state.get("active_key") == key
        and isinstance(state.get("candidate_id"), str)
        and state.get("candidate_id")
    ):
        return state["candidate_id"]
    raw = session_date + "|" + key + "|" + now.isoformat()
    prefix = "prod" if side in {"LONG", "SHORT"} else "watch"
    candidate_id = prefix + "-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    _atomic_json(state_path, {
        "session_date": session_date,
        "active_key": key,
        "candidate_id": candidate_id,
        "real_submit_allowed": False,
    })
    return candidate_id


def _reset_state(root: Path, now: datetime) -> None:
    _atomic_json(root / STATE_FILE, {
        "session_date": now.date().isoformat(),
        "active_key": None,
        "candidate_id": None,
        "real_submit_allowed": False,
    })


def _build_candidate(payload: dict, root: Path, now: datetime):
    rows = payload.get("all_targets")
    if not isinstance(rows, list):
        return None, None

    for row in rows:
        if not isinstance(row, dict):
            continue
        entry = shadow.entry_candidate(row)
        if entry is None:
            continue
        side = entry["side"]
        candidate_id = _stable_id(root, row, side, now)
        stamp = now.isoformat()
        candidate = {
            "candidate_id": candidate_id,
            "symbol": entry["ticker"],
            "side": side,
            "discovered_at": stamp,
            "entry_candidate_at": stamp,
            "entry_trigger": entry["signal"],
            "price": row.get("price"),
            "price_fresh": True,
            "reason": str(row.get("strategy") or entry["signal"]),
            "candidate_generator": "production_candidate_v1",
            "correlation": row.get("correlation") or "NOT AVAILABLE",
            "lead_lag": row.get("lead_lag") or "NOT AVAILABLE",
            "market_regime": row.get("market_regime") or "NOT AVAILABLE",
            "execution_authority": False,
            "real_submit_allowed": False,
        }
        sidecar = {
            "schema_version": "production-candidate-sidecar-1",
            "candidate_id": candidate_id,
            "symbol": entry["ticker"],
            "side": side,
            "generated_at": stamp,
            "execution_authority": False,
            "real_submit_allowed": False,
        }
        return candidate, sidecar

    for row in rows:
        if not isinstance(row, dict):
            continue
        signal = str(row.get("signal") or "")
        ticker = str(row.get("ticker") or "")
        if not ticker or "準備" not in signal:
            continue
        candidate_id = _stable_id(root, row, "NO-TRADE", now)
        stamp = now.isoformat()
        return {
            "candidate_id": candidate_id,
            "symbol": ticker,
            "side": "NO-TRADE",
            "discovered_at": stamp,
            "entry_candidate_at": stamp,
            "entry_trigger": signal,
            "price": row.get("price"),
            "price_fresh": True,
            "reason": "WATCH ONLY / " + str(row.get("strategy") or signal),
            "candidate_generator": "production_candidate_v1",
            "correlation": row.get("correlation") or "NOT AVAILABLE",
            "lead_lag": row.get("lead_lag") or "NOT AVAILABLE",
            "market_regime": row.get("market_regime") or "NOT AVAILABLE",
            "execution_authority": False,
            "real_submit_allowed": False,
        }, None

    _reset_state(root, now)
    return None, None


def _shadow_positions(data_dir: Path):
    ledger_path = data_dir / "ledger.jsonl"
    if not ledger_path.exists():
        return []
    rows = []
    try:
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    positions, error = shadow.replay_ledger(rows)
    return [] if error else list(positions.values())


def run(args) -> None:
    root = Path(args.brain_root).resolve()
    runtime = Path(args.runtime_dir).resolve()
    shadow_dir = Path(args.shadow_data_dir).resolve()
    sidecar_path = runtime / SIDECAR_FILE
    view_path = root / "brain_shadow_live.json"

    while True:
        now = datetime.now().astimezone()
        try:
            payload = _fetch_json(args.collector_url)
            candidate, sidecar = _build_candidate(payload, root, now)
            if sidecar is None:
                sidecar_path.unlink(missing_ok=True)
            else:
                _atomic_json(sidecar_path, sidecar)

            view = brain_shadow_live.live_view(
                [candidate] if candidate else [],
                [],
                _shadow_positions(shadow_dir),
                {
                    "BASELINE_N": 0,
                    "baseline_by_side": {},
                    "real_submit_allowed": False,
                },
            )
            view["real_submit_allowed"] = False
            view["live_signal_changed"] = False
            _atomic_json(view_path, view)
            print(now.isoformat(), view["brain"]["symbol"], view["brain"]["side"], view["brain"]["candidate_id"], flush=True)
        except Exception as exc:
            sidecar_path.unlink(missing_ok=True)
            print("FAIL-CLOSED", repr(exc), flush=True)
        time.sleep(max(1.0, args.interval))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector-url", default="http://127.0.0.1:28580/")
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--brain-root", required=True)
    parser.add_argument("--shadow-data-dir", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
