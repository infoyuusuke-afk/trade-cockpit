"""V10 Brain core: pick the 1-3 live signals with the highest expected value (NO orders).

OWNER 2026-10-21 「１の期待値を最大限にするためにこのシステム開発をしている」「全部やりたい」.
Every Brain pass scores the signals lit in the Controller's live_ms2.json with
what the recorded history says about them:

  * the best supported OWNER rule of the rule Shadow (R1/R2/R4/R5) that matches the
    signal's side, strategy, JST time, market state and open/gap conditions: its
    backtest test block, weighted by the rule's backtest_weight (0.5 for R1/R2, whose
    test block was out of sample; 0.1 for the search-selected R4/R5), plus its
    forward results from 2026-10-22, with the rule's own wider target/stop;
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
BACKTEST_WEIGHT = 0.5              # PROVISIONAL default; a rule's own "backtest_weight" wins
MIN_VALID_ROWS, MAX_VALID_ROWS = 90, 110   # the Collector's integer valid count (same bounds as the observer)
MIN_SCORE_PCT = 0.03               # PROVISIONAL: below this a pick would not survive a tick of slippage
SHORT_MIN_CREDIT_RATIO = 1.0       # PROVISIONAL: 売り長 (倍率 < 1) shorts are left out
BUY_HEAVY_CREDIT_RATIO = 10.0      # PROVISIONAL: shown as a caution only
PICKS_FILE = "brain_picks.csv"
PICK_FIELDS = ["captured_at", "ticker", "name", "signal", "strategy", "signal_bar", "entry", "stop", "target1",
               "market_state", "rule", "score_pct", "source"]
# OWNER 2026-10-23 「画面の一番上に『注目』欄を常に出し、ブレインのランキングに新しく入った銘柄と
# ルール①②④⑤のサインが出た銘柄を、時刻・社名・ルール名付きで新しい順に並べ、その日の分は消さずに残す」:
# each rule signal is logged once (same stock, strategy, side, signal bar and rule), and the
# pick file carries the whole day's 注目 list for the screen. Display only; no orders.
RULE_SIGNALS_FILE = "brain_rule_signals.csv"
RULE_SIGNAL_FIELDS = ["captured_at", "ticker", "name", "signal", "strategy", "signal_bar", "rule", "entry", "target",
                      "stop"]


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


MAX_GAP_PCT = 20.0  # same as the rule Shadow: a larger gap is a split, not a market gap


def _context_ok(rule: dict, row: dict, side: int) -> bool:
    """R4: the entry is at least min_move_pct beyond the day's open in the signal's
    direction. R5: the day opened at least 1 % below the reference price (前日終値)."""
    open_ = _f(row.get("open_price"))
    if rule.get("min_move_pct") is not None:
        entry = _f(row.get("entry_price"))
        if not open_ or open_ <= 0 or entry is None or side * (entry / open_ - 1) * 100 < rule["min_move_pct"]:
            return False
    if rule.get("gap") == "down":
        ref = _f(row.get("reference_price"))
        if not open_ or not ref or ref <= 0:
            return False
        gap = (open_ / ref - 1) * 100
        if gap > -1.0 or abs(gap) >= MAX_GAP_PCT:
            return False
    return True


def rules_for(rules: dict, row: dict, hm: str) -> list:
    side = SIDES.get(row.get("signal"))
    out = []
    for key, rule in (rules or {}).items():
        if rule.get("side") != side or not (rule.get("from", "") <= hm < rule.get("to", "")):
            continue
        if rule.get("market") and rule["market"] not in str(row.get("market_state", "")):
            continue
        if rule.get("strategy") and rule["strategy"] != row.get("strategy"):
            continue
        if not _context_ok(rule, row, side):
            continue
        out.append((key, rule))
    return out


def estimate(row: dict, *, ev_table: dict | None, rule_shadow: dict | None, hm: str) -> dict:
    """Expected net return in % of one trade on this signal, and what it rests on."""
    best = None
    for key, rule in rules_for((rule_shadow or {}).get("rules"), row, hm):
        if rule.get("record_only"):   # OWNER 2026-10-26: recorded, never scored
            continue
        test = (rule.get("backtest") or {}).get("test") or {}
        fwd = ((rule_shadow or {}).get("forward") or {}).get(key) or {}
        weight = _f(rule.get("backtest_weight"))
        w_bt = (BACKTEST_WEIGHT if weight is None else weight) * (test.get("n") or 0)
        n_fw = fwd.get("n") or 0
        ev_bt, ev_fw = _f(test.get("ev_pct")) or 0.0, _f(fwd.get("ev_pct")) or 0.0
        n_eff = w_bt + n_fw
        ev = (w_bt * ev_bt + n_fw * ev_fw) / n_eff if n_eff else None
        if ev is None:
            continue
        got = {"rule": key, "label": rule.get("label"), "ev_pct": ev, "n_eff": n_eff, "source": "RULE", "forward_n": n_fw,
               "target_mult": rule.get("target_mult", 1.0), "stop_mult": rule.get("stop_mult", 1.0)}
        if best is None or ev * n_eff / (n_eff + SHRINK_N) > best["ev_pct"] * best["n_eff"] / (best["n_eff"] + SHRINK_N):
            best = got  # several rules can match one signal: the best supported one is used
    if best:
        return best
    strat = str(row.get("strategy", "")) + "|" + str(row.get("signal", ""))
    for level, stat in (("TICKER", ((ev_table or {}).get("by_strategy_ticker") or {}).get(strat + "|" + str(row.get("ticker", "")))),
                        ("STRATEGY", ((ev_table or {}).get("by_strategy") or {}).get(strat))):
        if stat and stat.get("status") == "OK" and _f(stat.get("ev_pct")) is not None:
            return {"rule": None, "label": None, "ev_pct": _f(stat["ev_pct"]), "n_eff": stat.get("n") or 0,
                    "source": level, "forward_n": 0, "target_mult": 1.0, "stop_mult": 1.0}
    return {"rule": None, "label": None, "ev_pct": None, "n_eff": 0, "source": "NONE", "forward_n": 0,
            "target_mult": 1.0, "stop_mult": 1.0}


MARGIN_MAX_AGE_DAYS = 7


def margin_ratio(margin: dict | None, ticker, *, now: datetime):
    """(信用倍率 = purchases / sales, as-of date) from the JPX all-issue daily cache, or None.
    OWNER 2026-10-22 「全銘柄の信用残はブレインがPCで読む」. Older than 7 days: not used."""
    if not margin or margin.get("schema_version") != "100b-v10-jpx-margin-all-cache-v1":
        return None
    # audit 6327787186: refuse an incomplete cache at read time as well (same bounds as ingest)
    count, dropped = margin.get("issue_count"), margin.get("dropped_blocks")
    if type(count) is not int or type(dropped) is not int or count < 3500 or dropped > 0.01 * (count + dropped):
        return None
    try:
        as_of = datetime.strptime(str(margin.get("as_of_date")), "%Y-%m-%d").replace(tzinfo=JST)
    except ValueError:
        return None
    if not timedelta(0) <= now.astimezone(JST) - as_of <= timedelta(days=MARGIN_MAX_AGE_DAYS):
        return None
    item = (margin.get("issues") or {}).get(str(ticker or "").replace(".T", ""))
    if not item:
        return None
    md = margin["as_of_date"][5:7].lstrip("0") + "/" + margin["as_of_date"][8:10].lstrip("0")
    if not item.get("sales"):   # no sales balance: no ratio; the weekly ratio is used and this is said
        return None, md
    return item["purchases"] / item["sales"], md


def pick(live: dict, *, ev_table: dict | None, rule_shadow: dict | None, now: datetime,
         attention: dict | None = None, margin: dict | None = None) -> dict:
    """attention: code -> [{role, report_id, expires_at}] from the specialists' unexpired
    WATCH reports (OWNER 2026-10-22: specialists watch, the Brain decides). Shown as a flag
    and listed; it does not change the score until its own forward results exist."""
    local = now.astimezone(JST)
    hm = local.strftime("%H:%M")
    base = {"schema_version": SCHEMA, "generated_at": now.astimezone(timezone.utc).isoformat(), "picks": [],
            "excluded": [], "rule_signals": [], "specialist_watch": [], "considered": 0, "real_submit_allowed": False, "trade_instruction": False,
            "thresholds": {"max_picks": MAX_PICKS, "shrink_n": SHRINK_N, "backtest_weight": BACKTEST_WEIGHT,
                           "min_score_pct": MIN_SCORE_PCT, "short_min_credit_ratio": SHORT_MIN_CREDIT_RATIO,
                           "status": "PROVISIONAL"},
            "ev_table_days": len((ev_table or {}).get("days") or []), "rule_forward_from": (rule_shadow or {}).get("forward_from")}
    lit = {str(r.get("ticker", "")).replace(".T", ""): r.get("signal") for r in live.get("all_targets") or []}
    names = {str(r.get("ticker", "")).replace(".T", ""): r.get("name") for r in live.get("all_targets") or []}
    base["specialist_watch"] = [{"code": c, "name": names.get(c) or c, "roles": sorted({x["role"] for x in v}),
                                 "signal_now": lit.get(c) if lit.get(c) in SIDES else None}
                                for c, v in sorted((attention or {}).items())]
    updated = _live_time(live.get("updated_at"))
    base["live_updated_at"] = updated.isoformat() if updated else None
    valid = live.get("valid")   # the Collector's count of valid rows, an integer
    if (type(valid) is not int or not MIN_VALID_ROWS <= valid <= MAX_VALID_ROWS
            or live.get("stale") is not False or updated is None
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
        # OWNER 2026-10-26 「ルール①を記録だけにして」: a signal that only a record-only rule matches is
        # logged as that rule's signal (virtual replay and 注目 list) and never ranked, spoken or carded.
        matched = rules_for((rule_shadow or {}).get("rules"), row, hm)
        record_only = [(k, r) for k, r in matched if r.get("record_only")]
        if record_only and not [k for k, r in matched if not r.get("record_only")]:
            key, rule = record_only[0]
            dist = abs(target - entry)
            base["rule_signals"].append({"ticker": row.get("ticker"), "name": name, "signal": row.get("signal"),
                                         "strategy": row.get("strategy"), "signal_bar": row.get("signal_bar_time"),
                                         "rule": key, "entry": entry, "record_only": True,
                                         "target": round(entry + side * rule.get("target_mult", 1.0) * dist, 4),
                                         "stop": round(entry - side * rule.get("stop_mult", 1.0) * dist, 4)})
            base["excluded"].append({"ticker": row.get("ticker"), "name": name, "reason": "ルール①は記録のみ（ブレインは使わない）"})
            continue
        flags = []
        ratio = _f(row.get("credit_ratio"))
        daily = margin_ratio(margin, row.get("ticker"), now=now)
        if daily is not None and daily[0] is not None:  # the JPX daily figure replaces the weekly MS2 ratio
            ratio = daily[0]
            flags.append("信用倍率%.2f（JPX日次 %s申込み）" % (daily[0], daily[1]))
        elif daily is not None:
            flags.append("JPX日次 %s申込みは売0（倍率なし・週次の倍率を使用）" % daily[1])
        if ratio is None:
            flags.append("信用倍率不明（空売り状況 未確認）")
        elif side < 0 and ratio < SHORT_MIN_CREDIT_RATIO:
            base["excluded"].append({"ticker": row.get("ticker"), "name": name, "reason": "売り長（信用倍率%.2f）踏み上げ注意" % ratio})
            continue
        elif side > 0 and ratio >= BUY_HEAVY_CREDIT_RATIO:
            flags.append("買い長（信用倍率%.1f）戻り売り注意" % ratio)
        watched = (attention or {}).get(str(row.get("ticker", "")).replace(".T", ""))
        agents = sorted({x["role"] for x in watched or [] if x.get("role") != "grok"})
        if agents:
            flags.append("専門AIが先回り監視中（" + "・".join(a.replace("manual_", "") + ("・手動" if a.startswith("manual_") else "")
                                                        for a in agents) + "）")
        # OWNER 2026-10-23 manual Grok X topics: a flag for the Brain's overall view, never a score;
        # a view against the lit signal (弱気 on a buy, 強気 on a short) is marked as a caution.
        for x in watched or []:
            if x.get("role") == "grok":
                against = x.get("stance") == ("弱気" if side > 0 else "強気")
                flags.append("X話題（Grok・手動）：" + str(x.get("strength") or "") + "・" + str(x.get("stance")) + "「"
                             + str(x.get("summary"))[:120] + "」" + ("（サインと逆向き・注意）" if against else ""))
        if est["ev_pct"] is None:
            base["excluded"].append({"ticker": row.get("ticker"), "name": name, "reason": "根拠不足（記録20回未満）"})
            continue
        score = est["ev_pct"] * est["n_eff"] / (est["n_eff"] + SHRINK_N)
        dist = abs(target - entry)
        if est["source"] == "RULE":
            # OWNER 2026-10-22 「音声は①②④⑤だけ」: every lit signal matching a rule, for the
            # Collector's voice (whatever its score; the squeeze-risk shorts above are left out).
            base["rule_signals"].append({"ticker": row.get("ticker"), "name": name, "signal": row.get("signal"),
                                         "strategy": row.get("strategy"), "signal_bar": row.get("signal_bar_time"),
                                         "rule": est["rule"], "entry": entry,
                                         "target": round(entry + side * est["target_mult"] * dist, 4),
                                         "stop": round(entry - side * est["stop_mult"] * dist, 4)})
        scored.append({"ticker": row.get("ticker"), "name": name, "side": side, "signal": row.get("signal"),
                       "strategy": row.get("strategy"), "signal_bar": row.get("signal_bar_time"),
                       "market_state": row.get("market_state"), "entry": entry,
                       "target": round(entry + side * est["target_mult"] * dist, 4),
                       "stop": round(entry - side * est["stop_mult"] * dist, 4),
                       "signal_stop": stop, "signal_target": target, "score_pct": round(score, 4),
                       "ev_pct": round(est["ev_pct"], 4), "n_eff": round(est["n_eff"], 1), "source": est["source"],
                       "forward_n": est["forward_n"],
                       "rule": est["rule"], "rule_label": est["label"], "flags": flags})
    scored.sort(key=lambda s: -s["score_pct"])
    seen = set()
    for s in scored:
        if s["ticker"] in seen:
            continue
        seen.add(s["ticker"])
        if s["score_pct"] < MIN_SCORE_PCT or len(base["picks"]) >= MAX_PICKS:
            base["excluded"].append({"ticker": s["ticker"], "name": s["name"],
                                     "reason": ("順位スコア%+.3f%%（基準%.2f%%未満）" % (s["score_pct"], MIN_SCORE_PCT))
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


def log_new_rule_signals(records: Path, view: dict, *, now: datetime, logged: set) -> int:
    """Append each rule signal not yet logged today (same stock, strategy, side, signal bar and rule)."""
    local = now.astimezone(JST)
    path = Path(records) / local.date().isoformat() / RULE_SIGNALS_FILE
    if not logged and path.is_file():
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                logged.add((r.get("ticker"), r.get("strategy"), r.get("signal"), r.get("signal_bar"), r.get("rule")))
    new = []
    for x in view.get("rule_signals") or []:
        key = (x["ticker"], x["strategy"], x["signal"], x["signal_bar"] or "", x["rule"])
        if key in logged:
            continue
        logged.add(key)
        new.append({"captured_at": local.strftime("%Y-%m-%d %H:%M:%S"), "ticker": x["ticker"], "name": x["name"],
                    "signal": x["signal"], "strategy": x["strategy"], "signal_bar": x["signal_bar"] or "",
                    "rule": x["rule"], "entry": x["entry"], "target": x["target"], "stop": x["stop"]})
    if not new:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8-sig" if first else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RULE_SIGNAL_FIELDS)
        if first:
            w.writeheader()
        w.writerows(new)
    return len(new)


def today_lists(records: Path, *, now: datetime, rule_labels: dict | None = None) -> dict:
    """Today's 注目 list, newest first, nothing dropped: each stock's first entry into the
    Brain ranking (RANKING) and every logged rule signal (RULE)."""
    local = now.astimezone(JST)
    day_dir = Path(records) / local.date().isoformat()

    def rows(name):
        try:
            with open(day_dir / name, newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))
        except OSError:
            return []

    def label(rule):
        got = (rule_labels or {}).get(rule, {})
        return got.get("label", rule or "") + ("（記録のみ）" if got.get("record_only") else "")

    items, seen = [], set()
    for r in rows(PICKS_FILE):
        if r.get("ticker") in seen:
            continue
        seen.add(r.get("ticker"))
        items.append({"kind": "RANKING", "captured_at": r.get("captured_at"), "ticker": r.get("ticker"),
                      "name": r.get("name"), "signal": r.get("signal"), "strategy": r.get("strategy"),
                      "entry": r.get("entry"), "rule": r.get("rule") or "",
                      "label": "ブレインのランキング入り" + ("（" + label(r.get("rule")) + "）" if r.get("rule") else "")})
    for r in rows("manual_notes.csv"):   # OWNER 2026-10-23: Grok's X topics as 『X話題』
        if r.get("source") != "grok":
            continue
        items.append({"kind": "XTOPIC", "captured_at": r.get("seen_at"), "ticker": (r.get("code") or "") + ".T",
                      "name": r.get("name") or r.get("code"), "signal": r.get("view"), "strategy": "Grok（手動）",
                      "entry": "", "rule": "", "label": "X話題 " + str(r.get("strength") or "") + "・" + str(r.get("view") or "")
                      + "「" + str(r.get("reason") or "")[:60] + "」"})
    for r in rows(RULE_SIGNALS_FILE):
        items.append({"kind": "RULE", "captured_at": r.get("captured_at"), "ticker": r.get("ticker"),
                      "name": r.get("name"), "signal": r.get("signal"), "strategy": r.get("strategy"),
                      "entry": r.get("entry"), "target": r.get("target"), "stop": r.get("stop"),
                      "rule": r.get("rule"), "label": label(r.get("rule"))})
    items.sort(key=lambda x: (str(x.get("captured_at") or ""), x["kind"] == "RULE"), reverse=True)
    return {"date": local.date().isoformat(), "attention": items, "new_picks_total": len(seen),
            "rule_signals_total": sum(1 for x in items if x["kind"] == "RULE"),
            "x_topics_total": sum(1 for x in items if x["kind"] == "XTOPIC"), "status": "VERIFYING_SHADOW_ONLY"}


def _read_json(path: Path, schema: str):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("schema_version") != schema or data.get("real_submit_allowed") is not False:
        return None
    return data


def write_pick(runtime: Path, live: dict, *, now: datetime, logged: set, attention: dict | None = None,
               logged_rules: set | None = None, grok: dict | None = None, positions: dict | None = None,
               manual_analysts: dict | None = None) -> dict:
    runtime = Path(runtime)
    ev_table = _read_json(runtime / "signal_ev_table_v1.json", "100b-v10-signal-ev-table-v1")
    rule_shadow = _read_json(runtime / "rule_shadow_v1.json", "100b-v10-rule-shadow-v1")
    margin = _read_json(runtime / "jpx_margin_all_v1.json", "100b-v10-jpx-margin-all-cache-v1")
    view = pick(live, ev_table=ev_table, rule_shadow=rule_shadow, now=now, attention=attention, margin=margin)
    view["jpx_margin_as_of"] = (margin or {}).get("as_of_date")
    view["logged_new"] = log_new_picks(runtime / "records", view, now=now, logged=logged)
    view["logged_rule_new"] = log_new_rule_signals(runtime / "records", view, now=now,
                                                   logged=set() if logged_rules is None else logged_rules)
    view["today"] = today_lists(runtime / "records", now=now, rule_labels=(rule_shadow or {}).get("rules"))
    view["grok"] = grok or {"notes": [], "status": "MANUAL_WATCH_ONLY_NOT_A_SCORE"}
    view["manual_analysts"] = manual_analysts or {}   # backup only, shown as 『手動』
    # OWNER 2026-10-23: virtual holdings for the screen colours and the 08:50 / 15:30 voice
    view["positions"] = {k: (positions or {}).get(k) for k in ("generated_at", "date", "rule_positions", "overnight",
                                                               "swing", "value", "counts", "status",
                                                               "owner_rules")}   # OWNER 2026-10-27 OWNER's rules tally
    target = runtime / "brain_pick_v1.json"
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temp.replace(target)
    return view
