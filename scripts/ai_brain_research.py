"""AI Brain V1 research layer.

The live intraday strategy stays the baseline. This module records whether an
added feature changes expectancy. It does not change the collector signal,
does not call the supervisor, and does not submit.

A feature becomes a promotion candidate only after backtest, walk-forward,
replay, and shadow each show the same post-cost direction with enough
samples. Small samples stay INSUFFICIENT_SAMPLE. A value is usable only when
its available_at is at or before the decision.
"""
from __future__ import annotations

import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import decision_input_value as audit

JST = timezone(timedelta(hours=9))
MIN_SAMPLE = 8
STAGES = ("backtest", "oos", "replay", "shadow")
SIDES = ("LONG", "SHORT", "NO_TRADE")
LLM_ROLE = "STRUCTURE_UNSTRUCTURED_TEXT_ONLY"
BASELINE_MODEL = "BASELINE"

# lane: acquired = already on the live row, connected = existing code not in the
# live signal, expansion = registered only. None of these change the baseline.
REGISTRY = {
    "credit_buy": {"lane": "acquired", "row_field": "credit_buy", "kind": "number"},
    "credit_sell": {"lane": "acquired", "row_field": "credit_sell", "kind": "number"},
    "credit_ratio": {"lane": "acquired", "row_field": "credit_ratio", "kind": "number"},
    "shortable_quantity": {"lane": "acquired", "row_field": "shortable_quantity", "kind": "number"},
    "prior_pts": {"lane": "acquired", "row_field": "prior_pts_bias", "kind": "number"},
    "common_decision": {"lane": "acquired", "row_field": "common_decision", "kind": "text"},
    "tdnet_material": {"lane": "acquired", "row_field": "material_score", "kind": "number"},
    "usdjpy": {"lane": "connected", "row_field": "", "kind": "number"},
    "us_rates": {"lane": "connected", "row_field": "", "kind": "number"},
    "sox": {"lane": "connected", "row_field": "", "kind": "number"},
    "earnings_estimates": {"lane": "connected", "row_field": "", "kind": "number"},
    "sq_calendar": {"lane": "connected", "row_field": "", "kind": "text"},
    "credit_evaluation_loss": {"lane": "expansion", "row_field": "", "kind": "number"},
    "short_sale_ratio": {"lane": "expansion", "row_field": "", "kind": "number"},
    "arbitrage_balance": {"lane": "expansion", "row_field": "", "kind": "number"},
    "nt_ratio": {"lane": "expansion", "row_field": "", "kind": "number"},
    "investor_futures_flow": {"lane": "expansion", "row_field": "", "kind": "number"},
    "futures_options_positioning": {"lane": "expansion", "row_field": "", "kind": "number"},
    "crude": {"lane": "expansion", "row_field": "", "kind": "number"},
    "gold": {"lane": "expansion", "row_field": "", "kind": "number"},
    "silver": {"lane": "expansion", "row_field": "", "kind": "number"},
    "copper": {"lane": "expansion", "row_field": "", "kind": "number"},
    "korea_equity": {"lane": "expansion", "row_field": "", "kind": "number"},
    "macro_release": {"lane": "expansion", "row_field": "", "kind": "text"},
    "official_speech": {"lane": "expansion", "row_field": "", "kind": "text"},
    "earnings_schedule": {"lane": "expansion", "row_field": "", "kind": "text"},
    "catalyst": {"lane": "expansion", "row_field": "", "kind": "text"},
    "midterm_plan": {"lane": "expansion", "row_field": "", "kind": "text"},
    "shikiho_fundamentals": {"lane": "expansion", "row_field": "", "kind": "text"},
}

WORLD_MARKET_CODES = {"usdjpy": "511", "us_rates": "811", "sox": "611"}
MACRO_INSTRUMENTS = {"usdjpy": "USDJPY", "us_rates": "US_10Y", "sox": "SOX"}


def registry_ids(lane: str) -> tuple:
    return tuple(key for key, item in REGISTRY.items() if item["lane"] == lane)


def baseline_side(row: dict) -> str:
    """The side the unchanged live rule would take."""
    return audit.live_side(row if isinstance(row, dict) else {})


def _parse_time(value, decided_at: datetime):
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str) and value:
        text = value.strip()
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            day = datetime.fromisoformat(text).date()
            stamp = datetime.combine(day, time(23, 59, 59), tzinfo=decided_at.tzinfo or JST)
        else:
            try:
                stamp = datetime.fromisoformat(text)
            except ValueError:
                return None
    else:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=decided_at.tzinfo or JST)
    return stamp


def _availability(stamp, decided_at: datetime) -> str:
    parsed = _parse_time(stamp, decided_at)
    if parsed is None:
        return "UNSTAMPED"
    if parsed > decided_at:
        return "LOOKAHEAD_EXCLUDED"
    return "PRESENT"


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def _feature_record(feature_id: str, value, stamp, decided_at: datetime, *, verified: bool = True) -> dict:
    status = _availability(stamp, decided_at)
    if status == "PRESENT" and not verified:
        status = "UNVERIFIED"
    spec = REGISTRY[feature_id]
    if spec["kind"] == "number":
        number = _number(value)
        if status == "PRESENT" and number is None:
            status = "ABSENT"
        stored = number
    else:
        stored = value if isinstance(value, str) and value else None
        if status == "PRESENT" and stored is None and value is not False:
            status = "ABSENT"
        if value is False and status == "PRESENT":
            stored = "false"
    return {
        "feature_id": feature_id,
        "lane": spec["lane"],
        "value": stored if status == "PRESENT" else None,
        "available_at": _parse_time(stamp, decided_at).isoformat() if _parse_time(stamp, decided_at) else None,
        "status": status,
    }


def _row_stamp(row: dict, feature_id: str, field: str):
    for key in (feature_id + "_available_at", field + "_available_at", feature_id + "_observed_at", field + "_observed_at"):
        if key in row:
            return row.get(key)
    return None


def snapshot_acquired(row: dict, decided_at: datetime) -> dict:
    """Read features the collector already stores. Missing stamps stay unused."""
    found = {}
    if not isinstance(row, dict):
        return found
    for feature_id, spec in REGISTRY.items():
        if spec["lane"] != "acquired":
            continue
        field = spec["row_field"]
        found[feature_id] = _feature_record(feature_id, row.get(field), _row_stamp(row, feature_id, field), decided_at)
    return found


def snapshot_world_market(parsed: dict, decided_at: datetime) -> dict:
    """Connect USDJPY, US 10-year yield, and SOX from a world_market parse.

    Date-only stamps become usable after that calendar day. Unverified rows
    stay out of the research sample.
    """
    rows = parsed.get("rows") if isinstance(parsed, dict) else {}
    if not isinstance(rows, dict):
        rows = {}
    found = {}
    for feature_id, code in WORLD_MARKET_CODES.items():
        row = rows.get(code) if isinstance(rows.get(code), dict) else {}
        found[feature_id] = _feature_record(
            feature_id,
            row.get("value"),
            row.get("observed_at"),
            decided_at,
            verified=row.get("verified") is True,
        )
    return found


def snapshot_macro_observations(observations, decided_at: datetime) -> dict:
    """Connect the same three fields from global-macro observation rows."""
    by_instrument = {}
    if isinstance(observations, list):
        for row in observations:
            if isinstance(row, dict) and isinstance(row.get("instrument"), str):
                by_instrument[row["instrument"]] = row
    found = {}
    for feature_id, instrument in MACRO_INSTRUMENTS.items():
        row = by_instrument.get(instrument) or {}
        found[feature_id] = _feature_record(feature_id, row.get("value"), row.get("observed_at"), decided_at)
    return found


def snapshot_earnings(record: dict, decided_at: datetime) -> dict:
    """Connect an earnings-estimate score only when it carries available_at.

    This does not call a market-data vendor.
    """
    if not isinstance(record, dict):
        record = {}
    return {
        "earnings_estimates": _feature_record(
            "earnings_estimates",
            record.get("score"),
            record.get("available_at"),
            decided_at,
        )
    }


def snapshot_sq_calendar(events, decided_at: datetime) -> dict:
    """Connect SQ dates from event_calendar rows.

    A date is known only after fetched_at. The open is not invented when the
    calendar says the time is a window.
    """
    stamped = []
    if isinstance(events, dict):
        events = events.get("events")
    if isinstance(events, list):
        for item in events:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id") or "")
            if not event_id.startswith("sq-"):
                continue
            fetched = _parse_time(item.get("fetched_at"), decided_at)
            if fetched is None:
                continue
            stamped.append((item, fetched))
    if not stamped:
        return {"sq_calendar": _feature_record("sq_calendar", None, None, decided_at)}
    known = [(item, fetched) for item, fetched in stamped if fetched <= decided_at]
    if not known:
        return {"sq_calendar": _feature_record("sq_calendar", None, stamped[0][0].get("fetched_at"), decided_at)}
    day = decided_at.date().isoformat()
    on_day = any(item.get("date") == day for item, _fetched in known)
    latest = max(fetched for _item, fetched in known)
    return {"sq_calendar": _feature_record("sq_calendar", "on" if on_day else "off", latest, decided_at)}


def _model_features(model_id: str) -> list:
    if model_id == BASELINE_MODEL:
        return []
    parts = model_id.split("+")
    if not parts or parts[0] != BASELINE_MODEL:
        raise KeyError(model_id)
    features = parts[1:]
    if not features or any(feature not in REGISTRY for feature in features):
        raise KeyError(model_id)
    return features


def _net(trial: dict):
    gross = _number(trial.get("pnl_per_share_yen"))
    cost = _number(trial.get("cost_yen_per_share"))
    if gross is None or cost is None:
        return None
    return gross - cost


def _prepare(trial: dict) -> dict:
    if not isinstance(trial, dict):
        return {"ok": False, "reason": "UNREADABLE"}
    side = trial.get("side")
    stage = trial.get("stage")
    if side not in SIDES or stage not in STAGES:
        return {"ok": False, "reason": "UNKNOWN_SIDE_OR_STAGE"}
    decided_at = _parse_time(trial.get("decided_at"), datetime.now(JST))
    if decided_at is None:
        return {"ok": False, "reason": "UNSTAMPED_DECISION"}
    try:
        required = _model_features(str(trial.get("model_id")))
    except KeyError:
        return {"ok": False, "reason": "UNKNOWN_MODEL"}
    features = trial.get("features") if isinstance(trial.get("features"), dict) else {}
    for feature_id in required:
        feature = features.get(feature_id)
        if not isinstance(feature, dict):
            return {"ok": False, "reason": "FEATURE_MISSING"}
        status = _availability(feature.get("available_at"), decided_at)
        if status != "PRESENT":
            return {"ok": False, "reason": status}
        if REGISTRY[feature_id]["kind"] == "number" and _number(feature.get("value")) is None:
            return {"ok": False, "reason": "FEATURE_MISSING"}
    net = _net(trial)
    slip = _number(trial.get("slippage_yen"))
    if net is None or slip is None:
        return {"ok": False, "reason": "COST_OR_SLIPPAGE_MISSING"}
    return {
        "ok": True,
        "model_id": trial.get("model_id"),
        "side": side,
        "stage": stage,
        "decided_at": decided_at,
        "regime": trial.get("regime") if isinstance(trial.get("regime"), str) and trial.get("regime") else "UNKNOWN",
        "net": net,
        "mae": _number(trial.get("mae_yen")),
        "mfe": _number(trial.get("mfe_yen")),
        "slippage": slip,
    }


def _empty_metrics() -> dict:
    return {
        "n": 0,
        "net_ev": None,
        "win_rate": None,
        "profit_factor": None,
        "avg_mae_yen": None,
        "avg_mfe_yen": None,
        "max_dd_yen_per_share": None,
        "avg_slippage_yen": None,
        "ci_low": None,
        "ci_high": None,
    }


def _metrics(rows: list) -> dict:
    if not rows:
        return _empty_metrics()
    ordered = sorted(rows, key=lambda row: row["decided_at"])
    nets = [row["net"] for row in ordered]
    n = len(nets)
    ev = sum(nets) / n
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value < 0]
    if wins and losses:
        profit_factor = sum(wins) / abs(sum(losses))
    elif losses:
        profit_factor = 0.0
    else:
        profit_factor = None
    maes = [row["mae"] for row in ordered if row["mae"] is not None]
    mfes = [row["mfe"] for row in ordered if row["mfe"] is not None]
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in nets:
        equity += value
        if equity > peak:
            peak = equity
        if peak - equity > drawdown:
            drawdown = peak - equity
    ci_low = None
    ci_high = None
    if n >= 2:
        variance = sum((value - ev) ** 2 for value in nets) / (n - 1)
        error = (variance ** 0.5) / (n ** 0.5)
        ci_low = ev - 1.96 * error
        ci_high = ev + 1.96 * error
    return {
        "n": n,
        "net_ev": ev,
        "win_rate": len(wins) / n,
        "profit_factor": profit_factor,
        "avg_mae_yen": (sum(maes) / len(maes)) if maes else None,
        "avg_mfe_yen": (sum(mfes) / len(mfes)) if mfes else None,
        "max_dd_yen_per_share": drawdown,
        "avg_slippage_yen": sum(row["slippage"] for row in ordered) / n,
        "ci_low": ci_low,
        "ci_high": ci_high,
    }


def _same_direction(left, right) -> bool:
    if left is None or right is None or left == 0 or right == 0:
        return False
    return (left > 0 and right > 0) or (left < 0 and right < 0)


def summarize_model(trials, *, model_id: str, side: str) -> dict:
    """Compare one candidate with the baseline on the same side.

    The baseline model is the reference. Its own promotion flag stays false.
    """
    prepared = [row for row in (_prepare(trial) for trial in (trials or [])) if row.get("ok") and row["side"] == side]
    model_rows = [row for row in prepared if row["model_id"] == model_id]
    base_rows = [row for row in prepared if row["model_id"] == BASELINE_MODEL]
    stages = {}
    deltas = {}
    for stage in STAGES:
        model_metrics = _metrics([row for row in model_rows if row["stage"] == stage])
        base_metrics = _metrics([row for row in base_rows if row["stage"] == stage])
        delta = None
        if model_metrics["net_ev"] is not None and base_metrics["net_ev"] is not None:
            delta = model_metrics["net_ev"] - base_metrics["net_ev"]
        stages[stage] = {"model": model_metrics, "baseline": base_metrics, "delta_ev": delta}
        deltas[stage] = delta
    oos = stages["oos"]["model"]
    regimes = {}
    for row in model_rows:
        if row["stage"] != "oos":
            continue
        regimes.setdefault(row["regime"], []).append(row)
    regime_stats = {name: _metrics(rows) for name, rows in regimes.items()}
    status = "INSUFFICIENT_SAMPLE"
    promotion = False
    if model_id == BASELINE_MODEL:
        status = "BASELINE"
    else:
        enough = all(
            stages[stage]["model"]["n"] >= MIN_SAMPLE and stages[stage]["baseline"]["n"] >= MIN_SAMPLE
            for stage in STAGES
        )
        if not enough:
            status = "INSUFFICIENT_SAMPLE"
        elif not all(_same_direction(deltas["backtest"], deltas[stage]) for stage in STAGES):
            status = "OOS_FAILED"
        elif not all(deltas[stage] > 0 for stage in STAGES):
            status = "OOS_FAILED"
        elif oos["ci_low"] is None or oos["ci_low"] <= 0:
            status = "OOS_FAILED"
        else:
            status = "OOS_REPRODUCED"
            promotion = True
    return {
        "model_id": model_id,
        "side": side,
        "baseline_ev": stages["oos"]["baseline"]["net_ev"],
        "feature_ev": oos["net_ev"],
        "delta_ev": deltas["oos"],
        "sample_n": oos["n"],
        "win_rate": oos["win_rate"],
        "profit_factor": oos["profit_factor"],
        "avg_mae_yen": oos["avg_mae_yen"],
        "avg_mfe_yen": oos["avg_mfe_yen"],
        "max_dd_yen_per_share": oos["max_dd_yen_per_share"],
        "avg_slippage_yen": oos["avg_slippage_yen"],
        "ci_low": oos["ci_low"],
        "ci_high": oos["ci_high"],
        "regimes": regime_stats,
        "stages": stages,
        "measurement_status": status,
        "promotion_candidate": promotion,
        "oos_net_ev": oos["net_ev"],
        "oos_n": oos["n"],
        "live_roundtrip": "NOT_RUN/RESEARCH_LAYER",
        "real_submit_allowed": False,
        "is_entry_trigger": False,
    }


def select_research_candidate(summaries, *, current_regime: str, llm_side: str | None = None) -> dict:
    """Pick at most one research candidate. Count of models is not a vote.

    NO-TRADE wins unless one side's out-of-sample interval stays positive in
    the current regime. An LLM label is ignored. The result is not a live entry.
    """
    del llm_side
    eligible = []
    for summary in summaries or []:
        if not isinstance(summary, dict) or summary.get("promotion_candidate") is not True:
            continue
        if summary.get("real_submit_allowed") is not False:
            continue
        regime = summary.get("regimes", {}).get(current_regime)
        if not isinstance(regime, dict) or regime.get("n", 0) < MIN_SAMPLE:
            continue
        if regime.get("net_ev") is None or regime.get("net_ev") <= 0:
            continue
        if summary.get("ci_low") is None or summary.get("ci_low") <= 0:
            continue
        if summary.get("avg_slippage_yen") is None:
            continue
        eligible.append(summary)
    if not eligible:
        chosen = None
        reason = "NO_ELIGIBLE_CANDIDATE"
        side = "NO_TRADE"
    else:
        chosen = max(eligible, key=lambda item: (item.get("oos_net_ev") or 0, item.get("oos_n") or 0, item.get("ci_low") or 0))
        reason = "HIGHEST_OOS_NET_EV"
        side = chosen.get("side")
    return {
        "selected_side": side,
        "model_id": None if chosen is None else chosen.get("model_id"),
        "reason": reason,
        "llm_role": LLM_ROLE,
        "llm_decides_numeric_trade": False,
        "majority_vote": False,
        "is_entry_trigger": False,
        "real_submit_allowed": False,
        "live_roundtrip": "NOT_RUN/RESEARCH_LAYER",
    }
