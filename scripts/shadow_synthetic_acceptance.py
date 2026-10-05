"""Synthetic replay of one AI SHADOW round trip.

The printed result is SYNTHETIC_ACCEPTANCE. It is not a LIVE pass.
real_submit_allowed stays false. Entry rules are unchanged.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ai_shadow_supervisor as shadow
import shadow_live_observation as observation

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 2, 9, 16, 5, tzinfo=JST)


def _diag(**overrides):
    payload = {
        "price_source_status": "OK",
        "source_mode": "MS2_RSS_WORKBOOK",
        "workbook_name": "Kioxia_MS2_RSS_Live_Signals.xlsx",
        "data_conflict": False,
        "duplicate_collector": False,
        "duplicate_watcher": False,
        "collector_count": 1,
        "watcher_count": 1,
        "stale_reason": "",
        "real_submit_allowed": False,
    }
    payload.update(overrides)
    return payload


def _live(rows, updated_at="2026-10-02 09:16:05", **overrides):
    payload = {
        "updated_at": updated_at,
        "source": "MarketSpeed II RSS / local PC",
        "source_mode": "MS2_RSS_WORKBOOK",
        "stale": False,
        "data_conflict": False,
        "price_source_status": "OK",
        "live_values_available": True,
        "real_submit_allowed": False,
        "live_price_diagnostics": _diag(),
        "all_targets": rows,
    }
    payload.update(overrides)
    return payload


def _row(**overrides):
    row = {
        "ticker": "285A.T",
        "signal": "買いサイン",
        "strategy": "OR15",
        "price": 19120.0,
        "entry_price": 19120.0,
        "stop_price": 19000.0,
        "target1": 19240.0,
        "target2": 19360.0,
        "source_timestamp": "09:16:00",
        "data": "LIVE",
        "bid": 19110.0,
        "ask": 19130.0,
    }
    row.update(overrides)
    return row


def _cycle(engine, payload, now, data_dir: Path):
    verdict = shadow.assess_live_payload(payload, file_mtime=now, now=now)
    return shadow.apply_cycle(
        engine,
        payload,
        verdict,
        now=now,
        data_dir=data_dir,
        acceptance_class="synthetic",
    )


def run_synthetic_acceptance(data_dir: Path, *, now: datetime = NOW) -> dict:
    """Replay entry, fill, exit, restart, and fail-closed cases in one temp ledger."""
    engine = shadow.load_engine(data_dir, now=now)
    entry = _live([_row()])
    _cycle(engine, entry, now, data_dir)
    _cycle(engine, entry, now + timedelta(seconds=1), data_dir)
    down_at = now + timedelta(seconds=10)
    _cycle(engine, _live([_row(price=19050.0)], updated_at="2026-10-02 09:16:15"), down_at, data_dir)
    up_at = now + timedelta(seconds=20)
    _cycle(engine, _live([_row(price=19300.0)], updated_at="2026-10-02 09:16:25"), up_at, data_dir)
    flat_at = now + timedelta(seconds=30)
    flat = _live([_row(signal="監視", price=19180.0, bid=19170.0, ask=19190.0)], updated_at="2026-10-02 09:16:35")
    _cycle(engine, flat, flat_at, data_dir)
    _cycle(engine, flat, flat_at + timedelta(seconds=1), data_dir)
    loss_at = flat_at + timedelta(seconds=20)
    loss = _live([_row(price=100.0, entry_price=100.0, stop_price=90.0, bid=100.0, ask=100.0)], updated_at="2026-10-02 09:16:55")
    _cycle(engine, loss, loss_at, data_dir)
    loss_exit_at = loss_at + timedelta(seconds=10)
    loss_exit = _live([_row(signal="監視", price=90.0, bid=90.0, ask=90.0)], updated_at="2026-10-02 09:17:05")
    _cycle(engine, loss_exit, loss_exit_at, data_dir)

    restarted = shadow.load_engine(data_dir, now=loss_exit_at + timedelta(seconds=5))
    _cycle(restarted, loss_exit, loss_exit_at + timedelta(seconds=5), data_dir)
    exits_after_restart = [event for event in restarted["ledger"] if event.get("event_type") == "virtual_exit"]
    entries_after_restart = [event for event in restarted["ledger"] if event.get("event_type") == "virtual_entry"]

    stale_at = loss_exit_at + timedelta(seconds=40)
    before = len(restarted["ledger"])
    stale = _live([_row(price=1.0)], updated_at="2026-10-02 08:00:00")
    stale["live_price_diagnostics"] = _diag(stale_reason="WRONG_SYMBOL_MAPPING")
    _cycle(restarted, stale, stale_at, data_dir)
    duplicate = _live([_row(), _row()])
    duplicate["live_price_diagnostics"] = _diag(collector_count=2, duplicate_collector=True)
    _cycle(restarted, duplicate, stale_at + timedelta(seconds=5), data_dir)
    blocked = len(restarted["ledger"]) == before and restarted["state"]["state"] == "PAUSED_FAIL_CLOSED"

    closed = [event for event in restarted["ledger"] if event.get("event_type") == "virtual_exit"][0]
    stats = json.loads((data_dir / "shadow_performance.json").read_text(encoding="utf-8"))
    synthetic = all(event.get("acceptance_class") == "synthetic" for event in restarted["ledger"])
    metrics = (
        closed.get("fill_entry_price") == 19130.0
        and closed.get("fill_exit_price") == 19170.0
        and closed.get("fill_pnl_per_share_yen") == 40.0
        and closed.get("slippage_yen") == 20.0
        and closed.get("mae_yen") == 80.0
        and closed.get("mfe_yen") == 170.0
        and closed.get("fill_model") == "collector_quote_simulation"
        and isinstance(closed.get("decision_rationale"), str)
        and closed.get("decision_rationale")
        and closed.get("quantity") is None
        and closed.get("real_submit_allowed") is False
        and stats.get("expectancy_yen_per_share") == 15.0
        and stats.get("profit_factor") == 4.0
        and stats.get("avg_mae_yen") == 45.0
        and stats.get("avg_mfe_yen") == 85.0
        and stats.get("avg_slippage_yen") == 10.0
        and stats.get("real_submit_allowed") is False
        and len(entries_after_restart) == 2
        and len(exits_after_restart) == 2
        and synthetic
        and blocked
    )
    judged = observation.classify_observation(
        {"state": "RUNNING", "updated_at": now.isoformat(), "real_submit_allowed": False},
        {"heartbeat_at": now.isoformat(), "real_submit_allowed": False},
        entry,
        restarted["ledger"],
        now=now,
    )
    return {
        "ok": bool(metrics and judged["live_roundtrip"] == "NOT_RUN/SYNTHETIC_LEDGER"),
        "live_roundtrip": judged["live_roundtrip"],
        "real_submit_allowed": False,
    }


def format_report(result: dict) -> str:
    status = "PASS" if result["ok"] else "FAIL"
    return "\n".join([
        "SYNTHETIC_ACCEPTANCE=" + status,
        "LIVE_ROUNDTRIP=" + str(result["live_roundtrip"]),
        "REAL_SUBMIT_ALLOWED=0",
    ])


def main(argv: list[str] | None = None) -> int:
    del argv
    with tempfile.TemporaryDirectory(prefix="shadow-synthetic-") as temp:
        result = run_synthetic_acceptance(Path(temp))
    print(format_report(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
