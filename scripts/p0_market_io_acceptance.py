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


def _has_explicit_offset(text: str) -> bool:
    body = text.strip()
    if body.endswith("Z") or body.endswith("z"):
        return True
    return "+" in body[10:] or "-" in body[10:]


def quote_clock(quote: dict) -> tuple[datetime | None, str]:
    """Absolute quote time only from the quote itself.

    HH:mm:ss is what Get-TimeText publishes. The collector clock date and the
    evidence captured_at date are not an RSS date, so they are not attached.
    A date is usable only when quote_date_source is rss_cell.
    """
    text = str(quote.get("source_timestamp") or "").strip()
    if _has_explicit_offset(text):
        parsed = _parse_captured(text, JST)
        if parsed is not None:
            return parsed, "VERIFIED"
        return None, "UNVERIFIED"
    if quote.get("quote_date_source") != "rss_cell":
        return None, "UNVERIFIED"
    day_text = quote.get("quote_date")
    if not isinstance(day_text, str):
        return None, "UNVERIFIED"
    try:
        clock = datetime.strptime(text, "%H:%M:%S")
        day = datetime.strptime(day_text, "%Y-%m-%d")
    except ValueError:
        return None, "UNVERIFIED"
    return day.replace(hour=clock.hour, minute=clock.minute, second=clock.second, tzinfo=JST), "VERIFIED"


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


def _quote(symbol, price, source_timestamp, source, *, quote_date=None, quote_date_source=None) -> dict:
    quote = {
        "symbol": symbol if isinstance(symbol, str) else "",
        "price": price,
        "source_timestamp": source_timestamp if isinstance(source_timestamp, str) else "",
        "source": source if isinstance(source, str) else "",
    }
    if isinstance(quote_date, str):
        quote["quote_date"] = quote_date
    if isinstance(quote_date_source, str):
        quote["quote_date_source"] = quote_date_source
    return quote


def quotes_from_rows(rows, *, source: str) -> list[dict]:
    found = []
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict):
            continue
        found.append(_quote(
            row.get("symbol") or row.get("ticker"),
            row.get("price"),
            row.get("source_timestamp"),
            row.get("source") or source,
            quote_date=row.get("quote_date"),
            quote_date_source=row.get("quote_date_source"),
        ))
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


def _fresh_reasons(quotes: list[dict], captured: datetime | None, now: datetime) -> tuple[list[str], str]:
    reasons = []
    freshness = "VERIFIED"
    if now.tzinfo is None:
        return ["TIMESTAMP_NOT_ABSOLUTE"], "UNVERIFIED"
    if captured is None or not _has_explicit_offset(str(captured.isoformat())):
        reasons.append("CAPTURED_AT_UNVERIFIED")
        freshness = "UNVERIFIED"
    elif abs((now - captured).total_seconds()) > MAX_AGE_SECONDS:
        reasons.append("EVIDENCE_STALE")
        freshness = "STALE"
    for quote in quotes:
        instant, state = quote_clock(quote)
        if state != "VERIFIED" or instant is None:
            reasons.append("TIMESTAMP_UNVERIFIED")
            freshness = "UNVERIFIED"
            continue
        if captured is not None and _has_explicit_offset(str(captured.isoformat())):
            age = (captured - instant).total_seconds()
            if age < 0 or age > MAX_AGE_SECONDS:
                reasons.append("QUOTE_STALE")
                if freshness != "UNVERIFIED":
                    freshness = "STALE"
    return reasons, freshness


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

    captured_text = bundle.get("captured_at") if isinstance(bundle.get("captured_at"), str) else ""
    captured = _parse_captured(captured_text, JST) if _has_explicit_offset(captured_text) else None
    reasons: list[str] = []

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

    moment = now.astimezone(JST) if now.tzinfo else now.replace(tzinfo=JST)
    if rss:
        fresh_reasons, freshness = _fresh_reasons(rss, captured, moment)
        reasons.extend(fresh_reasons)
    else:
        fresh_reasons, freshness = [], "UNVERIFIED"
        reasons.append("RSS_ABSENT")
    report["freshness"] = freshness
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _observation_gate(payload, gate: str) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "OWNER_ACTION_PENDING", ""
    if payload.get("generated_by") == "p0_market_io_acceptance.synthetic_bundle" or payload.get("evidence_origin") != "owner_pc_observed":
        return "NOT_LIVE", "SYNTHETIC_OBSERVATION"
    if payload.get("real_submit_allowed") is not False:
        return "FAIL", "REAL_SUBMIT_NOT_FALSE"
    if gate == "G0":
        if payload.get("workbook_open") is True and payload.get("dialog_visible") is False:
            return "PASS", ""
        return "FAIL", "WORKBOOK_NOT_OPEN"
    if payload.get("rss_updated") is True:
        return "PASS", ""
    return "FAIL", "RSS_NOT_UPDATING"


def run_acceptance(run_dir: Path, out_dir: Path, *, now: datetime) -> dict:
    """Judge files that already exist. Missing files stay NOT_RUN, never PASS.

    This does not start Excel, read a dialog, or copy a price by hand.
    """
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    names = {
        "rss_rows": run_dir / "rss_rows.json",
        "collector": run_dir / "live_ms2.json",
        "gateway": run_dir / "gateway_live.json",
        "ms2_display": run_dir / "ms2_display.json",
        "g0": run_dir / "g0_observation.json",
        "g1": run_dir / "g1_observation.json",
    }
    inputs = []
    for name, path in names.items():
        if path.exists() and path.is_file():
            inputs.append({"name": name, "sha256": _sha256(path), "bytes": path.stat().st_size})
    present = {item["name"] for item in inputs}
    g0_payload = _read_json(names["g0"]) if "g0" in present else None
    g1_payload = _read_json(names["g1"]) if "g1" in present else None
    g0, g0_reason = _observation_gate(g0_payload, "G0")
    g1, g1_reason = _observation_gate(g1_payload, "G1")
    market_present = present & {"rss_rows", "collector", "gateway", "ms2_display"}
    if not market_present:
        report = {
            "schema_version": "p0-market-io-1",
            "evidence_origin": None,
            "live_acceptance": "NOT_RUN",
            "real_submit_allowed": False,
            "freshness": "UNVERIFIED",
            "comparator": "NOT_RUN",
            "gates": {gate: "NOT_RUN" for gate in GATES},
            "reasons": ["MARKET_FILES_ABSENT"],
            "fingerprints": {},
        }
    else:
        collector = _read_json(names["collector"]) if "collector" in present else None
        gateway = _read_json(names["gateway"]) if "gateway" in present else None
        rss_rows = _read_json(names["rss_rows"]) if "rss_rows" in present else None
        ms2_rows = _read_json(names["ms2_display"]) if "ms2_display" in present else None
        captured = ""
        if isinstance(collector, dict) and _has_explicit_offset(str(collector.get("updated_at") or "")):
            captured = str(collector.get("updated_at"))
        bundle = {
            "evidence_origin": "owner_pc_observed",
            "captured_at": captured,
            "rss": rss_rows if isinstance(rss_rows, list) else [],
            "collector": collector,
            "gateway": gateway,
            "strategy_input": project_strategy_input(collector) if isinstance(collector, dict) else None,
            "ms2_display": ms2_rows if isinstance(ms2_rows, list) else None,
        }
        if isinstance(collector, dict) and collector.get("generated_by") == "p0_market_io_acceptance.synthetic_bundle":
            bundle["generated_by"] = collector["generated_by"]
        report = evaluate_market_io(bundle, now=now)
        if "rss_rows" not in present:
            report["gates"]["G2"] = "NOT_RUN"
            report["reasons"] = sorted(set(report["reasons"]) | {"RSS_INDEPENDENT_OBSERVATION_ABSENT"})
            if report["live_acceptance"] == "DATA_PLANE_PASS":
                report["live_acceptance"] = "DATA_PLANE_FAIL"
        if "gateway" not in present:
            report["gates"]["G3"] = "NOT_RUN"
        if "ms2_display" not in present:
            report["gates"]["G4"] = "NOT_RUN" if "collector" not in present else "FAIL"
    report["gates"]["G0"] = g0
    report["gates"]["G1"] = g1
    if g0_reason:
        report["reasons"] = sorted(set(report.get("reasons") or []) | {g0_reason})
    if g1_reason:
        report["reasons"] = sorted(set(report.get("reasons") or []) | {g1_reason})
    previous_path = out_dir / "latest_evidence.json"
    if previous_path.exists():
        previous = _read_json(previous_path)
        resume = evaluate_resume(previous.get("report") or previous, {"evidence_origin": report.get("evidence_origin"), "agreement_checked": False})
        if resume["status"] != "NOT_RUN":
            report["gates"]["G5"] = resume["status"]
            if resume["reason"]:
                report["reasons"] = sorted(set(report["reasons"]) | {resume["reason"]})
    digest = hashlib.sha256("".join(item["sha256"] for item in inputs).encode("utf-8")).hexdigest()
    evidence = {
        "schema_version": "p0-evidence-1",
        "run_id": digest,
        "real_submit_allowed": False,
        "inputs": inputs,
        "report": report,
    }
    body = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2)
    target = out_dir / ("evidence-" + digest + ".json")
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(target)
    latest = out_dir / "latest_evidence.json"
    latest_tmp = latest.with_suffix(".json.tmp")
    latest_tmp.write_text(body, encoding="utf-8")
    latest_tmp.replace(latest)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare an already observed P0 market-I/O bundle")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--resume-from", default="")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if args.run_dir:
        if not args.out:
            print("OUT_REQUIRED")
            return 2
        evidence = run_acceptance(Path(args.run_dir), Path(args.out), now=datetime.now(JST))
        report = evidence["report"]
        print("RUN_ID=" + evidence["run_id"])
        print("LIVE_ACCEPTANCE=" + str(report["live_acceptance"]))
        for gate in GATES:
            print(gate + "=" + str(report["gates"][gate]))
        print("REASONS=" + ",".join(report.get("reasons") or []))
        print("REAL_SUBMIT_ALLOWED=false")
        if report["live_acceptance"] == "NOT_RUN":
            return 2
        return 0 if report["live_acceptance"] in {"NOT_LIVE", "DATA_PLANE_PASS"} else 1
    if not args.evidence:
        print("EVIDENCE_OR_RUN_DIR_REQUIRED")
        return 2
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
