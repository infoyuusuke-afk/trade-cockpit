#!/usr/bin/env python3
"""Read-only loopback acceptance probe for Collector, Gateway and Watcher.

No credentials, orders, broker calls, persistent logs, or outbound connections.
Prints health and mismatch categories only (never quotes, names, account data).
Intended to run on the Owner PC *only after separate authorization*.
"""
import argparse
from datetime import datetime
import json
import math
from urllib.request import urlopen

COLLECTOR = "http://127.0.0.1:28580/live_ms2.json"
GATEWAY = "http://127.0.0.1:28581/health"
WATCHER = "http://127.0.0.1:28582/kioxia_watcher_live.json"


def read_only_json(url, timeout=2):
    if url not in (COLLECTOR, GATEWAY, WATCHER):
        raise ValueError("ONLY_FIXED_LOOPBACK_URLS_ALLOWED")
    with urlopen(url, timeout=timeout) as response:
        if int(response.status) != 200:
            raise ValueError("HTTP_NOT_OK")
        body = response.read(512 * 1024 + 1)
    if len(body) > 512 * 1024:
        raise ValueError("RESPONSE_TOO_LARGE")
    doc = json.loads(body)
    if not isinstance(doc, dict):
        raise ValueError("NOT_JSON_OBJECT")
    return doc


def age_seconds(stamp, now):
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    try:
        parsed = datetime.fromisoformat(stamp.strip().replace(" ", "T"))
        if parsed.tzinfo is None:
            # Local services format timestamps as naive PC-local time.
            if now.tzinfo is not None:
                parsed = parsed.replace(tzinfo=now.tzinfo)
        elif now.tzinfo is None:
            return None
        return (now - parsed).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return None


def finite_price(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def evaluate(collector, gateway, watcher, now):
    """Conservative status without publishing private snapshots."""
    incidents = []
    collector_ok = isinstance(collector, dict) and collector.get("schema_version") == "ms2-common-1.0"
    if not collector_ok:
        incidents.append("COLLECTOR_SCHEMA_OR_CONNECTION")
    else:
        age = age_seconds(collector.get("updated_at"), now)
        valid = collector.get("valid")
        universe = collector.get("universe")
        coverage = (type(valid) is int and type(universe) is int
                    and universe >= 90 and 0 <= valid <= universe
                    and valid >= max(90, math.ceil(universe * 0.9)))
        if age is None or not -5 <= age <= 60:
            incidents.append("COLLECTOR_STALE_OR_CLOCK")
        if not coverage or collector.get("stale") is not False:
            incidents.append("COLLECTOR_COVERAGE_OR_STALE")
    gateway_ok = isinstance(gateway, dict) and gateway.get("status") == "ok" and gateway.get("port") == 28581
    if not gateway_ok:
        incidents.append("GATEWAY_HEALTH_OR_CONNECTION")
    watcher_ok = isinstance(watcher, dict) and watcher.get("schema_version") == "kioxia-watcher-1.0"
    if not watcher_ok:
        incidents.append("WATCHER_SCHEMA_OR_CONNECTION")
    else:
        age = age_seconds(watcher.get("updated_at"), now)
        if age is None or not -5 <= age <= 60:
            incidents.append("WATCHER_STALE_OR_CLOCK")
    if collector_ok and watcher_ok:
        cp = (collector.get("kioxia") or {}).get("price") if isinstance(collector.get("kioxia"), dict) else None
        wp = watcher.get("price")
        if not finite_price(cp) or not finite_price(wp):
            incidents.append("KIOXIA_PRICE_NOT_COMPARABLE")
        elif abs(float(cp) - float(wp)) > 0.01:
            incidents.append("KIOXIA_PRICE_MISMATCH")
    # PASS is diagnostic only, never authorization to place a trade.
    return {
        "status": "PASS" if not incidents else "BLOCKED",
        "incidents": incidents,
        "collector_reachable": collector_ok,
        "gateway_reachable": gateway_ok,
        "watcher_reachable": watcher_ok,
        "runtime_verification_only": True,
        "real_submit_allowed": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only local MS2 acceptance")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    if not 0.2 <= args.timeout <= 5:
        parser.error("timeout must be 0.2..5 seconds")
    from datetime import timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=9)))
    docs = []
    for address in (COLLECTOR, GATEWAY, WATCHER):
        try:
            docs.append(read_only_json(address, args.timeout))
        except (OSError, ValueError, json.JSONDecodeError):
            docs.append(None)
    print(json.dumps(evaluate(*docs, now), ensure_ascii=False, sort_keys=True))
    return 0 if all(doc is not None for doc in docs) and evaluate(*docs, now)["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
