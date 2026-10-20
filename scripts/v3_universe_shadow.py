"""Offline, read-only inputs and private v3 universe Shadow observation.

NEVER imports a broker, touches MS2/Excel/V10, fetches the network, or
writes a repository data file. This is NOT a trading or execution engine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path

SCHEMA = "v3-universe-shadow-1"
SOURCE_TYPES = {"SYNTHETIC", "MS2_LOCAL"}
ROLE_LIMITS = {"A": 25, "B": 8, "C": 40, "D": 8}
INSTRUMENT_TYPES = {"EQUITY", "INDEX", "FUTURE", "SECTOR_PROXY"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{2,48}$")
ROOT = Path(__file__).resolve().parents[1]


class ShadowReject(ValueError):
    """Fail-closed input or output rejection."""


def _time(value):
    if not isinstance(value, str):
        raise ShadowReject("TIME_MISSING")
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowReject("TIME_INVALID") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ShadowReject("TIME_OFFSET_REQUIRED")
    return t


def _nonnegative(value, kind):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ShadowReject("INVALID_" + kind)
    if not math.isfinite(float(value)) or value < 0:
        raise ShadowReject("INVALID_" + kind)
    if kind.endswith("_YEN") and not isinstance(value, int):
        raise ShadowReject("INTEGER_REQUIRED_" + kind)
    return value


def _digest(doc):
    data = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_snapshot(doc):
    if not isinstance(doc, dict) or doc.get("schema_version") != "v3-universe-input-1":
        raise ShadowReject("SCHEMA_INVALID")
    at = _time(doc.get("selection_at"))
    source = doc.get("input_source")
    if source not in SOURCE_TYPES:
        raise ShadowReject("SOURCE_UNAUTHORIZED")
    if source == "MS2_LOCAL" and doc.get("rights_verified") is not True:
        raise ShadowReject("RIGHTS_NOT_ATTESTED")
    sid = doc.get("session_id")
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", sid):
        raise ShadowReject("SESSION_ID_INVALID")
    src = doc.get("rows")
    if not isinstance(src, list) or len(src) > 5000:
        raise ShadowReject("ROWS_INVALID")
    counts = {key: 0 for key in ROLE_LIMITS}
    seen = set()
    records = []
    for raw in src:
        if not isinstance(raw, dict):
            raise ShadowReject("ROW_INVALID")
        ident = raw.get("instrument_id")
        if not isinstance(ident, str) or not ID_PATTERN.fullmatch(ident):
            raise ShadowReject("INSTRUMENT_ID_INVALID")
        if ident in seen:
            raise ShadowReject("DUPLICATE_INSTRUMENT")
        seen.add(ident)
        instrument_type = raw.get("instrument_type")
        if instrument_type not in INSTRUMENT_TYPES:
            raise ShadowReject("INSTRUMENT_TYPE_INVALID")
        roles = raw.get("roles")
        if not isinstance(roles, list) or not roles or len(set(map(str, roles))) != len(roles):
            raise ShadowReject("ROLES_INVALID")
        if any(role not in ROLE_LIMITS for role in roles):
            raise ShadowReject("ROLE_UNKNOWN")
        if instrument_type != "EQUITY" and any(role != "A" for role in roles):
            raise ShadowReject("NON_EQUITY_NOT_TRADE_CANDIDATE")
        if type(raw.get("selected")) is not bool:
            raise ShadowReject("SELECTED_BOOL_REQUIRED")
        observed = _time(raw.get("observed_at"))
        available = _time(raw.get("available_at"))
        if observed > available or available > at:
            raise ShadowReject("LOOKAHEAD_OR_BAD_LINEAGE")
        for role in roles:
            counts[role] += 1
            if counts[role] > ROLE_LIMITS[role]:
                raise ShadowReject("ROLE_CAP_EXCEEDED_" + role)
        turnover = _nonnegative(raw.get("prior_day_trading_value_yen"), "TURNOVER_YEN")
        spread = _nonnegative(raw.get("spread_bps"), "SPREAD_BPS")
        bid = _nonnegative(raw.get("bid_depth_yen"), "BID_DEPTH_YEN")
        ask = _nonnegative(raw.get("ask_depth_yen"), "ASK_DEPTH_YEN")
        cap = (turnover // 100) if turnover is not None and instrument_type == "EQUITY" else None
        records.append({
            "instrument_id": ident,
            "instrument_type": instrument_type,
            "roles": sorted(roles),
            "selected": raw["selected"],
            "observed_at": observed.isoformat(),
            "available_at": available.isoformat(),
            "prior_day_trading_value_yen": turnover,
            "turnover_one_percent_cap_yen": cap,
            "spread_bps": spread,
            "bid_depth_yen": bid,
            "ask_depth_yen": ask,
            "execution_capacity_verified": False,
        })
    rows = sorted(records, key=lambda x: x["instrument_id"])
    snapshot = {
        "schema_version": SCHEMA,
        "selection_at": at.isoformat(),
        "source_kind": source,
        "rights_attestation_only": source == "MS2_LOCAL",
        "session_id": sid,
        "real_submit_allowed": False,
        "research_only": True,
        "role_assignment_counts": counts,
        "unique_instrument_count": len(rows),
        "selected_equity_count": sum(r["selected"] and r["instrument_type"] == "EQUITY" for r in rows),
        "rows": rows,
        "forward_comparison": None,
        "realized_net_profit": None,
    }
    snapshot["snapshot_sha256"] = _digest(snapshot)
    return snapshot


def compare_outcomes(snapshot, outcomes):
    if not isinstance(outcomes, dict) or outcomes.get("schema_version") != "v3-universe-outcomes-1":
        raise ShadowReject("OUTCOME_SCHEMA_INVALID")
    data = outcomes.get("rows")
    if not isinstance(data, list):
        raise ShadowReject("OUTCOME_ROWS_INVALID")
    by_id = {row["instrument_id"]: row for row in snapshot["rows"] if row["instrument_type"] == "EQUITY"}
    selected_at = _time(snapshot["selection_at"])
    seen = set()
    results = {True: [], False: []}
    for item in data:
        if not isinstance(item, dict):
            raise ShadowReject("OUTCOME_INVALID")
        name = item.get("instrument_id")
        if name not in by_id or name in seen:
            raise ShadowReject("OUTCOME_DUPLICATE_OR_UNKNOWN")
        seen.add(name)
        end = _time(item.get("horizon_end_at"))
        available = _time(item.get("available_at"))
        if not (selected_at < end <= available):
            raise ShadowReject("OUTCOME_TIME_INVALID")
        value = item.get("return_pct")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ShadowReject("OUTCOME_RETURN_INVALID")
        results[by_id[name]["selected"]].append(float(value))
    summary = {}
    for selected, label in ((True, "selected"), (False, "unselected")):
        nums = results[selected]
        total = sum(row["selected"] == selected for row in by_id.values())
        summary[label] = {
            "eligible": total,
            "observed": len(nums),
            "missing": total - len(nums),
            "mean_return_pct": round(sum(nums) / len(nums), 6) if nums else None,
            "mean_absolute_return_pct": round(sum(map(abs, nums)) / len(nums), 6) if nums else None,
        }
    return {
        "observation_only": True,
        "costs_verified": False,
        "fills_verified": False,
        "net_expectancy": None,
        "comparison": summary,
    }


def _private_output(path):
    p = Path(path).resolve()
    if p == ROOT or ROOT in p.parents:
        raise ShadowReject("GIT_REPOSITORY_OUTPUT_FORBIDDEN")
    if p.suffix.lower() != ".json" or not p.parent.is_dir() or p.is_symlink():
        raise ShadowReject("OUTPUT_PATH_INVALID")
    return p


def write_private_snapshot(path, snap):
    p = _private_output(path)
    payload = dict(snap)
    checksum = payload.pop("snapshot_sha256", None)
    if _digest(payload) != checksum:
        raise ShadowReject("SNAPSHOT_DIGEST_INVALID")
    content = json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        raise  # Do not erase potentially partial evidence on failure.
    if json.loads(p.read_text(encoding="utf-8")) != snap:
        raise ShadowReject("INDEPENDENT_READBACK_MISMATCH")
    return checksum


def main():
    parser = argparse.ArgumentParser(description="Offline v3 universe Shadow; NO runtime integration")
    parser.add_argument("--input", required=True, help="private local JSON, NEVER commit")
    parser.add_argument("--output", required=True, help="new private JSON outside Git repository")
    parser.add_argument("--outcomes", help="optional private, post-decision outcome observations")
    args = parser.parse_args()
    doc = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = build_snapshot(doc)
    if args.outcomes:
        outcomes = json.loads(Path(args.outcomes).read_text(encoding="utf-8"))
        result["forward_comparison"] = compare_outcomes(result, outcomes)
        result.pop("snapshot_sha256")
        result["snapshot_sha256"] = _digest(result)
    checksum = write_private_snapshot(args.output, result)
    print(json.dumps({
        "status": "SYNTHETIC_PASS" if result["source_kind"] == "SYNTHETIC" else "OWNER_ATTESTED_PRIVATE_RECORD",
        "unique_count": result["unique_instrument_count"],
        "role_counts": result["role_assignment_counts"],
        "snapshot_sha256": checksum,
        "real_submit_allowed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
