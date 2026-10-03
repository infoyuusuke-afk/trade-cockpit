"""P0 market-I/O acceptance harness.

Compares quotes that were already observed. It does not read Excel, RSS, or
the market, and it does not invent prices. A synthetic fixture can prove the
comparator. It cannot satisfy G0–G5 live acceptance.

G0 and G1 stay OWNER_ACTION_PENDING. real_submit_allowed is required false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
MAX_AGE_SECONDS = 60
CANONICAL_SOURCE = "MarketSpeed II RSS / local PC"
CANONICAL_WORKBOOK = "Kioxia_MS2_RSS_Live_Signals.xlsx"
CANONICAL_MODE = "MS2_RSS_WORKBOOK"

GATES = ("G0", "G1", "G2", "G3", "G4", "G5", "G6")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and value not in (float("inf"), float("-inf"))


def _parse_captured(value, tz) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _quote_instant(source_timestamp: str, captured: datetime) -> datetime | None:
    text = source_timestamp.strip()
    absolute = _parse_captured(text, captured.tzinfo)
    if absolute is not None and len(text) > 8:
        return absolute
    try:
        clock = datetime.strptime(text, "%H:%M:%S")
    except ValueError:
        return None
    return captured.replace(hour=clock.hour, minute=clock.minute, second=clock.second, microsecond=0)


def fingerprint(quotes: list[dict]) -> str:
    rows = []
    for quote in quotes:
        rows.append({
            "symbol": quote.get("symbol"),
            "price": quote.get("price"),
            "source_timestamp": quote.get("source_timestamp"),
            "source": quote.get("source"),
        })
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _quote(symbol, price, source_timestamp, source) -> dict:
    return {
        "symbol": symbol if isinstance(symbol, str) else "",
        "price": price,
        "source_timestamp": source_timestamp if isinstance(source_timestamp, str) else "",
        "source": source if isinstance(source, str) else "",
    }


def quotes_from_rows(rows, *, source: str) -> list[dict]:
    found = []
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        found.append(_quote(row.get("symbol") or row.get("ticker"), row.get("price"), row.get("source_timestamp"), row.get("source") or source))
    return found


def quotes_from_live_payload(payload) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    source = payload.get("source") if isinstance(payload.get("source"), str) else ""
    return quotes_from_rows(payload.get("all_targets"), source=source)


def project_strategy_input(payload) -> dict:
    """The only quote tuple a strategy is allowed to read from a live payload."""
    quotes = quotes_from_live_payload(payload)
    return {
        "real_submit_allowed": False,
        "quotes": quotes,
        "derived_from": "collector_or_gateway_payload",
    }


def _envelope_reasons(payload, name: str) -> list[str]:
    reasons = []
    if not isinstance(payload, dict):
        return [name + "_MISSING"]
    if payload.get("real_submit_allowed") is not False:
        reasons.append("REAL_SUBMIT_NOT_FALSE")
    if payload.get("source") != CANONICAL_SOURCE:
        reasons.append(name + "_SOURCE")
    if payload.get("source_mode") != CANONICAL_MODE:
        reasons.append(name + "_SOURCE_MODE")
    if payload.get("stale") is not False:
        reasons.append(name + "_STALE")
    if payload.get("live_values_available") is not True:
        reasons.append(name + "_UNVERIFIED")
    if payload.get("price_source_status") != "OK":
        reasons.append(name + "_MISMATCH")
    if payload.get("data_conflict") is True:
        reasons.append(name + "_DATA_CONFLICT")
    diag = payload.get("live_price_diagnostics")
    if not isinstance(diag, dict) or diag.get("workbook_name") != CANONICAL_WORKBOOK:
        reasons.append(name + "_WORKBOOK")
    if diag.get("real_submit_allowed") is not False if isinstance(diag, dict) else True:
        reasons.append("REAL_SUBMIT_NOT_FALSE")
    return reasons


def _indexed(quotes: list[dict]) -> tuple[dict, list[str]]:
    by_symbol = {}
    reasons = []
    for quote in quotes:
        symbol = quote.get("symbol") or ""
        if not symbol:
            reasons.append("SYMBOL_MISSING")
            continue
        if symbol in by_symbol:
            reasons.append("DUPLICATE_SYMBOL")
        if not _finite(quote.get("price")) or quote.get("price") <= 0:
            reasons.append("PRICE_INVALID")
        by_symbol[symbol] = quote
    return by_symbol, reasons


def _compare_maps(left: dict, right: dict, *, label: str) -> list[str]:
    reasons = []
    if set(left) != set(right):
        reasons.append(label + "_SYMBOL_SET")
        return reasons
    for symbol, quote in left.items():
        other = right[symbol]
        if quote.get("price") != other.get("price"):
            reasons.append("PRICE_MISMATCH")
        if quote.get("source_timestamp") != other.get("source_timestamp"):
            reasons.append("TIMESTAMP_MISMATCH")
        if quote.get("source") != other.get("source") or quote.get("source") != CANONICAL_SOURCE:
            reasons.append("SOURCE_MISMATCH")
    return reasons


def _fresh_reasons(quotes: list[dict], captured: datetime, now: datetime) -> list[str]:
    reasons = []
    if captured.tzinfo is None or now.tzinfo is None:
        return ["TIMESTAMP_NOT_ABSOLUTE"]
    if abs((now - captured).total_seconds()) > MAX_AGE_SECONDS:
        reasons.append("EVIDENCE_STALE")
    for quote in quotes:
        instant = _quote_instant(str(quote.get("source_timestamp") or ""), captured)
        if instant is None:
            reasons.append("TIMESTAMP_UNVERIFIED")
            continue
        age = (captured - instant).total_seconds()
        if age < 0 or age > MAX_AGE_SECONDS:
            reasons.append("QUOTE_STALE")
    return reasons


def evaluate_market_io(bundle, *, now: datetime) -> dict:
    """Return gate statuses. Synthetic input never produces a live PASS."""
    origin = bundle.get("evidence_origin") if isinstance(bundle, dict) else None
    if isinstance(bundle, dict) and bundle.get("generated_by") == "p0_market_io_acceptance.synthetic_bundle":
        origin = "synthetic_fixture"
        bundle = dict(bundle)
        bundle["evidence_origin"] = origin
    report = {
        "schema_version": "p0-market-io-1",
        "evidence_origin": origin,
        "live_acceptance": "NOT_RUN",
        "real_submit_allowed": False,
        "gates": {gate: "NOT_RUN" for gate in GATES},
        "reasons": [],
        "fingerprints": {},
    }
    report["gates"]["G0"] = "OWNER_ACTION_PENDING"
    report["gates"]["G1"] = "OWNER_ACTION_PENDING"
    if origin not in {"synthetic_fixture", "owner_pc_observed"} or not isinstance(bundle, dict):
        report["reasons"].append("EVIDENCE_ABSENT")
        return report

    captured = _parse_captured(bundle.get("captured_at"), JST)
    reasons: list[str] = []
    if captured is None:
        reasons.append("CAPTURED_AT_UNVERIFIED")
        captured = now if now.tzinfo is not None else now.replace(tzinfo=JST)

    rss = quotes_from_rows(bundle.get("rss"), source=CANONICAL_SOURCE)
    collector_payload = bundle.get("collector")
    gateway_payload = bundle.get("gateway")
    reasons.extend(_envelope_reasons(collector_payload, "COLLECTOR"))
    reasons.extend(_envelope_reasons(gateway_payload, "GATEWAY"))
    collector_quotes = quotes_from_live_payload(collector_payload)
    gateway_quotes = quotes_from_live_payload(gateway_payload)
    strategy_payload = bundle.get("strategy_input")
    strategy_explicit = isinstance(strategy_payload, dict) and isinstance(strategy_payload.get("quotes"), list)
    if strategy_explicit:
        if strategy_payload.get("real_submit_allowed") is not False:
            reasons.append("REAL_SUBMIT_NOT_FALSE")
        strategy_quotes = quotes_from_rows(strategy_payload.get("quotes"), source=CANONICAL_SOURCE)
    else:
        strategy_quotes = []
        reasons.append("STRATEGY_INPUT_ABSENT")
    ms2 = bundle.get("ms2_display")
    ms2_quotes = quotes_from_rows(ms2, source=CANONICAL_SOURCE) if isinstance(ms2, list) else []
    if not isinstance(ms2, list):
        reasons.append("MS2_DISPLAY_ABSENT")

    maps = {}
    for name, quotes in (
        ("rss", rss),
        ("collector", collector_quotes),
        ("gateway", gateway_quotes),
        ("strategy_input", strategy_quotes),
        ("ms2_display", ms2_quotes),
    ):
        indexed, index_reasons = _indexed(quotes)
        maps[name] = indexed
        reasons.extend(name.upper() + "_" + item if item in {"SYMBOL_MISSING", "DUPLICATE_SYMBOL", "PRICE_INVALID"} else item for item in index_reasons)
        report["fingerprints"][name] = fingerprint(quotes)

    if rss:
        reasons.extend(_fresh_reasons(rss, captured, now.astimezone(JST) if now.tzinfo else now.replace(tzinfo=JST)))
    else:
        reasons.append("RSS_ABSENT")
    for label in ("collector", "gateway", "strategy_input"):
        reasons.extend(_compare_maps(maps["rss"], maps[label], label=label.upper()))
    if isinstance(ms2, list):
        reasons.extend(_compare_maps(maps["rss"], maps["ms2_display"], label="MS2"))
    unique = sorted(set(reasons))
    report["reasons"] = unique
    consistent = not unique
    report["comparator"] = "MATCH" if consistent else "MISMATCH"

    if origin == "synthetic_fixture":
        report["live_acceptance"] = "NOT_LIVE"
        for gate in ("G2", "G3", "G4", "G5", "G6"):
            report["gates"][gate] = "NOT_LIVE"
        return report

    plane = "DATA_PLANE_PASS" if consistent else "DATA_PLANE_FAIL"
    report["live_acceptance"] = plane
    report["gates"]["G2"] = "PASS" if consistent else "FAIL"
    report["gates"]["G3"] = "PASS" if consistent else "FAIL"
    report["gates"]["G4"] = "PASS" if consistent else "FAIL"
    report["gates"]["G5"] = "NOT_RUN"
    report["gates"]["G6"] = "FAIL" if "REAL_SUBMIT_NOT_FALSE" in unique else "PASS"
    if consistent:
        report["reasons"] = ["G0_G1_STILL_PENDING"]
    return report


def evaluate_resume(previous: dict, current: dict) -> dict:
    """A new snapshot must not resume a failed chain without an agreement mark."""
    origin = current.get("evidence_origin") if isinstance(current, dict) else None
    failed = previous.get("comparator") == "MISMATCH" or previous.get("live_acceptance") == "DATA_PLANE_FAIL" or previous.get("gates", {}).get("G4") == "FAIL"
    marked = isinstance(current, dict) and current.get("agreement_checked") is True
    if origin == "synthetic_fixture":
        status = "NOT_LIVE"
    elif not failed:
        status = "NOT_RUN"
    elif marked:
        status = "PASS"
    else:
        status = "FAIL"
    return {
        "gate": "G5",
        "status": status,
        "reason": "AUTO_RESUME_WITHOUT_AGREEMENT" if status == "FAIL" else "",
        "real_submit_allowed": False,
    }


def synthetic_bundle(*, price: float = 100.0, other_price: float | None = None, captured_at: str = "2026-10-05T09:16:05+09:00") -> dict:
    """Build a fixture. The origin is fixed so it cannot be reported as live."""
    stamp = "09:16:00"
    px = other_price if other_price is not None else price
    row = {"symbol": "TEST", "ticker": "TEST", "price": price, "source_timestamp": stamp, "source": CANONICAL_SOURCE, "data": "LIVE"}
    other = {"symbol": "TEST", "ticker": "TEST", "price": px, "source_timestamp": stamp, "source": CANONICAL_SOURCE, "data": "LIVE"}

    def payload(item):
        return {
            "updated_at": "2026-10-05 09:16:05",
            "source": CANONICAL_SOURCE,
            "source_mode": CANONICAL_MODE,
            "stale": False,
            "data_conflict": False,
            "price_source_status": "OK",
            "live_values_available": True,
            "real_submit_allowed": False,
            "live_price_diagnostics": {"workbook_name": CANONICAL_WORKBOOK, "real_submit_allowed": False, "price_source_status": "OK"},
            "all_targets": [item],
        }

    return {
        "evidence_origin": "synthetic_fixture",
        "generated_by": "p0_market_io_acceptance.synthetic_bundle",
        "captured_at": captured_at,
        "rss": [row],
        "collector": payload(row),
        "gateway": payload(other),
        "strategy_input": {"real_submit_allowed": False, "quotes": [_quote("TEST", px, stamp, CANONICAL_SOURCE)]},
        "ms2_display": [_quote("TEST", px, stamp, CANONICAL_SOURCE)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare an already observed P0 market-I/O bundle")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--resume-from", default="")
    args = parser.parse_args(argv)
    path = Path(args.evidence)
    if not path.exists():
        print("LIVE_ACCEPTANCE=NOT_RUN")
        print("G0=OWNER_ACTION_PENDING")
        print("G1=OWNER_ACTION_PENDING")
        return 2
    bundle = json.loads(path.read_text(encoding="utf-8"))
    report = evaluate_market_io(bundle, now=datetime.now(JST))
    if args.resume_from:
        previous = json.loads(Path(args.resume_from).read_text(encoding="utf-8"))
        resume = evaluate_resume(previous, bundle)
        report["gates"]["G5"] = resume["status"]
        if resume["reason"]:
            report["reasons"] = sorted(set(report["reasons"]) | {resume["reason"]})
    print("LIVE_ACCEPTANCE=" + str(report["live_acceptance"]))
    for gate in GATES:
        print(gate + "=" + str(report["gates"][gate]))
    print("REASONS=" + ",".join(report["reasons"]))
    print("REAL_SUBMIT_ALLOWED=false")
    return 0 if report["live_acceptance"] in {"NOT_LIVE", "NOT_RUN", "DATA_PLANE_PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
