"""V10 Brain core: pick the 1-3 live signals with the highest expected value (NO orders).

OWNER 2026-10-21 「１の期待値を最大限にするためにこのシステム開発をしている」「全部やりたい」.
Every Brain pass scores the signals lit in the Controller's live_ms2.json with
what the recorded history says about them:

  * an OWNER rule (R1/R2 of the rule Shadow) that matches the signal's side, the
    JST time and the market state: its backtest (later half, weighted 0.5) and
    its forward results from 2026-10-22, with the rule's own wider target/stop;
  * otherwise the EV table of the same strategy on the same stock, then the same
    strategy on all stocks.

The estimate is shrunk toward zero by the number of trades behind it
(n / (n + SHRINK_N)) so thin evidence cannot top the list. Shorts on stocks with
more margin sells than buys (信用倍率 < 1, squeeze risk) are left out; a missing
倍率 is shown as unverified. The top MAX_PICKS stocks whose score is at least
MIN_SCORE_PCT are picked, and every new pick is appended to
records/<day>/brain_picks.csv in the trade_signals.csv layout so the rule
Shadow replays the Brain's own choices on the recorded ticks (forward["BRAIN"]).
Virtual only: real_submit_allowed and trade_instruction are always false.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

SCHEMA = "100b-v10-brain-pick-v1"
JST = timezone(timedelta(hours=9))
SIDES = {"買いサイン": 1, "空売りサイン": -1}
MAX_PICKS = 3
MAX_LIVE_AGE_SECONDS = 60
SHRINK_N = 30                      # PROVISIONAL
BACKTEST_WEIGHT = 0.5              # PROVISIONAL: the backtest chose the rule, so it counts half
MIN_SCORE_PCT = 0.03               # PROVISIONAL: below this a pick would not survive a tick of slippage
SHORT_MIN_CREDIT_RATIO = 1.0       # PROVISIONAL: 売り長 (倍率 < 1) shorts are left out
BUY_HEAVY_CREDIT_RATIO = 10.0      # PROVISIONAL: shown as a caution only
PICKS_FILE = "brain_picks.csv"
PICK_FIELDS = ["captured_at", "ticker", "name", "signal", "strategy", "signal_bar", "entry", "stop", "target1",
               "market_state", "rule", "score_pct", "source"]


def _f(raw):
    try:
        value = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _live_time(raw) -> datetime | None:
    text = str(raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=JST)
        except ValueError:
            continue
    return None


def rule_for(rules: dict, row: dict, hm: str):
    side = SIDES.get(row.get("signal"))
    for key, rule in (rules or {}).items():
        if rule.get("side") != side or not (rule.get("from", "") <= hm < rule.get("to", "")):
            continue
        if rule.get("market") and rule["market"] not in str(row.get("market_state", "")):
            continue
        return key, rule
    return None, None


def estimate(row: dict, *, ev_table: dict | None, rule_shadow: dict | None, hm: str) -> dict:
    """Expected net return in % of one trade on this signal, and what it rests on."""
    key, rule = rule_for((rule_shadow or {}).get("rules"), row, hm)
    if rule:
        test = (rule.get("backtest") or {}).get("test") or {}
        fwd = ((rule_shadow or {}).get("forward") or {}).get(key) or {}
        w_bt = BACKTEST_WEIGHT * (test.get("n") or 0)
        n_fw = fwd.get("n") or 0
        ev_bt, ev_fw = _f(test.get("ev_pct")) or 0.0, _f(fwd.get("ev_pct")) or 0.0
        n_eff = w_bt + n_fw
        ev = (w_bt * ev_bt + n_fw * ev_fw) / n_eff if n_eff else None
        return {"rule": key, "label": rule.get("label"), "ev_pct": ev, "n_eff": n_eff, "source": "RULE",
                "target_mult": rule.get("target_mult", 1.0), "stop_mult": rule.get("stop_mult", 1.0)}
    strat = str(row.get("strategy", "")) + "|" + str(row.get("signal", ""))
    for level, stat in (("TICKER", ((ev_table or {}).get("by_strategy_ticker") or {}).get(strat + "|" + str(row.get("ticker", "")))),
                        ("STRATEGY", ((ev_table or {}).get("by_strategy") or {}).get(strat))):
        if stat and stat.get("status") == "OK" and _f(stat.get("ev_pct")) is not None:
            return {"rule": None, "label": None, "ev_pct": _f(stat["ev_pct"]), "n_eff": stat.get("n") or 0,
                    "source": level, "target_mult": 1.0, "stop_mult": 1.0}
    return {"rule": None, "label": None, "ev_pct": None, "n_eff": 0, "source": "NONE", "target_mult": 1.0, "stop_mult": 1.0}


def pick(live: dict, *, ev_table: dict | None, rule_shadow: dict | None, now: datetime) -> dict:
    local = now.astimezone(JST)
    hm = local.strftime("%H:%M")
    base = {"schema_version": SCHEMA, "generated_at": now.astimezone(timezone.utc).isoformat(), "picks": [],
            "excluded": [], "considered": 0, "real_submit_allowed": False, "trade_instruction": False,
            "thresholds": {"max_picks": MAX_PICKS, "shrink_n": SHRINK_N, "backtest_weight": BACKTEST_WEIGHT,
                           "min_score_pct": MIN_SCORE_PCT, "short_min_credit_ratio": SHORT_MIN_CREDIT_RATIO,
                           "status": "PROVISIONAL"},
            "ev_table_days": len((ev_table or {}).get("days") or []), "rule_forward_from": (rule_shadow or {}).get("forward_from")}
    updated = _live_time(live.get("updated_at"))
    base["live_updated_at"] = updated.isoformat() if updated else None
    if (live.get("valid") is not True or live.get("stale") is not False or updated is None
            or not timedelta(seconds=-5) <= local - updated <= timedelta(seconds=MAX_LIVE_AGE_SECONDS)):
        return dict(base, state="NOT_LIVE")
    scored = []
    for row in live.get("all_targets") or []:
        side = SIDES.get(row.get("signal"))
        if side is None:
            continue
        base["considered"] += 1
        name = row.get("name") or row.get("ticker")
        if row.get("aggregate_row_fresh") is not True:
            base["excluded"].append({"ticker": row.get("ticker"), "name": name, "reason": "行の鮮度未確認"})
            continue
        entry, stop, target = _f(row.get("entry_price")), _f(row.get("stop_price")), _f(row.get("target1"))
        if None in (entry, stop, target) or entry <= 0:
            base["excluded"].append({"ticker": row.get("ticker"), "name": name, "reason": "発動・損切・目標が未確定"})
            continue
        est = estimate(row, ev_table=ev_table, rule_shadow=rule_shadow, hm=hm)
        flags = []
        ratio = _f(row.get("credit_ratio"))
        if ratio is None:
            flags.append("信用倍率不明（空売り状況 未確認）")
        elif side < 0 and ratio < SHORT_MIN_CREDIT_RATIO:
            base["excluded"].append({"ticker": row.get("ticker"), "name": name, "reason": "売り長（信用倍率%.2f）踏み上げ注意" % ratio})
            continue
        elif side > 0 and ratio >= BUY_HEAVY_CREDIT_RATIO:
            flags.append("買い長（信用倍率%.1f）戻り売り注意" % ratio)
        if est["ev_pct"] is None:
            base["excluded"].append({"ticker": row.get("ticker"), "name": name, "reason": "根拠不足（記録20回未満）"})
            continue
        score = est["ev_pct"] * est["n_eff"] / (est["n_eff"] + SHRINK_N)
        dist = abs(target - entry)
        scored.append({"ticker": row.get("ticker"), "name": name, "side": side, "signal": row.get("signal"),
                       "strategy": row.get("strategy"), "signal_bar": row.get("signal_bar_time"),
                       "market_state": row.get("market_state"), "entry": entry,
                       "target": round(entry + side * est["target_mult"] * dist, 4),
                       "stop": round(entry - side * est["stop_mult"] * dist, 4),
                       "signal_stop": stop, "signal_target": target, "score_pct": round(score, 4),
                       "ev_pct": round(est["ev_pct"], 4), "n_eff": round(est["n_eff"], 1), "source": est["source"],
                       "rule": est["rule"], "rule_label": est["label"], "flags": flags})
    scored.sort(key=lambda s: -s["score_pct"])
    seen = set()
    for s in scored:
        if s["ticker"] in seen:
            continue
        seen.add(s["ticker"])
        if s["score_pct"] < MIN_SCORE_PCT or len(base["picks"]) >= MAX_PICKS:
            base["excluded"].append({"ticker": s["ticker"], "name": s["name"],
                                     "reason": ("期待値%+.3f%%（基準%.2f%%未満）" % (s["score_pct"], MIN_SCORE_PCT))
                                     if s["score_pct"] < MIN_SCORE_PCT else "上位%d件の外" % MAX_PICKS})
            continue
        base["picks"].append(dict(s, rank=len(base["picks"]) + 1))
    base["excluded"] = base["excluded"][:20]
    return dict(base, state="PICK" if base["picks"] else "NO_PICK")


def log_new_picks(records: Path, view: dict, *, now: datetime, logged: set) -> int:
    """Append each pick not yet logged today (same stock, strategy, side and signal bar)."""
    if view.get("state") != "PICK":
        return 0
    local = now.astimezone(JST)
    day_dir = Path(records) / local.date().isoformat()
    path = day_dir / PICKS_FILE
    if not logged and path.is_file():
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                logged.add((r.get("ticker"), r.get("strategy"), r.get("signal"), r.get("signal_bar")))
    new = []
    for p in view["picks"]:
        key = (p["ticker"], p["strategy"], p["signal"], p["signal_bar"])
        if key in logged:
            continue
        logged.add(key)
        new.append({"captured_at": local.strftime("%Y-%m-%d %H:%M:%S"), "ticker": p["ticker"], "name": p["name"],
                    "signal": p["signal"], "strategy": p["strategy"], "signal_bar": p["signal_bar"] or "",
                    "entry": p["entry"], "stop": p["signal_stop"], "target1": p["signal_target"],
                    "market_state": p["market_state"] or "", "rule": p["rule"] or "", "score_pct": p["score_pct"],
                    "source": p["source"]})
    if not new:
        return 0
    day_dir.mkdir(parents=True, exist_ok=True)
    first = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8-sig" if first else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PICK_FIELDS)
        if first:
            w.writeheader()
        w.writerows(new)
    return len(new)


def _read_json(path: Path, schema: str):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("schema_version") != schema or data.get("real_submit_allowed") is not False:
        return None
    return data


def write_pick(runtime: Path, live: dict, *, now: datetime, logged: set) -> dict:
    runtime = Path(runtime)
    ev_table = _read_json(runtime / "signal_ev_table_v1.json", "100b-v10-signal-ev-table-v1")
    rule_shadow = _read_json(runtime / "rule_shadow_v1.json", "100b-v10-rule-shadow-v1")
    view = pick(live, ev_table=ev_table, rule_shadow=rule_shadow, now=now)
    view["logged_new"] = log_new_picks(runtime / "records", view, now=now, logged=logged)
    target = runtime / "brain_pick_v1.json"
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temp.replace(target)
    return view
