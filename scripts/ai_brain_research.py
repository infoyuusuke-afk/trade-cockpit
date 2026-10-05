"""AI Brain V1 research layer.

The live intraday strategy stays the baseline. This module records whether an
added feature changes expectancy. It does not change the collector signal,
does not call the supervisor, and does not submit.

A feature becomes a promotion candidate only after backtest, walk-forward,
replay, and shadow each show the same post-cost direction with enough
samples. Small samples stay INSUFFICIENT_SAMPLE. A value is usable only when
its available_at is at or before the decision. Shadow trade rows with an
unknown commission stay out of the live sample. Synthetic rows stay in the
replay pipe.
"""
from __future__ import annotations

import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import decision_input_value as audit
import shadow_trade_ledger as trade_ledger

JST = timezone(timedelta(hours=9))
MIN_SAMPLE = 8
STATISTICAL_MIN_SAMPLE = 30
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


def _family_z(family_size: int) -> float:
    """Wider interval when several features are searched together.

    Eight samples remain the pipeline floor. They do not survive this bar.
    """
    if family_size <= 1:
        return 1.96
    if family_size <= 5:
        return 2.58
    if family_size <= 12:
        return 2.88
    return 3.10


def _variance(values: list) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _effect_size(model_nets: list, base_nets: list):
    left = _variance(model_nets)
    right = _variance(base_nets)
    if left is None or right is None:
        return None
    pooled = ((len(model_nets) - 1) * left + (len(base_nets) - 1) * right) / (len(model_nets) + len(base_nets) - 2)
    if pooled <= 0:
        return None
    return (sum(model_nets) / len(model_nets) - sum(base_nets) / len(base_nets)) / (pooled ** 0.5)


def _delta_ci_low(model_nets: list, base_nets: list, z_value: float):
    left = _variance(model_nets)
    right = _variance(base_nets)
    if left is None or right is None or left <= 0 or right <= 0:
        return None
    se = ((left / len(model_nets)) + (right / len(base_nets))) ** 0.5
    delta = (sum(model_nets) / len(model_nets)) - (sum(base_nets) / len(base_nets))
    return delta - z_value * se


def summarize_model(trials, *, model_id: str, side: str, family_size: int | None = None) -> dict:
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
    searched = len(registry_ids("acquired")) + len(registry_ids("connected"))
    if family_size is None:
        family_size = searched
    model_oos = [row["net"] for row in model_rows if row["stage"] == "oos"]
    base_oos = [row["net"] for row in base_rows if row["stage"] == "oos"]
    effect = _effect_size(model_oos, base_oos)
    adjusted_low = _delta_ci_low(model_oos, base_oos, _family_z(family_size))
    status = "INSUFFICIENT_SAMPLE"
    promotion = False
    edge_claim = False
    edge_block_reasons = []
    if model_id == BASELINE_MODEL:
        status = "BASELINE"
    else:
        pipeline = all(
            stages[stage]["model"]["n"] >= MIN_SAMPLE and stages[stage]["baseline"]["n"] >= MIN_SAMPLE
            for stage in STAGES
        )
        statistical_n = all(
            stages[stage]["model"]["n"] >= STATISTICAL_MIN_SAMPLE and stages[stage]["baseline"]["n"] >= STATISTICAL_MIN_SAMPLE
            for stage in STAGES
        )
        regime_ok = bool(regime_stats) and all(item["n"] >= STATISTICAL_MIN_SAMPLE for item in regime_stats.values())
        if not pipeline:
            status = "INSUFFICIENT_SAMPLE"
        elif not all(_same_direction(deltas["backtest"], deltas[stage]) for stage in STAGES):
            status = "OOS_FAILED"
        elif not all(deltas[stage] > 0 for stage in STAGES):
            status = "OOS_FAILED"
        elif oos["ci_low"] is None or oos["ci_low"] <= 0:
            status = "OOS_FAILED"
        else:
            if not statistical_n:
                edge_block_reasons.append("STATISTICAL_SAMPLE")
            if effect is None:
                edge_block_reasons.append("EFFECT_SIZE_UNMEASURED")
            if not regime_ok:
                edge_block_reasons.append("REGIME_SAMPLE")
            if adjusted_low is None or adjusted_low <= 0:
                edge_block_reasons.append("MULTIPLE_TESTING")
            if edge_block_reasons:
                status = "PIPELINE_ONLY"
            else:
                status = "OOS_REPRODUCED"
                promotion = True
                edge_claim = True
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
        "effect_size": effect,
        "adjusted_delta_ci_low": adjusted_low,
        "family_size": family_size,
        "pipeline_min_sample": MIN_SAMPLE,
        "statistical_min_sample": STATISTICAL_MIN_SAMPLE,
        "measurement_status": status,
        "promotion_candidate": promotion,
        "edge_claim": edge_claim,
        "edge_block_reasons": edge_block_reasons,
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
        if not isinstance(summary, dict) or summary.get("promotion_candidate") is not True or summary.get("edge_claim") is not True:
            continue
        if summary.get("real_submit_allowed") is not False:
            continue
        regime = summary.get("regimes", {}).get(current_regime)
        if not isinstance(regime, dict) or regime.get("n", 0) < STATISTICAL_MIN_SAMPLE:
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


def _entry_by_seq(ledger) -> dict:
    found = {}
    if not isinstance(ledger, list):
        return found
    for event in ledger:
        if isinstance(event, dict) and event.get("event_type") == "virtual_entry" and event.get("seq") is not None:
            found[event.get("seq")] = event
    return found


def _stale_exit(event: dict) -> bool:
    if event.get("stale") is True:
        return True
    reason = event.get("stale_reason")
    if isinstance(reason, str) and reason:
        return True
    if event.get("data") == "STALE":
        return True
    status = event.get("price_source_status")
    return isinstance(status, str) and status not in {"", "OK"}


def _fee(event: dict):
    for key in ("fee_yen_per_share", "cost_yen_per_share"):
        value = _number(event.get(key))
        if value is not None and value >= 0:
            return value
    return None


def _exclude(event, reason: str) -> dict:
    return {
        "seq": None if not isinstance(event, dict) else event.get("seq"),
        "reason": reason,
        "source": "synthetic" if isinstance(event, dict) and event.get("acceptance_class") == "synthetic" else "live_shadow",
    }


def ingest_shadow_exits(ledger) -> dict:
    """Keep confirmed live shadow exits. Synthetic rows stay out of this stage.

    A trade needs an entry time, exit time, both fill prices, slippage, and a
    known fee. The same entry is counted once. Nothing here opens a new trade.
    """
    entries = _entry_by_seq(ledger)
    accepted = []
    excluded = []
    seen = set()
    events = ledger if isinstance(ledger, list) else []
    exited = set()
    for event in events:
        if not isinstance(event, dict) or event.get("event_type") != "virtual_exit":
            continue
        if event.get("acceptance_class") == "synthetic":
            excluded.append(_exclude(event, "SYNTHETIC_NOT_LIVE_SHADOW"))
            continue
        if event.get("real_submit_allowed") is not False:
            excluded.append(_exclude(event, "REAL_SUBMIT_NOT_FALSE"))
            continue
        ticker = event.get("ticker")
        side = event.get("side")
        if not isinstance(ticker, str) or not ticker or side not in {"LONG", "SHORT"}:
            excluded.append(_exclude(event, "IDENTITY_UNKNOWN"))
            continue
        if _stale_exit(event):
            excluded.append(_exclude(event, "STALE_PRICE"))
            continue
        if event.get("performance_bucket") != "clean_strategy":
            excluded.append(_exclude(event, "INCOMPLETE"))
            continue
        entry = entries.get(event.get("related_entry_seq"))
        entry_at = _parse_time(None if not isinstance(entry, dict) else entry.get("at"), datetime.now(JST))
        exit_at = _parse_time(event.get("at"), datetime.now(JST))
        if entry_at is None or exit_at is None:
            excluded.append(_exclude(event, "INCOMPLETE"))
            continue
        if exit_at < entry_at:
            excluded.append(_exclude(event, "TIMESTAMP_INCONSISTENT"))
            continue
        prices = (_number(event.get("fill_entry_price")), _number(event.get("fill_exit_price")))
        if any(price is None or price <= 0 for price in prices):
            excluded.append(_exclude(event, "INCOMPLETE"))
            continue
        if _number(event.get("slippage_yen")) is None or _number(event.get("mae_yen")) is None or _number(event.get("mfe_yen")) is None:
            excluded.append(_exclude(event, "INCOMPLETE"))
            continue
        if _number(event.get("fill_pnl_per_share_yen")) is None:
            excluded.append(_exclude(event, "INCOMPLETE"))
            continue
        fee = _fee(event)
        if fee is None:
            excluded.append(_exclude(event, "FEE_UNKNOWN"))
            continue
        trade_id = ticker + "|" + side + "|" + str(event.get("related_entry_seq"))
        if trade_id in seen:
            excluded.append(_exclude(event, "DUPLICATE"))
            continue
        seen.add(trade_id)
        exited.add(event.get("related_entry_seq"))
        features = event.get("features") if isinstance(event.get("features"), dict) else {}
        accepted.append({
            "model_id": BASELINE_MODEL,
            "side": side,
            "stage": "shadow",
            "source": "live_shadow",
            "trade_id": trade_id,
            "decided_at": entry_at,
            "exit_at": exit_at.isoformat(),
            "regime": event.get("regime") if isinstance(event.get("regime"), str) and event.get("regime") else "UNKNOWN",
            "pnl_per_share_yen": _number(event.get("fill_pnl_per_share_yen")),
            "cost_yen_per_share": fee,
            "mae_yen": _number(event.get("mae_yen")),
            "mfe_yen": _number(event.get("mfe_yen")),
            "slippage_yen": _number(event.get("slippage_yen")),
            "features": features,
            "real_submit_allowed": False,
        })
    for event in events:
        if not isinstance(event, dict) or event.get("event_type") != "virtual_entry":
            continue
        if event.get("acceptance_class") == "synthetic":
            continue
        if event.get("seq") in exited:
            continue
        excluded.append(_exclude(event, "INCOMPLETE"))
    return {
        "trials": accepted,
        "excluded": excluded,
        "clean_n": len(accepted),
        "source": "live_shadow",
        "stage": "shadow",
        "real_submit_allowed": False,
    }


def _prepared_shadow(trials) -> list:
    prepared = []
    for trial in trials or []:
        row = _prepare(trial)
        if row.get("ok") and row.get("stage") == "shadow" and trial.get("source") == "live_shadow":
            row["trade_id"] = trial.get("trade_id")
            prepared.append(row)
    return prepared


def baseline_shadow_metrics(trials) -> dict:
    """LONG and SHORT metrics for one live-shadow population."""
    rows = _prepared_shadow(trials)
    by_side = {}
    for side in ("LONG", "SHORT"):
        metrics = _metrics([row for row in rows if row["side"] == side])
        by_side[side] = {
            "n": metrics["n"],
            "net_ev": metrics["net_ev"],
            "win_rate": metrics["win_rate"],
            "profit_factor": metrics["profit_factor"],
            "avg_mae_yen": metrics["avg_mae_yen"],
            "avg_mfe_yen": metrics["avg_mfe_yen"],
            "max_dd_yen_per_share": metrics["max_dd_yen_per_share"],
            "avg_slippage_yen": metrics["avg_slippage_yen"],
        }
    return {"by_side": by_side, "clean_n": len(rows), "real_submit_allowed": False, "promotion_candidate": False}


def paired_feature_comparison(trials, feature_id: str) -> dict:
    """Compare a feature on exactly the same live-shadow trades.

    Missing a feature on one trade blocks that comparison. A recorded value
    without a counterfactual result does not create a delta.
    """
    if feature_id not in REGISTRY:
        raise KeyError(feature_id)
    rows = _prepared_shadow(trials)
    by_id = {trial.get("trade_id"): trial for trial in trials or [] if isinstance(trial, dict)}
    present = []
    alternate = []
    for row in rows:
        trial = by_id.get(row["trade_id"]) or {}
        feature = trial.get("features", {}).get(feature_id) if isinstance(trial.get("features"), dict) else None
        availability = "ABSENT"
        if isinstance(feature, dict):
            availability = _availability(feature.get("available_at"), row["decided_at"])
        if availability == "PRESENT":
            present.append(row["trade_id"])
        item = trial.get("counterfactuals", {}).get(feature_id) if isinstance(trial.get("counterfactuals"), dict) else None
        pnl = _number(item.get("pnl_per_share_yen")) if isinstance(item, dict) else None
        cost = _number(item.get("cost_yen_per_share")) if isinstance(item, dict) else None
        if pnl is not None and cost is not None:
            alternate.append({
                "decided_at": row["decided_at"],
                "net": pnl - cost,
                "mae": row["mae"],
                "mfe": row["mfe"],
                "slippage": row["slippage"],
            })
    trade_ids = [row["trade_id"] for row in rows]
    same_population = len(present) == len(trade_ids) and set(present) == set(trade_ids)
    baseline = _metrics(rows) if rows else _empty_metrics()
    feature_ev = None
    delta = None
    if not rows:
        status = "NO_CLEAN_TRADES"
    elif same_population and len(alternate) == len(trade_ids):
        feature_metrics = _metrics(alternate)
        feature_ev = feature_metrics["net_ev"]
        delta = None if feature_ev is None or baseline["net_ev"] is None else feature_ev - baseline["net_ev"]
        status = "PAIRED"
    elif same_population:
        status = "FEATURE_RECORDED_MODEL_NOT_APPLIED"
    else:
        status = "POPULATION_MISMATCH"
    if status == "NO_CLEAN_TRADES":
        measurement = "NO_CLEAN_TRADES"
    elif status == "PAIRED":
        measurement = "INSUFFICIENT_SAMPLE" if len(rows) < MIN_SAMPLE else "PIPELINE_ONLY"
    elif status == "FEATURE_RECORDED_MODEL_NOT_APPLIED":
        measurement = "NO_COUNTERFACTUAL"
    else:
        measurement = status
    return {
        "feature_id": feature_id,
        "baseline_n": len(trade_ids),
        "feature_n": len(present),
        "baseline_ev": baseline["net_ev"],
        "feature_ev": feature_ev,
        "delta_ev": delta,
        "population_status": status,
        "measurement_status": measurement,
        "promotion_candidate": False,
        "edge_claim": False,
        "live_roundtrip": "NOT_RUN/RESEARCH_LAYER",
        "real_submit_allowed": False,
    }


DATA_LANE = (
    {"id": "nt_ratio", "priority": 1, "availability": "日経225とTOPIXから計算できる。このリポジトリにはリアルタイム系列が無い。", "published_clock": "両指数の遅い方の公表時刻。寄り前の値は前営業日終値。", "update_frequency": "ザラ場中の指数更新。比率自体の公式系列は未接続。", "history_storable": False, "license": "日経平均は日本経済新聞社、TOPIXはJPXの利用条件。再配布しない。", "fetch_status": "NOT_FETCHED"},
    {"id": "investor_futures_flow", "priority": 1, "availability": "JPXの投資部門別、先物は derivatives/sector。scripts/investor_regime.py は週次ファイルを読むが、LIVE signal には入れない。", "published_clock": "JPXがファイルを出した時刻。週の途中では未公表。", "update_frequency": "週次。公表遅れあり。", "history_storable": True, "license": "JPX公開統計。出典を残し、売買フィードとしては使わない。", "fetch_status": "NOT_FETCHED"},
    {"id": "futures_options_positioning", "priority": 1, "availability": "建玉と出来高はJPX派生商品統計。IVとPCRの公式リアルタイム系列はこのリポジトリに無い。", "published_clock": "取引所統計は日次締め後。場中のIVはベンダー計算が多い。", "update_frequency": "日次。IVは未接続。", "history_storable": False, "license": "建玉はJPX。IVはベンダー契約が別。未契約の値は取らない。", "fetch_status": "NOT_FETCHED"},
    {"id": "short_sale_ratio", "priority": 2, "availability": "JPX空売り集計。LIVE行には無い。", "published_clock": "当日セッション後の公表。場中判断には使えない。", "update_frequency": "日次。", "history_storable": True, "license": "JPX公開統計。", "fetch_status": "NOT_FETCHED"},
    {"id": "credit_evaluation_loss", "priority": 2, "availability": "取引所の単一系列としては未確認。証券会社の計算である可能性が高く、このリポジトリに取得元が無い。", "published_clock": "未確認。推定で埋めない。", "update_frequency": "未確認。", "history_storable": False, "license": "未確認。ソースが特定できるまで取得しない。", "fetch_status": "NOT_FETCHED"},
    {"id": "arbitrage_balance", "priority": 2, "availability": "JPXの裁定取引残高統計。LIVE signal には無い。", "published_clock": "公表ファイルの時刻。日中の速報とは限らない。", "update_frequency": "日次または週次。取得前にJPXの欄を確認する。", "history_storable": True, "license": "JPX公開統計。", "fetch_status": "NOT_FETCHED"},
    {"id": "crude", "priority": 3, "availability": "WTI/Brentは取引所先物。global_macro は名前だけを持ち、取得はしない。", "published_clock": "各取引所の約定時刻。東京の判断より後の足は使えない。", "update_frequency": "場中。", "history_storable": False, "license": "取引所またはベンダー契約。未契約。", "fetch_status": "NOT_FETCHED"},
    {"id": "gold", "priority": 3, "availability": "COMEX金先物など。系列は未保存。", "published_clock": "取引所の約定時刻。", "update_frequency": "場中。", "history_storable": False, "license": "取引所またはベンダー契約。未契約。", "fetch_status": "NOT_FETCHED"},
    {"id": "silver", "priority": 3, "availability": "銀先物の取得コードは無い。", "published_clock": "未接続。", "update_frequency": "未接続。", "history_storable": False, "license": "未契約。", "fetch_status": "NOT_FETCHED"},
    {"id": "copper", "priority": 3, "availability": "COMEX銅など。global_macro の許可リストにあるだけで値は無い。", "published_clock": "取引所の約定時刻。", "update_frequency": "場中。", "history_storable": False, "license": "取引所またはベンダー契約。未契約。", "fetch_status": "NOT_FETCHED"},
    {"id": "korea_equity", "priority": 3, "availability": "KRXのKOSPI、KOSDAQ、個別株。このリポジトリに系列が無い。", "published_clock": "韓国市場の約定時刻。東京の同時刻より後は使えない。", "update_frequency": "韓国ザラ場。", "history_storable": False, "license": "KRXまたはベンダー契約。未契約。", "fetch_status": "NOT_FETCHED"},
    {"id": "macro_release", "priority": 4, "availability": "event_calendar.py が日銀、FOMC、CPI、雇用統計の予定時刻を持つ。結果の数値系列は未接続。", "published_clock": "カレンダーの exact 時刻だけ。window は時刻を作らない。", "update_frequency": "公表日ごと。", "history_storable": True, "license": "公式予定表。数値の再配布条件は各当局。", "fetch_status": "NOT_FETCHED"},
    {"id": "official_speech", "priority": 4, "availability": "構造化された要人発言フィードは無い。", "published_clock": "未確認。発言後にしか使えない。", "update_frequency": "不定期。", "history_storable": False, "license": "未確認。", "fetch_status": "NOT_FETCHED"},
    {"id": "earnings_schedule", "priority": 5, "availability": "update.py はJPXの決算日程を別バッチで読む。LIVE signal には入っていない。", "published_clock": "日程表の公表時刻。結果はその後。", "update_frequency": "月次の日程と、開示のたび。", "history_storable": True, "license": "JPX公表資料。", "fetch_status": "NOT_FETCHED"},
    {"id": "catalyst", "priority": 5, "availability": "TDnet見出しの点数は引け後PTS側にある。一般カタリスト系列はLIVE判断に入っていない。", "published_clock": "開示時刻。", "update_frequency": "開示のたび。", "history_storable": True, "license": "TDnet公表資料。", "fetch_status": "NOT_FETCHED"},
    {"id": "midterm_plan", "priority": 5, "availability": "各社IRのPDF。構造化系列は無い。", "published_clock": "IR公表時刻。", "update_frequency": "不定期。", "history_storable": False, "license": "各社の資料。本文はコピーしない。", "fetch_status": "NOT_FETCHED"},
    {"id": "shikiho_fundamentals", "priority": 5, "availability": "四季報は東洋経済新報社の著作物。このリポジトリに本文も指標系列も無い。", "published_clock": "誌面の発行日。発売前の値は使えない。", "update_frequency": "季刊。", "history_storable": False, "license": "転載しない。契約が無いので取得しない。", "fetch_status": "NOT_FETCHED"},
)


LANE_SURVEY = {
    "nt_ratio": {
        "source_candidate": "日経平均は日本経済新聞社の指数、TOPIXはJPX。比率の保存系列はこのリポジトリに無い。",
        "source_url": "https://www.jpx.co.jp/markets/indices/topix/",
        "history_fetchable": False,
        "available_at": "両指数の遅い方の公表時刻。寄り前の値は前営業日終値。",
    },
    "investor_futures_flow": {
        "source_candidate": "JPX投資部門別売買状況。株式の週間ファイルは第4営業日15:30掲載。",
        "source_url": "https://www.jpx.co.jp/markets/statistics-equities/investor-type/",
        "history_fetchable": True,
        "available_at": "JPXがファイルを出した時刻。週の途中では未公表。",
    },
    "futures_options_positioning": {
        "source_candidate": "JPX派生商品の建玉・出来高。IVとPCRの公式リアルタイム系列は未確認。",
        "source_url": "https://www.jpx.co.jp/markets/derivatives/",
        "history_fetchable": False,
        "available_at": "取引所統計は日次締め後。場中のIVは使わない。",
    },
    "short_sale_ratio": {
        "source_candidate": "JPX空売り集計。日次と月間の売買代金比率。",
        "source_url": "https://www.jpx.co.jp/markets/statistics-equities/short-selling/",
        "history_fetchable": True,
        "available_at": "当日セッション後の公表。場中判断には使えない。",
    },
    "credit_evaluation_loss": {
        "source_candidate": "取引所の単一系列は未確認。証券会社計算の可能性がある。",
        "source_url": None,
        "history_fetchable": None,
        "available_at": "未確認。推定で埋めない。",
    },
    "arbitrage_balance": {
        "source_candidate": "JPXプログラム売買・裁定取引の日次合計。参加者別PDFの合計ポジションは未切り出し。",
        "source_url": "https://www.jpx.co.jp/markets/statistics-equities/program/",
        "history_fetchable": True,
        "available_at": "公表ファイルの時刻。日中の速報とは限らない。",
    },
    "crude": {
        "source_candidate": "WTIはCMEのLight Sweet Crude。未契約のため値は取らない。",
        "source_url": "https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.html",
        "history_fetchable": False,
        "available_at": "取引所の約定時刻。東京の判断より後の足は使えない。",
    },
    "gold": {
        "source_candidate": "COMEX金先物。未契約のため値は取らない。",
        "source_url": "https://www.cmegroup.com/markets/metals/precious/gold.html",
        "history_fetchable": False,
        "available_at": "取引所の約定時刻。東京の判断より後の足は使えない。",
    },
    "silver": {
        "source_candidate": "銀先物の取得コードは無い。",
        "source_url": None,
        "history_fetchable": False,
        "available_at": "未接続。",
    },
    "copper": {
        "source_candidate": "銅先物の公式系列はこのリポジトリに無い。",
        "source_url": None,
        "history_fetchable": False,
        "available_at": "未接続。",
    },
    "korea_equity": {
        "source_candidate": "KRXのKOSPI、KOSDAQ。未契約のため値は取らない。",
        "source_url": "https://global.krx.co.kr/",
        "history_fetchable": False,
        "available_at": "韓国市場の約定時刻。東京の同時刻より後は使えない。",
    },
    "macro_release": {
        "source_candidate": "event_calendar.py の日銀、FOMC、CPI、雇用統計の予定時刻。結果の数値は未接続。",
        "source_url": None,
        "history_fetchable": True,
        "available_at": "カレンダーの exact 時刻だけ。window は時刻を作らない。",
    },
    "official_speech": {
        "source_candidate": "構造化された要人発言フィードは未確認。",
        "source_url": None,
        "history_fetchable": False,
        "available_at": "未確認。発言後にしか使えない。",
    },
    "earnings_schedule": {
        "source_candidate": "JPX決算発表予定。scripts/earnings_calendar.py が日程だけを読む。",
        "source_url": "https://www.jpx.co.jp/listing/event-schedules/financial-announcement/index.html",
        "history_fetchable": True,
        "available_at": "日程表の公表時刻。結果はその後。",
    },
    "catalyst": {
        "source_candidate": "TDnet開示見出し。本文はコピーしない。",
        "source_url": "https://www.release.tdnet.info/inbs/",
        "history_fetchable": True,
        "available_at": "開示時刻。",
    },
    "midterm_plan": {
        "source_candidate": "各社IRのPDF。構造化系列は無い。本文はコピーしない。",
        "source_url": None,
        "history_fetchable": False,
        "available_at": "IR公表時刻。",
    },
    "shikiho_fundamentals": {
        "source_candidate": "四季報は東洋経済新報社の著作物。本文も指標系列も置かない。",
        "source_url": None,
        "history_fetchable": False,
        "available_at": "誌面の発行日。発売前の値は使えない。",
    },
}


def research_data_lane() -> tuple:
    """Recorded sources stay unadopted. A fetched row is still not a trade input."""
    if set(LANE_SURVEY) != {item["id"] for item in DATA_LANE}:
        raise RuntimeError("research data lane survey does not match the registry")
    import research_lane_investor_flow as investor_flow
    import research_lane_short_sale as short_sale

    loaded_by_id = {
        "short_sale_ratio": short_sale.load_latest(),
        "investor_futures_flow": investor_flow.load_latest(),
    }
    value_field = {
        "short_sale_ratio": "short_ratio_for_research",
        "investor_futures_flow": "foreign_nikkei225_futures_net_yen_for_research",
    }
    rows = []
    for item in DATA_LANE:
        survey = LANE_SURVEY[item["id"]]
        status = "NOT_FETCHED"
        extra = {}
        loaded = loaded_by_id.get(item["id"])
        if loaded is not None and loaded.get("fetch_status") == "FETCHED":
            status = "FETCHED"
            field = value_field[item["id"]]
            extra = {
                "source": loaded.get("source"),
                "fetched_at": loaded.get("fetched_at"),
                "first_seen_at": loaded.get("first_seen_at"),
                "available_at": loaded.get("available_at"),
                "published_at": loaded.get("published_at"),
                "published_at_basis": loaded.get("published_at_basis"),
                "freshness": loaded.get("freshness"),
                "freshness_basis": loaded.get("freshness_basis"),
                "business_day_gap": loaded.get("business_day_gap"),
                "calendar_age_days": loaded.get("calendar_age_days"),
                "license_note": loaded.get("license_note"),
                "session_date": loaded.get("session_date"),
                "sha256": loaded.get("sha256"),
                field: loaded.get(field),
                "counts_as_live_sample": False,
                "promotion_candidate": False,
                "source_stage": "OFFICIAL_PUBLIC",
            }
        elif loaded is not None and loaded.get("fetch_status") == "FAIL_CLOSED":
            status = "FAIL_CLOSED"
            extra = {
                "freshness": "MALFORMED",
                value_field[item["id"]]: None,
                "reason": "MALFORMED",
            }
        rows.append({
            **item,
            **survey,
            "surveyed_on": "2026-10-05",
            "available_at_rule": survey["available_at"],
            "fetch_status": status,
            "trading_adoption": False,
            "lane": "research_data_lane",
            "real_submit_allowed": False,
            **extra,
        })
    return tuple(rows)


def research_lane_fetch_summary(lane: tuple | None = None) -> dict:
    rows = research_data_lane() if lane is None else lane
    fetched = [item["id"] for item in rows if item.get("fetch_status") == "FETCHED"]
    return {"fetched": len(fetched), "registry": len(rows), "ids": fetched}


def _trial_from_shadow_trade(record: dict, source: str) -> dict:
    commission = _number(record.get("commission"))
    other = _number(record.get("other_cost"))
    entry_slip = _number(record.get("entry_slippage"))
    exit_slip = _number(record.get("exit_slippage"))
    return {
        "model_id": BASELINE_MODEL,
        "side": record.get("side"),
        "stage": "shadow",
        "source": source,
        "trade_id": record.get("trade_id"),
        "decided_at": record.get("decision_at"),
        "regime": record.get("regime") if isinstance(record.get("regime"), str) and record.get("regime") else "UNKNOWN",
        "pnl_per_share_yen": _number(record.get("gross_pnl")),
        "cost_yen_per_share": None if commission is None or other is None else commission + other,
        "mae_yen": _number(record.get("mae")),
        "mfe_yen": _number(record.get("mfe")),
        "slippage_yen": None if entry_slip is None or exit_slip is None else entry_slip + exit_slip,
        "features": {},
        "source_stage": record.get("source_stage"),
        "real_submit_allowed": False,
    }


def evaluate_shadow_trade_ledger(records) -> dict:
    """Turn saved shadow trades into a baseline sample.

    N=0 stays NOT_AVAILABLE. A synthetic fixture can prove the pipe and still
    adds nothing to the live sample or to promotion.
    """
    split = trade_ledger.split_shadow_trades(records)
    trials = [_trial_from_shadow_trade(record, "live_shadow") for record in split["live"]]
    pipe = [_trial_from_shadow_trade(record, "synthetic_replay") for record in split["pipe"]]
    clean_n = len(trials)
    feature_delta = "NOT_AVAILABLE"
    if clean_n:
        for feature_id in registry_ids("acquired") + registry_ids("connected"):
            compared = paired_feature_comparison(trials, feature_id)
            if compared.get("delta_ev") is not None:
                feature_delta = compared["delta_ev"]
                break
    pipe_rows = []
    for trial in pipe:
        net = _net(trial)
        pipe_rows.append({
            "trade_id": trial["trade_id"],
            "gross_pnl": trial["pnl_per_share_yen"],
            "net_pnl": net,
            "mae": trial["mae_yen"],
            "mfe": trial["mfe_yen"],
            "source_stage": trade_ledger.SOURCE_SYNTHETIC,
            "counts_as_live_sample": False,
            "promotion_candidate": False,
        })
    status = {
        "CLEAN_SHADOW_TRADE_N": clean_n,
        "BASELINE_N": clean_n,
        "FEATURE_DELTA_EV": feature_delta,
        "PROMOTION_CANDIDATE": "NONE",
        "excluded": split["excluded"],
        "pipe_n": len(pipe_rows),
        "pipe_trades": pipe_rows,
        "pipe_counts_as_live_sample": False,
        "pipe_promotion_candidate": False,
        "real_submit_allowed": False,
        "live_roundtrip": "NOT_RUN/RESEARCH_LAYER",
    }
    if clean_n:
        status["baseline_by_side"] = baseline_shadow_metrics(trials)["by_side"]
    return status
