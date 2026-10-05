"""Collector, Gateway, Strategy Input, and AI SHADOW must share one 285A price.

This check does not start Excel, MarketSpeed II, or the Collector, and it
does not call an order function. real_submit_allowed stays false.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ai_shadow_supervisor as shadow
from p0_market_io_acceptance import project_strategy_input

IDENTITY = "285A.T"


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and value not in (float("inf"), float("-inf"))


def _diag(payload):
    if not isinstance(payload, dict):
        return None
    diag = payload.get("live_price_diagnostics")
    return diag if isinstance(diag, dict) else None


def _identity_row(payload):
    rows = payload.get("all_targets") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None, "STRATEGY_QUOTE_MISSING"
    found = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol") or row.get("ticker")
        if symbol != IDENTITY:
            continue
        if found is not None:
            return None, "DUPLICATE_SYMBOL"
        found = row
    if found is None:
        return None, "STRATEGY_QUOTE_MISSING"
    return found, ""


def evaluate_chain(collector, gateway, *, now: datetime, file_mtime: datetime) -> dict:
    """Return whether one 285A price reached strategy input and shadow."""
    reasons = []
    if collector is None or gateway is None:
        reasons.append("MISSING_PAYLOAD")
    collector_diag = _diag(collector)
    gateway_diag = _diag(gateway)
    if collector_diag is None or gateway_diag is None:
        reasons.append("MISSING_PRICE_DIAGNOSTICS")
    symbol = gateway_diag.get("symbol") if gateway_diag else None
    price = gateway_diag.get("current_price") if gateway_diag else None
    stamp = gateway_diag.get("source_timestamp") if gateway_diag else None
    if symbol != IDENTITY or (collector_diag and collector_diag.get("symbol") != IDENTITY):
        reasons.append("WRONG_SYMBOL_MAPPING")
    if collector_diag and gateway_diag:
        if collector_diag.get("current_price") != price or not _finite(price) or price <= 0:
            reasons.append("COLLECTOR_GATEWAY_PRICE_MISMATCH")
        if collector_diag.get("source_timestamp") != stamp or not isinstance(stamp, str) or not stamp:
            reasons.append("TIMESTAMP_MISMATCH")
        for diag in (collector_diag, gateway_diag):
            if diag.get("collector_count") != 1 or diag.get("duplicate_collector") is True:
                reasons.append("DUPLICATE_COLLECTOR")
            if diag.get("price_source_status") != "OK":
                reasons.append("PRICE_SOURCE_MISMATCH")
            if diag.get("workbook_identity_verified") is not True:
                reasons.append("WRONG_SOURCE_WORKBOOK")
            if diag.get("real_submit_allowed") is not False:
                reasons.append("REAL_SUBMIT_NOT_FALSE")
    for payload in (collector, gateway):
        if isinstance(payload, dict) and payload.get("real_submit_allowed") is not False:
            reasons.append("REAL_SUBMIT_NOT_FALSE")
        if isinstance(payload, dict) and payload.get("live_values_available") is not True:
            reasons.append("LIVE_VALUES_UNAVAILABLE")
        if isinstance(payload, dict) and payload.get("stale") is not False:
            reasons.append("STALE_OR_MISSING_TIMESTAMP")

    strategy_price = None
    if isinstance(gateway, dict):
        projected = project_strategy_input(gateway)
        if projected.get("real_submit_allowed") is not False:
            reasons.append("REAL_SUBMIT_NOT_FALSE")
        row, row_reason = _identity_row(gateway)
        if row_reason:
            reasons.append(row_reason)
        elif row.get("price") != price or row.get("source_timestamp") != stamp:
            reasons.append("STRATEGY_PRICE_MISMATCH")
        else:
            strategy_price = row.get("price")
            quotes = [item for item in projected.get("quotes") or [] if item.get("symbol") == IDENTITY]
            if len(quotes) != 1 or quotes[0].get("price") != price:
                reasons.append("STRATEGY_PRICE_MISMATCH")

    shadow_state = "PAUSED_FAIL_CLOSED"
    if isinstance(gateway, dict):
        verdict = shadow.assess_live_payload(gateway, file_mtime=file_mtime, now=now)
        if not verdict.get("ok"):
            reasons.extend(verdict.get("reasons") or ["SHADOW_REJECTED"])
        if verdict.get("real_submit_allowed") is not False:
            reasons.append("REAL_SUBMIT_NOT_FALSE")
        with tempfile.TemporaryDirectory(prefix="shadow-penetration-") as temp:
            data = Path(temp)
            engine = shadow.load_engine(data, now=now)
            engine = shadow.apply_cycle(engine, gateway, verdict, now=now, data_dir=data)
        shadow_state = str(engine.get("state", {}).get("state") or "")
        if engine.get("state", {}).get("real_submit_allowed") is not False:
            reasons.append("REAL_SUBMIT_NOT_FALSE")
        if verdict.get("ok") and shadow_state == "PAUSED_FAIL_CLOSED":
            reasons.append(str(engine.get("state", {}).get("reason") or "SHADOW_REJECTED"))

    unique = sorted(set(reasons))
    return {
        "ok": not unique,
        "reasons": unique,
        "symbol": IDENTITY if symbol == IDENTITY else symbol,
        "price": price,
        "strategy_price": strategy_price,
        "shadow_state": shadow_state,
        "real_submit_allowed": False,
    }


def _load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check one 285A price across collector, gateway, strategy, and shadow")
    parser.add_argument("--collector", required=True)
    parser.add_argument("--gateway", required=True)
    args = parser.parse_args(argv)
    now = datetime.now().astimezone()
    gateway_path = Path(args.gateway)
    result = evaluate_chain(
        _load(args.collector),
        _load(args.gateway),
        now=now,
        file_mtime=datetime.fromtimestamp(gateway_path.stat().st_mtime, tz=now.tzinfo),
    )
    if result["ok"]:
        print("SHADOW_PENETRATION=PASS")
        print("SYMBOL=" + str(result["symbol"]))
        print("PRICE=" + str(result["price"]))
        print("STRATEGY_PRICE=" + str(result["strategy_price"]))
        print("SHADOW_STATE=" + str(result["shadow_state"]))
        print("REAL_SUBMIT_ALLOWED=0")
        return 0
    print("SHADOW_PENETRATION=FAIL")
    print("REASONS=" + ",".join(result["reasons"]))
    print("REAL_SUBMIT_ALLOWED=0")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
