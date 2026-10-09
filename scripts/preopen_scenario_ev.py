#!/usr/bin/env python3
"""Preopen Scenario EV Engine V1.

Research and cockpit-data engine only. It does not read the live Collector,
does not open a broker, and does not submit an order. real_submit_allowed
is false on every record. Missing live feeds stay UNAVAILABLE or NOT_LIVE.
Numbers are not filled in to make a chart look populated.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta, timezone

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "preopen-scenario-ev-1"
REAL_SUBMIT_ALLOWED = False
MIN_SAMPLE_N = 30
SIDES = ("LONG", "SHORT", "NO-TRADE")
HORIZONS = ("10s", "30s", "1m", "3m", "5m", "15m", "30m")
HORIZON_SECONDS = {
    "10s": 10,
    "30s": 30,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
}
FAMILIES = (
    "normal_gu",
    "normal_gd",
    "special_buy_continuation",
    "special_buy_gu_expansion",
    "gu_topping",
    "gu_shrink",
    "yoriten",
    "yorisoko",
    "pullback",
    "vwap_recovery",
    "or5_breakout",
    "or5_failure",
    "or15_breakout",
    "or15_failure",
    "skip",
)
QUOTE_FEATURES = (
    "gap_pct",
    "prev_close",
    "quote_price",
    "special_quote",
    "special_buy_duration_seconds",
    "gu_change_3m",
    "market_buy",
    "market_sell",
    "over_qty",
    "under_qty",
    "best_bid",
    "best_ask",
    "bid_qty",
    "ask_qty",
    "spread",
    "board_imbalance",
    "quote_change_speed",
    "open_price",
    "last_price",
    "session_high",
    "session_low",
    "vwap",
    "or5_high",
    "or5_low",
    "or5_complete",
    "or15_high",
    "or15_low",
    "or15_complete",
    "prior_last",
    "prior_vs_vwap",
)
EXTERNAL_FEATURES = (
    "nikkei_futures",
    "nikkei_topix_relative",
    "semiconductor_relative",
    "us_semiconductor",
    "nasdaq",
    "us_rates",
    "usdjpy",
    "oil",
    "gold",
    "silver",
    "copper",
    "regime_score",
)
SPECIAL_BUY_PARTS = (
    "special_buy_duration_seconds",
    "gap_pct",
    "gu_change_3m",
    "board_imbalance",
    "regime_score",
    "semiconductor_relative",
)
PREOPEN_START = time(8, 30, 0)
CLOCK_OPEN = time(9, 0, 0)
EV_ENTRY_THRESHOLD = 0.002


def parse_ts(value):
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith(" JST"):
            dt = datetime.strptime(text[: -len(" JST")], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def _iso(value):
    return parse_ts(value).isoformat()


def _blank_feature(name, status):
    return {
        "name": name,
        "value": None,
        "status": status,
        "available_at": None,
        "source": None,
        "live": False,
    }


def empty_observation(decision_at, symbol="285A.T"):
    """Every feed starts unconnected. Callers opt in per feature."""
    decision = parse_ts(decision_at)
    features = {}
    for name in QUOTE_FEATURES:
        features[name] = _blank_feature(name, "UNAVAILABLE")
    for name in EXTERNAL_FEATURES:
        features[name] = _blank_feature(name, "NOT_LIVE")
    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "decision_at": decision.isoformat(),
        "live_connected": False,
        "live_status": "NOT_LIVE",
        "features": features,
        "real_submit_allowed": False,
    }


def note_feature(observation, name, value, available_at, source, *, live=False, research=False):
    """Record one point-in-time value.

    A value whose available_at is after the decision is FUTURE and is not
    usable. A live=False value is kept only when research=True, and even
    then the observation stays NOT_LIVE. Unconnected feeds are not filled
    with zero.
    """
    if observation.get("real_submit_allowed") is not False:
        raise ValueError("real_submit_allowed must stay false")
    if name not in observation["features"]:
        raise KeyError(name)
    decision = parse_ts(observation["decision_at"])
    available = parse_ts(available_at)
    feature = dict(observation["features"][name])
    if available > decision:
        feature.update(value=None, status="FUTURE", available_at=available.isoformat(), source=source, live=False)
    elif value is None:
        status = "NOT_LIVE" if name in EXTERNAL_FEATURES else "UNAVAILABLE"
        feature.update(value=None, status=status, available_at=available.isoformat(), source=source, live=False)
    elif not live and not research:
        feature.update(value=None, status="NOT_LIVE", available_at=available.isoformat(), source=source, live=False)
    else:
        feature.update(value=value, status="OK", available_at=available.isoformat(), source=source, live=bool(live))
    features = dict(observation["features"])
    features[name] = feature
    out = dict(observation)
    out["features"] = features
    external_open = all(features[name]["status"] == "OK" and features[name]["live"] for name in EXTERNAL_FEATURES)
    out["live_connected"] = external_open
    out["live_status"] = "LIVE" if external_open else "NOT_LIVE"
    out["real_submit_allowed"] = False
    return out


def special_buy_context(observation):
    """Duration x GU x 3-minute GU speed x board x regime x semiconductor.

    The product exists only when every part is OK. Missing parts are not
    replaced with zero.
    """
    parts = {}
    blocked = None
    for name in SPECIAL_BUY_PARTS:
        feature = observation["features"][name]
        parts[name] = {"status": feature["status"], "value": feature["value"] if feature["status"] == "OK" else None}
        if feature["status"] != "OK" and blocked is None:
            blocked = feature["status"]
    if blocked is not None:
        return {"status": blocked, "value": None, "parts": parts}
    product = 1.0
    for name in SPECIAL_BUY_PARTS:
        product *= float(parts[name]["value"])
    return {"status": "OK", "value": product, "parts": parts}


def _ok(features, name):
    feature = features.get(name)
    return bool(feature) and feature["status"] == "OK" and feature["value"] is not None


def _num(features, name):
    return float(features[name]["value"])


def _gap_bucket(gap):
    if gap > 3:
        return "gu_large"
    if gap > 1:
        return "gu_medium"
    if gap > 0:
        return "gu_small"
    if gap < -3:
        return "gd_large"
    if gap < -1:
        return "gd_medium"
    if gap < 0:
        return "gd_small"
    return None


def _board_bucket(imbalance):
    if imbalance >= 0.2:
        return "buy_heavy"
    if imbalance <= -0.2:
        return "sell_heavy"
    return "balanced"


def _regime_bucket(score):
    return "risk_on" if score >= 0 else "risk_off"


def _semi_bucket(score):
    return "strong" if score >= 0 else "weak"


def _duration_bucket(seconds):
    if seconds < 180:
        return "short"
    if seconds < 540:
        return "mid"
    return "long"


def _speed_bucket(change):
    if change > 0.15:
        return "expand"
    if change < -0.15:
        return "shrink"
    return "flat"


def _scenario_id(family, bins):
    body = family + ":" + "|".join(key + "=" + bins[key] for key in sorted(bins))
    return "scev1:" + body


def build_catalog():
    """100 to 500 candidates. Families stay addressable; bins do the rest."""
    catalog = []

    def add(family, bins):
        catalog.append({
            "scenario_id": _scenario_id(family, bins),
            "family": family,
            "bins": dict(bins),
        })

    for gap in ("gu_small", "gu_medium", "gu_large"):
        for board in ("buy_heavy", "balanced", "sell_heavy"):
            for regime in ("risk_on", "risk_off"):
                add("normal_gu", {"gap": gap, "board": board, "regime": regime})
    for gap in ("gd_small", "gd_medium", "gd_large"):
        for board in ("buy_heavy", "balanced", "sell_heavy"):
            for regime in ("risk_on", "risk_off"):
                add("normal_gd", {"gap": gap, "board": board, "regime": regime})
    for duration in ("short", "mid", "long"):
        for speed in ("expand", "flat", "shrink"):
            for board in ("buy_heavy", "balanced", "sell_heavy"):
                for regime in ("risk_on", "risk_off"):
                    for semi in ("strong", "weak"):
                        add("special_buy_continuation", {
                            "duration": duration,
                            "speed": speed,
                            "board": board,
                            "regime": regime,
                            "semi": semi,
                        })
    for duration in ("short", "mid", "long"):
        for board in ("buy_heavy", "balanced", "sell_heavy"):
            for regime in ("risk_on", "risk_off"):
                for semi in ("strong", "weak"):
                    add("special_buy_gu_expansion", {
                        "duration": duration,
                        "speed": "expand",
                        "board": board,
                        "regime": regime,
                        "semi": semi,
                    })
    for speed in ("flat", "shrink"):
        for board in ("buy_heavy", "balanced", "sell_heavy"):
            add("gu_topping", {"speed": speed, "board": board})
    for board in ("buy_heavy", "balanced", "sell_heavy"):
        add("gu_shrink", {"speed": "shrink", "board": board})
    for family in ("yoriten", "yorisoko", "pullback", "vwap_recovery"):
        for gap_sign in ("gu", "flat", "gd"):
            for board in ("buy_heavy", "balanced", "sell_heavy"):
                add(family, {"gap_sign": gap_sign, "board": board})
    for family in ("or5_breakout", "or5_failure", "or15_breakout", "or15_failure"):
        for board in ("buy_heavy", "balanced", "sell_heavy"):
            for regime in ("risk_on", "risk_off"):
                add(family, {"board": board, "regime": regime})
    for phase in ("preopen", "special_buy", "post_open"):
        add("skip", {"phase": phase})
    if not 100 <= len(catalog) <= 500:
        raise RuntimeError("catalog size out of contract: %s" % len(catalog))
    return catalog


CATALOG = build_catalog()


def _gap_sign(gap):
    if gap > 0:
        return "gu"
    if gap < 0:
        return "gd"
    return "flat"


def candidate_matches(candidate, observation, phase):
    """Match using only features already OK at the decision time."""
    features = observation["features"]
    bins = candidate["bins"]
    family = candidate["family"]
    if "board" in bins:
        if not _ok(features, "board_imbalance"):
            return False
        if _board_bucket(_num(features, "board_imbalance")) != bins["board"]:
            return False
    if "regime" in bins:
        if not _ok(features, "regime_score"):
            return False
        if _regime_bucket(_num(features, "regime_score")) != bins["regime"]:
            return False
    if "semi" in bins:
        if not _ok(features, "semiconductor_relative"):
            return False
        if _semi_bucket(_num(features, "semiconductor_relative")) != bins["semi"]:
            return False
    if family == "normal_gu":
        if not _ok(features, "gap_pct") or not _ok(features, "special_quote"):
            return False
        gap = _num(features, "gap_pct")
        return features["special_quote"]["value"] == "none" and _gap_bucket(gap) == bins["gap"]
    if family == "normal_gd":
        if not _ok(features, "gap_pct") or not _ok(features, "special_quote"):
            return False
        gap = _num(features, "gap_pct")
        return features["special_quote"]["value"] == "none" and _gap_bucket(gap) == bins["gap"]
    if family in ("special_buy_continuation", "special_buy_gu_expansion"):
        needed = ("special_quote", "special_buy_duration_seconds", "gu_change_3m")
        if any(not _ok(features, name) for name in needed):
            return False
        if features["special_quote"]["value"] != "special_buy":
            return False
        if _duration_bucket(_num(features, "special_buy_duration_seconds")) != bins["duration"]:
            return False
        if _speed_bucket(_num(features, "gu_change_3m")) != bins["speed"]:
            return False
        return True
    if family == "gu_topping":
        if not _ok(features, "gap_pct") or not _ok(features, "gu_change_3m"):
            return False
        return _num(features, "gap_pct") > 0 and _speed_bucket(_num(features, "gu_change_3m")) == bins["speed"]
    if family == "gu_shrink":
        if not _ok(features, "gu_change_3m"):
            return False
        return _speed_bucket(_num(features, "gu_change_3m")) == "shrink"
    if family in ("yoriten", "yorisoko", "pullback", "vwap_recovery"):
        if not _ok(features, "gap_pct"):
            return False
        if _gap_sign(_num(features, "gap_pct")) != bins["gap_sign"]:
            return False
        if family == "yoriten":
            needed = ("open_price", "last_price", "session_high")
            if any(not _ok(features, name) for name in needed):
                return False
            return _num(features, "session_high") > _num(features, "open_price") and _num(features, "last_price") < _num(features, "open_price")
        if family == "yorisoko":
            needed = ("open_price", "last_price", "session_low")
            if any(not _ok(features, name) for name in needed):
                return False
            return _num(features, "session_low") < _num(features, "open_price") and _num(features, "last_price") > _num(features, "open_price")
        if family == "pullback":
            needed = ("last_price", "session_high", "open_price")
            if any(not _ok(features, name) for name in needed):
                return False
            return (
                _num(features, "gap_pct") > 0
                and _num(features, "last_price") < _num(features, "session_high")
                and _num(features, "last_price") > _num(features, "open_price")
            )
        if not _ok(features, "vwap") or not _ok(features, "last_price") or not _ok(features, "prior_vs_vwap"):
            return False
        return features["prior_vs_vwap"]["value"] == "below" and _num(features, "last_price") >= _num(features, "vwap")
    if family in ("or5_breakout", "or5_failure", "or15_breakout", "or15_failure"):
        if not _ok(features, "last_price"):
            return False
        last = _num(features, "last_price")
        if family == "or5_breakout":
            return _ok(features, "or5_complete") and features["or5_complete"]["value"] is True and _ok(features, "or5_high") and last > _num(features, "or5_high")
        if family == "or5_failure":
            return _ok(features, "or5_complete") and features["or5_complete"]["value"] is True and _ok(features, "or5_low") and last < _num(features, "or5_low")
        if family == "or15_breakout":
            return _ok(features, "or15_complete") and features["or15_complete"]["value"] is True and _ok(features, "or15_high") and last > _num(features, "or15_high")
        return _ok(features, "or15_complete") and features["or15_complete"]["value"] is True and _ok(features, "or15_low") and last < _num(features, "or15_low")
    if family == "skip":
        return _ok(features, "quote_price") and phase == bins["phase"]
    return False


def session_phase(observed_at, open_anchor_at, special_quote):
    observed = parse_ts(observed_at)
    if observed.timetz().replace(tzinfo=None) < PREOPEN_START:
        raise ValueError("TOO_EARLY")
    if open_anchor_at is not None and observed >= parse_ts(open_anchor_at):
        return "post_open"
    if special_quote == "special_buy":
        return "special_buy"
    return "preopen"


def net_return(side, entry_price, exit_price, slippage_bps, cost_bps):
    if side not in SIDES:
        raise ValueError("unknown side")
    if slippage_bps is None or cost_bps is None:
        raise ValueError("slippage and transaction cost are required")
    slip = (float(slippage_bps) + float(cost_bps)) / 10000.0
    if side == "NO-TRADE":
        return 0.0
    entry = float(entry_price)
    if entry <= 0:
        raise ValueError("entry price must be positive")
    gross = (float(exit_price) - entry) / entry
    if side == "SHORT":
        gross = -gross
    return gross - slip


def _max_drawdown(pnls):
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def estimate_rows(rows, min_n=MIN_SAMPLE_N):
    """One side and one horizon. Small samples do not publish an EV."""
    cleaned = []
    for row in rows:
        if "slippage_bps" not in row or "cost_bps" not in row:
            raise ValueError("slippage and transaction cost are required")
        side = row["side"]
        if side == "NO-TRADE" and (float(row.get("mfe_pct") or 0) != 0 or float(row.get("mae_pct") or 0) != 0):
            raise ValueError("NO-TRADE cannot carry an excursion")
        decision = parse_ts(row["decision_at"])
        known = parse_ts(row["outcome_known_at"])
        horizon = HORIZON_SECONDS[row["horizon"]]
        if known < decision + timedelta(seconds=horizon):
            raise ValueError("outcome is not known yet")
        feature_at = parse_ts(row["feature_available_at"])
        if feature_at > decision:
            raise ValueError("future information")
        pnl = net_return(side, row.get("entry_price"), row.get("exit_price"), row["slippage_bps"], row["cost_bps"])
        cleaned.append((decision, pnl, float(row.get("mfe_pct") or 0), float(row.get("mae_pct") or 0), float(row["slippage_bps"])))
    cleaned.sort(key=lambda item: item[0])
    n = len(cleaned)
    hidden = {
        "status": "INSUFFICIENT_SAMPLE",
        "display_ev": False,
        "sample_n": n,
        "net_ev": None,
        "win_rate": None,
        "profit_factor": None,
        "mfe": None,
        "mae": None,
        "max_dd": None,
        "mean_slippage_bps": None,
        "confidence": "INSUFFICIENT_SAMPLE",
        "real_submit_allowed": False,
    }
    if n < min_n:
        return hidden
    pnls = [item[1] for item in cleaned]
    wins = [item for item in pnls if item > 0]
    losses = [item for item in pnls if item < 0]
    pf = None
    if losses:
        pf = sum(wins) / abs(sum(losses))
    return {
        "status": "SUFFICIENT",
        "display_ev": True,
        "sample_n": n,
        "net_ev": sum(pnls) / n,
        "win_rate": len(wins) / n,
        "profit_factor": pf,
        "mfe": sum(item[2] for item in cleaned) / n,
        "mae": sum(item[3] for item in cleaned) / n,
        "max_dd": _max_drawdown(pnls),
        "mean_slippage_bps": sum(item[4] for item in cleaned) / n,
        "confidence": "SUFFICIENT",
        "estimate_scope": "scenario",
        "merged": False,
        "real_submit_allowed": False,
    }


def _usable(outcomes, decision_at):
    decision = parse_ts(decision_at)
    usable = []
    for row in outcomes:
        if parse_ts(row["outcome_known_at"]) <= decision:
            usable.append(row)
    return usable


def _group_rows(outcomes, scenario_id, side, horizon):
    return [
        row for row in outcomes
        if row["scenario_id"] == scenario_id and row["side"] == side and row["horizon"] == horizon
    ]


def estimate_catalog(outcomes, decision_at, catalog=None, min_n=MIN_SAMPLE_N):
    """Train-only estimates. Rows whose horizon has not elapsed are excluded."""
    catalog = catalog if catalog is not None else CATALOG
    usable = _usable(outcomes, decision_at)
    by_family = {}
    for row in usable:
        by_family.setdefault((row.get("family"), row["side"], row["horizon"], row.get("merge_sign")), []).append(row)
    published = {}
    for candidate in catalog:
        family = candidate["family"]
        sign = candidate["bins"].get("speed") or candidate["bins"].get("gap") or candidate["bins"].get("gap_sign") or candidate["bins"].get("phase")
        published[candidate["scenario_id"]] = {}
        for side in SIDES:
            published[candidate["scenario_id"]][side] = {}
            for horizon in HORIZONS:
                own = estimate_rows(_group_rows(usable, candidate["scenario_id"], side, horizon), min_n=min_n)
                if own["status"] != "SUFFICIENT":
                    pool = by_family.get((family, side, horizon, sign), [])
                    pool = [row for row in pool if row["scenario_id"] != candidate["scenario_id"]]
                    own_rows = _group_rows(usable, candidate["scenario_id"], side, horizon)
                    merged_rows = own_rows + pool
                    if len(merged_rows) >= min_n and own_rows:
                        merged = estimate_rows(merged_rows, min_n=min_n)
                        merged["estimate_scope"] = "merged_similar"
                        merged["merged"] = True
                        own = merged
                published[candidate["scenario_id"]][side][horizon] = own
    return published


def walk_forward(outcomes, min_train=MIN_SAMPLE_N, test_size=10, min_n=MIN_SAMPLE_N):
    """Expanding window. A test row cannot enter its own training set."""
    ordered = sorted(outcomes, key=lambda row: parse_ts(row["outcome_known_at"]))
    folds = []
    start = min_train
    while start < len(ordered):
        end = min(len(ordered), start + test_size)
        train = ordered[:start]
        test = ordered[start:end]
        train_end = parse_ts(train[-1]["outcome_known_at"])
        train_ids = {id(row) for row in train}
        if any(id(row) in train_ids for row in test):
            raise ValueError("future information")
        oos_rows = [row for row in test if parse_ts(row["outcome_known_at"]) > train_end]
        folds.append({
            "train_n": len(train),
            "oos_n": len(oos_rows),
            "train_end": train_end.isoformat(),
            "oos_estimate": estimate_rows(oos_rows, min_n=min_n) if oos_rows else estimate_rows([], min_n=min_n),
            "real_submit_allowed": False,
        })
        start = end
    return {"policy": "expanding_window_walk_forward", "folds": folds, "real_submit_allowed": False}


def _content_hash(payload):
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class ScenarioLog:
    """Append-only snapshots, shadow candidates, and close scores."""

    def __init__(self):
        self.records = []
        self._by_id = {}
        self.open_anchor_at = None

    def append(self, record):
        if record.get("real_submit_allowed") is not False:
            raise ValueError("real_submit_allowed must stay false")
        record_id = record["record_id"]
        if record_id in self._by_id:
            raise ValueError("immutable record")
        stored = json.loads(json.dumps(record))
        stored["content_hash"] = _content_hash({key: value for key, value in stored.items() if key != "content_hash"})
        stored["real_submit_allowed"] = False
        self.records.append(stored)
        self._by_id[record_id] = stored
        return stored

    def record_snapshot(self, observation, outcomes, open_anchor_at=None, catalog=None):
        observed = parse_ts(observation["decision_at"])
        phase = session_phase(
            observed,
            open_anchor_at,
            observation["features"]["special_quote"]["value"] if observation["features"]["special_quote"]["status"] == "OK" else None,
        )
        if open_anchor_at is not None:
            anchor = _iso(open_anchor_at)
            if self.open_anchor_at is None:
                self.open_anchor_at = anchor
            elif self.open_anchor_at != anchor:
                raise ValueError("ANCHOR_CONFLICT")
        estimates = estimate_catalog(outcomes, observed, catalog=catalog)
        matched = []
        for candidate in (catalog or CATALOG):
            if not candidate_matches(candidate, observation, phase):
                continue
            sides = {}
            for side in SIDES:
                cell = estimates[candidate["scenario_id"]][side]["1m"]
                sides[side] = {
                    "status": cell["status"],
                    "display_ev": cell["display_ev"],
                    "net_ev": cell["net_ev"],
                    "win_rate": cell["win_rate"],
                    "profit_factor": cell["profit_factor"],
                    "sample_n": cell["sample_n"],
                    "mfe": cell["mfe"],
                    "mae": cell["mae"],
                    "max_dd": cell["max_dd"],
                    "confidence": cell["confidence"],
                    "merged": cell.get("merged", False),
                }
            frequency = _scenario_frequency(outcomes, observed, candidate["scenario_id"])
            matched.append({
                "scenario_id": candidate["scenario_id"],
                "family": candidate["family"],
                "probability": frequency["probability"],
                "probability_status": frequency["status"],
                "sides": sides,
            })
        event_kind = "QUOTE_UPDATE"
        if open_anchor_at is not None and parse_ts(open_anchor_at) == observed:
            event_kind = "OPEN_ANCHOR"
        elif _special_buy_3m(observed, observation):
            event_kind = "SPECIAL_BUY_3M"
        record = {
            "record_id": "snap:" + observed.strftime("%Y%m%dT%H%M%S") + ":" + str(len(self.records) + 1),
            "record_type": "snapshot",
            "schema_version": SCHEMA_VERSION,
            "symbol": observation["symbol"],
            "observed_at": observed.isoformat(),
            "phase": phase,
            "open_anchor_at": self.open_anchor_at,
            "event_kind": event_kind,
            "live_status": observation["live_status"],
            "features": observation["features"],
            "special_buy_context": special_buy_context(observation),
            "matched": matched,
            "real_submit_allowed": False,
        }
        return self.append(record)

    def propose_shadow(self, snapshot_record, horizon="1m", threshold=EV_ENTRY_THRESHOLD):
        """A virtual candidate only. The snapshot itself is not rewritten."""
        if snapshot_record["record_id"] not in self._by_id:
            raise KeyError(snapshot_record["record_id"])
        best = None
        for match in snapshot_record["matched"]:
            for side in ("LONG", "SHORT"):
                cell = match["sides"][side]
                if not cell["display_ev"] or cell["net_ev"] is None:
                    continue
                if cell["net_ev"] < threshold:
                    continue
                if best is None or cell["net_ev"] > best["net_ev"]:
                    best = {
                        "scenario_id": match["scenario_id"],
                        "side": side,
                        "net_ev": cell["net_ev"],
                        "sample_n": cell["sample_n"],
                        "confidence": cell["confidence"],
                    }
        if best is None:
            return None
        before = snapshot_record["content_hash"]
        record = {
            "record_id": "shadow:" + snapshot_record["record_id"] + ":" + best["scenario_id"] + ":" + best["side"],
            "record_type": "shadow_candidate",
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot_record["record_id"],
            "scenario_id": best["scenario_id"],
            "side": best["side"],
            "horizon": horizon,
            "decision_at": snapshot_record["observed_at"],
            "feature_hash": _content_hash(snapshot_record["features"]),
            "net_ev": best["net_ev"],
            "sample_n": best["sample_n"],
            "confidence": best["confidence"],
            "quantity": None,
            "real_submit_allowed": False,
        }
        stored = self.append(record)
        if self._by_id[snapshot_record["record_id"]]["content_hash"] != before:
            raise ValueError("snapshot was rewritten")
        return stored

    def score_after_close(self, candidate, close_at, entry_price, exit_price, slippage_bps, cost_bps, mfe_pct, mae_pct):
        """Write a score beside the candidate. The candidate stays unchanged."""
        original = self._by_id[candidate["record_id"]]
        before = original["content_hash"]
        close = parse_ts(close_at)
        decision = parse_ts(candidate["decision_at"])
        if close < decision + timedelta(seconds=HORIZON_SECONDS[candidate["horizon"]]):
            raise ValueError("outcome is not known yet")
        if candidate["side"] == "NO-TRADE" and (mfe_pct or mae_pct):
            raise ValueError("NO-TRADE cannot carry an excursion")
        pnl = net_return(candidate["side"], entry_price, exit_price, slippage_bps, cost_bps)
        score = {
            "record_id": "score:" + candidate["record_id"],
            "record_type": "shadow_score",
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate["record_id"],
            "scenario_id": candidate["scenario_id"],
            "side": candidate["side"],
            "horizon": candidate["horizon"],
            "decision_at": candidate["decision_at"],
            "outcome_known_at": close.isoformat(),
            "feature_available_at": candidate["decision_at"],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "slippage_bps": slippage_bps,
            "cost_bps": cost_bps,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "net_pnl": pnl,
            "next_day_sample": True,
            "real_submit_allowed": False,
        }
        stored = self.append(score)
        if self._by_id[candidate["record_id"]]["content_hash"] != before:
            raise ValueError("candidate was rewritten")
        return stored


def _scenario_frequency(outcomes, decision_at, scenario_id):
    usable = [
        row for row in _usable(outcomes, decision_at)
        if row["horizon"] == "1m" and row["side"] == "LONG"
    ]
    n = len(usable)
    if n < MIN_SAMPLE_N:
        return {"status": "INSUFFICIENT_SAMPLE", "probability": None, "sample_n": n}
    hits = sum(1 for row in usable if row["scenario_id"] == scenario_id)
    return {"status": "SUFFICIENT", "probability": hits / n, "sample_n": n}


def _special_buy_3m(observed, observation):
    feature = observation["features"]["special_quote"]
    if feature["status"] != "OK" or feature["value"] != "special_buy":
        return False
    local = observed.timetz().replace(tzinfo=None)
    if local < CLOCK_OPEN:
        return False
    if observed.second != 0 or observed.microsecond != 0:
        return False
    minutes = (local.hour * 60 + local.minute) - (9 * 60)
    return minutes >= 0 and minutes % 3 == 0


def _ev_change_reason(previous, current):
    if previous is None:
        return "first_snapshot"
    changed = []
    for name, feature in current["features"].items():
        prior = previous["features"].get(name)
        if prior is None:
            continue
        if feature["status"] == "OK" and feature["value"] != prior.get("value"):
            changed.append(name)
    if not changed:
        return "no_feature_change"
    return "changed:" + ",".join(sorted(changed))


def build_dashboard_payload(log, focus_horizon="1m"):
    """Data for a later dashboard. Insufficient cells stay null."""
    snapshots = [record for record in log.records if record["record_type"] == "snapshot"]
    race = []
    previous = None
    top3 = []
    timeline = []
    for snapshot in snapshots:
        point = {"observed_at": snapshot["observed_at"], "status": "INSUFFICIENT_SAMPLE",
                 "long_net_ev": None, "short_net_ev": None, "no_trade_net_ev": None}
        best = {"LONG": None, "SHORT": None, "NO-TRADE": None}
        ranked = []
        for match in snapshot["matched"]:
            for side in SIDES:
                cell = match["sides"][side]
                ranked.append((cell["net_ev"], cell["display_ev"], match, side, cell))
                if cell["display_ev"] and cell["net_ev"] is not None:
                    current = best[side]
                    if current is None or cell["net_ev"] > current:
                        best[side] = cell["net_ev"]
        if any(value is not None for value in best.values()):
            point["status"] = "SUFFICIENT"
            point["long_net_ev"] = best["LONG"]
            point["short_net_ev"] = best["SHORT"]
            point["no_trade_net_ev"] = best["NO-TRADE"]
        race.append(point)
        if snapshot["event_kind"] == "SPECIAL_BUY_3M":
            context = snapshot["special_buy_context"]
            timeline.append({
                "observed_at": snapshot["observed_at"],
                "event_kind": "SPECIAL_BUY_3M",
                "status": context["status"],
                "gu_pct": context["parts"]["gap_pct"]["value"],
                "duration_seconds": context["parts"]["special_buy_duration_seconds"]["value"],
            })
        previous = snapshot
    if snapshots:
        latest = snapshots[-1]
        prior = snapshots[-2] if len(snapshots) > 1 else None
        reason = _ev_change_reason(prior, latest)
        ranked = []
        for match in latest["matched"]:
            for side in SIDES:
                cell = match["sides"][side]
                ranked.append((
                    cell["net_ev"] if cell["display_ev"] and cell["net_ev"] is not None else float("-inf"),
                    match,
                    side,
                    cell,
                ))
        ranked.sort(key=lambda item: item[0], reverse=True)
        for _, match, side, cell in ranked[:3]:
            top3.append({
                "scenario_id": match["scenario_id"],
                "side": side,
                "probability": match["probability"],
                "net_ev": cell["net_ev"] if cell["display_ev"] else None,
                "profit_factor": cell["profit_factor"] if cell["display_ev"] else None,
                "sample_n": cell["sample_n"],
                "confidence": cell["confidence"],
                "ev_change_reason": reason,
                "display_ev": cell["display_ev"],
                "horizon": focus_horizon,
            })
    heatmap = _heatmap(snapshots[-1] if snapshots else None)
    live_status = snapshots[-1]["live_status"] if snapshots else "NOT_LIVE"
    return {
        "schema_version": SCHEMA_VERSION,
        "live_status": live_status,
        "real_submit_allowed": False,
        "race": race,
        "top3": top3,
        "special_buy_timeline": timeline,
        "heatmap": heatmap,
        "open_anchor_at": log.open_anchor_at,
        "focus_horizon": focus_horizon,
    }


def _heatmap(snapshot):
    rows = ["gu_large", "gu_medium", "gu_small", "flat", "gd_small", "gd_medium", "gd_large"]
    cols = ["short", "mid", "long"]
    cells = []
    current = None
    current_ev = None
    current_status = "INSUFFICIENT_SAMPLE"
    current_display = False
    if snapshot is not None:
        features = snapshot["features"]
        if _ok(features, "gap_pct") and _ok(features, "special_buy_duration_seconds"):
            current = {
                "row": _gap_bucket(_num(features, "gap_pct")) or "flat",
                "col": _duration_bucket(_num(features, "special_buy_duration_seconds")),
            }
        for match in snapshot["matched"]:
            if match["family"] != "special_buy_continuation":
                continue
            cell = match["sides"]["LONG"]
            if cell["display_ev"] and cell["net_ev"] is not None:
                current_ev = cell["net_ev"]
                current_status = "SUFFICIENT"
                current_display = True
    for row in rows:
        for col in cols:
            is_current = current is not None and current["row"] == row and current["col"] == col
            cells.append({
                "gap_bucket": row,
                "duration_bucket": col,
                "status": current_status if is_current else "INSUFFICIENT_SAMPLE",
                "net_ev": current_ev if is_current else None,
                "display_ev": current_display if is_current else False,
                "current": is_current,
            })
    return {"rows": rows, "cols": cols, "cells": cells, "live_status": "NOT_LIVE" if snapshot is None or snapshot["live_status"] != "LIVE" else "LIVE"}


def outcome_from_score(score, family, merge_sign):
    """A close score can enter the next session as a sample. It is a new row."""
    return {
        "outcome_id": score["record_id"],
        "scenario_id": score["scenario_id"],
        "family": family,
        "merge_sign": merge_sign,
        "side": score["side"],
        "horizon": score["horizon"],
        "decision_at": score["decision_at"],
        "outcome_known_at": score["outcome_known_at"],
        "feature_available_at": score["feature_available_at"],
        "entry_price": score["entry_price"],
        "exit_price": score["exit_price"],
        "slippage_bps": score["slippage_bps"],
        "cost_bps": score["cost_bps"],
        "mfe_pct": score["mfe_pct"],
        "mae_pct": score["mae_pct"],
        "real_submit_allowed": False,
    }
