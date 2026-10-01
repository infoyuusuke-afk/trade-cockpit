"""Dynamic Active100, NEXT20, and NEXT5.

Membership is not a fixed symbol list. A scheduled morning or afternoon
pass rebuilds the top of the discovery ranking. Between those passes the
set stays put, except an intraday emergency promotion.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.next_foundation.score import selection_value


def classify_selection(as_of: str, mode: str | None, config: dict) -> dict:
    sessions = config["sessions"]
    if mode in ("scheduled_morning", "scheduled_afternoon", "intraday", "outside_session"):
        kind = {
            "scheduled_morning": "SCHEDULED_MORNING",
            "scheduled_afternoon": "SCHEDULED_AFTERNOON",
            "intraday": "INTRADAY",
            "outside_session": "OUTSIDE_SESSION",
        }[mode]
        return {
            "selection_kind": kind,
            "session_open": kind in ("SCHEDULED_MORNING", "SCHEDULED_AFTERNOON", "INTRADAY"),
            "rebuild": kind != "INTRADAY",
            "allow_emergency": kind == "INTRADAY",
        }
    observed = datetime.fromisoformat(as_of)
    if observed.tzinfo is None:
        raise ValueError("as_of must include a timezone offset")
    clock = observed.astimezone(ZoneInfo(sessions["timezone"]))
    hm = clock.strftime("%H:%M")
    morning = sessions["morning"]
    afternoon = sessions["afternoon"]
    if hm in set(morning["reselect_at"]):
        return {"selection_kind": "SCHEDULED_MORNING", "session_open": True, "rebuild": True, "allow_emergency": False}
    if hm in set(afternoon["reselect_at"]):
        return {"selection_kind": "SCHEDULED_AFTERNOON", "session_open": True, "rebuild": True, "allow_emergency": False}
    if _in_window(hm, morning) or _in_window(hm, afternoon):
        return {"selection_kind": "INTRADAY", "session_open": True, "rebuild": False, "allow_emergency": True}
    return {"selection_kind": "OUTSIDE_SESSION", "session_open": False, "rebuild": True, "allow_emergency": False}


def _in_window(hm: str, window: dict) -> bool:
    return window["start"] <= hm <= window["end"]


def rank_rows(rows: list[dict]) -> None:
    ordered = sorted(
        [row for row in rows if row.get("market_score") is not None],
        key=lambda row: (-row["market_score"], row["symbol"]),
    )
    for index, row in enumerate(ordered, start=1):
        row["rank"] = index
    for row in rows:
        if row.get("market_score") is None:
            row["rank"] = None


def attach_rank_velocity(row: dict, as_of: str) -> None:
    history = row.get("rank_history") or []
    path = []
    previous = None
    previous_at = None
    invalid_time = False
    for point in history:
        if not isinstance(point, dict):
            invalid_time = True
            continue
        rank = point.get("rank")
        stamp = point.get("timestamp")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0 or not isinstance(stamp, str):
            invalid_time = True
            continue
        path.append(rank)
        previous = rank
        previous_at = stamp
    row["rank_path_prior"] = path
    row["previous_rank"] = previous
    row["rank_history_invalid"] = invalid_time and not path
    if previous is None or row.get("rank") is None or previous_at is None:
        row["rank_velocity"] = None
        return
    elapsed = _minutes(previous_at, as_of)
    if elapsed is None or elapsed <= 0:
        row["rank_velocity"] = None
        row["rank_history_invalid"] = True
        return
    row["rank_velocity"] = round((previous - row["rank"]) / elapsed, 6)


def _minutes(start: str, end: str) -> float | None:
    try:
        left = datetime.fromisoformat(start)
        right = datetime.fromisoformat(end)
    except ValueError:
        return None
    if left.tzinfo is None or right.tzinfo is None:
        return None
    return (right - left).total_seconds() / 60.0


def is_emergency(row: dict, config: dict) -> bool:
    if row.get("fail_closed") or row.get("score") is None:
        return False
    rules = config["emergency"]
    if row["score"] < float(rules["min_score"]):
        return False
    needed = set(rules["required_any"])
    hits = [code for code in row.get("reason_codes") or [] if code in needed]
    return len(set(hits)) >= int(rules["min_reason_count"])


def select_active100(rows: list[dict], selection: dict, previous_members: list[str] | None, config: dict, protected: set[str]) -> list[dict]:
    eligible = [row for row in rows if not row.get("fail_closed") and row.get("market_score") is not None]
    ranked = sorted(eligible, key=lambda row: (-row["market_score"], row["symbol"]))
    limit = int(config["funnel"]["active_size"])
    if selection["rebuild"] or not previous_members:
        chosen = ranked[:limit]
        for row in chosen:
            row["membership"] = "SCHEDULED" if selection["rebuild"] else "INITIAL"
            _add_reason(row, "SCHEDULED_RESELECT" if selection["rebuild"] else "TOP_UNIVERSE_SCORE")
            if not _market_reasons(row):
                _add_reason(row, "TOP_UNIVERSE_SCORE")
        return chosen

    by_symbol = {row["symbol"]: row for row in ranked}
    kept = []
    for symbol in previous_members:
        row = by_symbol.get(symbol)
        if row is None:
            continue
        row["membership"] = "HELD"
        if not _market_reasons(row):
            _add_reason(row, "TOP_UNIVERSE_SCORE")
        kept.append(row)
    if selection["allow_emergency"]:
        held_ids = {row["symbol"] for row in kept}
        for row in ranked:
            if row["symbol"] in held_ids:
                continue
            if is_emergency(row, config):
                row["membership"] = "EMERGENCY"
                _add_reason(row, "EMERGENCY_PROMOTION")
                kept.append(row)
    return _trim(kept, limit, protected)


def _market_reasons(row: dict) -> list[str]:
    skip = {"FAIL_CLOSED", "SCHEDULED_RESELECT", "EMERGENCY_PROMOTION", "TOP_UNIVERSE_SCORE"}
    return [code for code in row.get("reason_codes") or [] if code not in skip]


def _add_reason(row: dict, code: str) -> None:
    reasons = list(row.get("reason_codes") or [])
    if code not in reasons:
        reasons.append(code)
    row["reason_codes"] = reasons


def _trim(members: list[dict], limit: int, protected: set[str]) -> list[dict]:
    if len(members) <= limit:
        return members

    def drop_key(row: dict):
        sticky = row["symbol"] in protected or row.get("membership") == "EMERGENCY"
        return (sticky, row.get("market_score") or -1, row["symbol"])

    ordered = sorted(members, key=drop_key)
    drop_ids = {row["symbol"] for row in ordered[: len(members) - limit]}
    return [row for row in members if row["symbol"] not in drop_ids]


def _promotion_min_coverage(config: dict) -> float:
    return float(config["funnel"]["promotion_min_coverage"])


def _coverage_ok(row: dict, minimum: float) -> bool:
    coverage = row.get("coverage")
    return isinstance(coverage, (int, float)) and not isinstance(coverage, bool) and float(coverage) >= minimum


def _has_observed_velocity(row: dict) -> bool:
    return row.get("rank_velocity") is not None and row.get("rank_velocity_component") is not None


def _precursor_ok(row: dict, config: dict) -> bool:
    if not config["funnel"].get("require_precursor", True):
        return True
    needed = set((config.get("states") or {}).get("precursor_reasons") or [])
    return bool(needed.intersection(row.get("reason_codes") or []))


def _promotable(row: dict, min_score: float, config: dict) -> bool:
    """NEXT slots require a complete, fully covered score and a real precursor.

    List length is a cap. A short list stays short. WATCH-level rows are not
    used to fill empty seats.
    """

    if row.get("fail_closed") or row.get("score_status") != "COMPLETE" or row.get("score") is None:
        return False
    if not _has_observed_velocity(row):
        return False
    if not _coverage_ok(row, _promotion_min_coverage(config)):
        return False
    if float(row["score"]) < min_score:
        return False
    return _precursor_ok(row, config)


def _empty_funnel_reason(active: list[dict], config: dict) -> tuple[bool, str]:
    if not active:
        return True, "ACTIVE100_EMPTY"
    minimum = _promotion_min_coverage(config)
    scored = [row for row in active if not row.get("fail_closed") and row.get("market_score") is not None]
    if not scored:
        return True, "ACTIVE100_EMPTY"
    covered = [row for row in scored if _coverage_ok(row, minimum)]
    if not covered:
        return True, "COMPLETE_SCORE_UNAVAILABLE"
    observed = [
        row for row in covered
        if _has_observed_velocity(row) and row.get("score_status") == "COMPLETE" and row.get("score") is not None
    ]
    if not observed:
        return True, "RANK_VELOCITY_UNAVAILABLE"
    return False, "NEXT_ELIGIBILITY_UNMET"


def _leave_in_active(active: list[dict], promoted: list[dict]) -> None:
    chosen = {row["symbol"] for row in promoted}
    for row in active:
        if row["symbol"] in chosen:
            continue
        row["funnel"] = "ACTIVE100"
        row["next_rank"] = None
        row["next20_rank"] = None


def build_funnel(active: list[dict], config: dict) -> dict:
    funnel = config["funnel"]
    next20_floor = float(funnel["next20_min_score"])
    next5_floor = float(funnel["next5_min_score"])
    next20_ready = [row for row in active if _promotable(row, next20_floor, config)]
    if not next20_ready:
        closed, reason = _empty_funnel_reason(active, config)
        _leave_in_active(active, [])
        return {"next20": [], "next5": [], "funnel_fail_closed": closed, "funnel_reason": reason}

    def keyed(row: dict, score_weight: float, velocity_weight: float):
        value = selection_value(row["score"], row["rank_velocity_component"], score_weight, velocity_weight)
        row_key = (-value, -row["score"], row["symbol"])
        return row_key, value

    next20_scored = []
    for row in next20_ready:
        key, value = keyed(row, float(funnel["next20_score_weight"]), float(funnel["next20_velocity_weight"]))
        row["next20_selection"] = round(value, 6)
        next20_scored.append((key, row))
    next20_scored.sort(key=lambda item: item[0])
    next20 = [row for _, row in next20_scored[: int(funnel["next20_size"])]]
    for index, row in enumerate(next20, start=1):
        row["next20_rank"] = index
        row["funnel"] = "NEXT20"

    next5_scored = []
    for row in next20:
        if float(row["score"]) < next5_floor:
            continue
        key, value = keyed(row, float(funnel["next5_score_weight"]), float(funnel["next5_velocity_weight"]))
        row["next5_selection"] = round(value, 6)
        next5_scored.append((key, row))
    next5_scored.sort(key=lambda item: item[0])
    next5 = [row for _, row in next5_scored[: int(funnel["next5_size"])]]
    next5_ids = {row["symbol"] for row in next5}
    for index, row in enumerate(next5, start=1):
        row["next_rank"] = index
        row["funnel"] = "NEXT5"
    for row in next20:
        if row["symbol"] not in next5_ids:
            row["next_rank"] = row["next20_rank"]
    _leave_in_active(active, next20)
    return {
        "next20": next20,
        "next5": next5,
        "funnel_fail_closed": False,
        "funnel_reason": None,
    }
