"""Expected value of the cockpit's own signals, from its recorded MS2 data.

Backtest only (OWNER 2026-10-21: old data is for backtesting, never for an
entry). For every buy/short signal the Collector logged in
records/<day>/trade_signals.csv, the same day's recorded MS2 ticks of that
ticker are replayed from the signal time:

- only ticks strictly after the signal bar's close (and after the logged
  signal time) are used, so a tick inside the signal's own bar never fills it;
- fill: the first such tick at or through the entry within FILL_WINDOW (buy:
  price >= entry, short: price <= entry), booked at that tick's price (a gap
  through the entry fills at the gap price); otherwise NOT_FILLED;
- exit: the first later second in which target1 or stop is touched, booked at
  the touching tick's price (a gap through the stop exits at the gap price);
  when one second touches both, the stop is taken (pessimistic, both sides);
  otherwise the last tick at or before 15:20 JST;
- while a trade from the same ticker and setup is open, later signals of that
  ticker and setup are skipped (no overlapping, correlated trades);
- return: side * (exit / fill - 1) minus the cost below.

Ticks are recorded on change, not every trade, so a touch between two ticks
can be missed; results are an estimate from this sampling. Statistics are
grouped by strategy+side and by strategy+side+ticker; a group with fewer than
MIN_N filled trades is marked INSUFFICIENT and must not be ranked.
No order path; nothing here is a trade instruction.
"""
from __future__ import annotations

import argparse
import bisect
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys

SCHEMA = "100b-v10-signal-ev-table-v1"
JST = timezone(timedelta(hours=9))
FILL_WINDOW = timedelta(minutes=30)       # PROVISIONAL
EXIT_TIME = "15:20:00"
# Costs (OWNER 2026-10-21: 楽天証券ゼロコース, 制度信用, mainly day trading).
# Rates from https://www.rakuten-sec.co.jp/web/domestic/margin/commission.html
# (checked 2026-10-21): commission 0; 制度信用 buyer interest 2.80 %/year;
# stock lending fee (short) 1.10 %/year. Whether a same-day round trip is
# charged one day is not stated there: one day is assumed (conservative).
COMMISSION_PCT_PER_SIDE = 0.0
LONG_INTEREST_PCT_PER_YEAR = 2.80
SHORT_LENDING_FEE_PCT_PER_YEAR = 1.10
FINANCING_DAYS_PER_DAY_TRADE = 1          # UNVERIFIED (one day assumed)
SLIPPAGE_PCT_PER_SIDE = 0.0               # PROVISIONAL: shown as the break-even value instead
MIN_N = 20
SIDES = {"買いサイン": 1, "空売りサイン": -1}


def _f(raw):
    try:
        v = float(str(raw).replace(",", ""))
    except ValueError:
        return None
    return v if math.isfinite(v) and v > 0 else None


def load_ticks(path: Path) -> dict:
    """Per ticker: (exchange_time, file order, price), stably ordered by time."""
    out = {}
    if not path.is_file():
        return out
    with open(path, newline="", encoding="utf-8-sig") as f:
        for seq, r in enumerate(csv.DictReader(f)):
            price = _f(r.get("price"))
            t = (r.get("exchange_time") or "").strip()
            if price is None or len(t) != 8:
                continue
            out.setdefault(r.get("ticker", ""), []).append((t, seq, price))
    for rows in out.values():
        rows.sort(key=lambda x: (x[0], x[1]))
    return out


def _not_before(signal: dict, at: datetime) -> str:
    """First usable tick time: after the logged signal second and after the bar's close."""
    first = (at + timedelta(seconds=1)).strftime("%H:%M:%S")
    try:
        bar = datetime.strptime(str(signal.get("signal_bar", "")).strip(), "%Y-%m-%d %H:%M")
        first = max(first, (bar + timedelta(minutes=1)).strftime("%H:%M:%S"))
    except ValueError:
        pass
    return first


def replay(signal: dict, ticks: list, *, target_mult: float = 1.0, stop_mult: float = 1.0,
           max_hold_minutes: int | None = None) -> dict | None:
    """Default: the signal's own target1/stop. A rule can widen both as multiples of
    the signal's entry-to-target distance and cap the holding time."""
    side = SIDES.get(signal.get("signal"))
    entry, stop, target = _f(signal.get("entry")), _f(signal.get("stop")), _f(signal.get("target1"))
    if (target_mult, stop_mult) != (1.0, 1.0) and None not in (side, entry, target):
        base = abs(target - entry)
        target, stop = entry + side * target_mult * base, entry - side * stop_mult * base
    try:
        at = datetime.strptime(signal["captured_at"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        return None
    if side is None or None in (entry, stop, target):
        return None
    if (side > 0 and not stop < entry < target) or (side < 0 and not target < entry < stop):
        return None
    start = _not_before(signal, at)
    fill_until = (at + FILL_WINDOW).strftime("%H:%M:%S")
    later = [x for x in ticks if x[0] >= start]
    fill_i = None
    for i, (t, _, p) in enumerate(later):
        if t > fill_until or t > EXIT_TIME:
            break
        if (side > 0 and p >= entry) or (side < 0 and p <= entry):
            fill_i = i
            break
    if fill_i is None:
        return {"state": "NOT_FILLED", "start": start}
    fill_t, fill = later[fill_i][0], later[fill_i][2]
    exit_limit = EXIT_TIME
    if max_hold_minutes:
        exit_limit = min(EXIT_TIME, (datetime.strptime(fill_t, "%H:%M:%S") + timedelta(minutes=max_hold_minutes)).strftime("%H:%M:%S"))
    rest = [x for x in later[fill_i + 1:] if x[0] <= exit_limit]
    by_second = {}
    for t, _, p in rest:
        by_second.setdefault(t, []).append(p)
    for t in sorted(by_second):
        prices = by_second[t]
        stops = [p for p in prices if (side > 0 and p <= stop) or (side < 0 and p >= stop)]
        targets = [p for p in prices if (side > 0 and p >= target) or (side < 0 and p <= target)]
        if stops:  # a second touching both is resolved to the stop
            return _result(side, fill, stops[0], "STOP", fill_t, t)
        if targets:
            return _result(side, fill, targets[0], "TARGET", fill_t, t)
    last_t, last = (rest[-1][0], rest[-1][2]) if rest else (fill_t, fill)
    return _result(side, fill, last, "TIME_EXIT", fill_t, last_t)


def cost_pct(side: int) -> float:
    """Round-trip cost of one day trade in %, before slippage is added."""
    rate = LONG_INTEREST_PCT_PER_YEAR if side > 0 else SHORT_LENDING_FEE_PCT_PER_YEAR
    return 2 * (COMMISSION_PCT_PER_SIDE + SLIPPAGE_PCT_PER_SIDE) + rate / 365 * FINANCING_DAYS_PER_DAY_TRADE


def _result(side, fill, exit_price, how, fill_t, exit_t):
    gross = side * (exit_price / fill - 1) * 100
    return {"state": "FILLED", "exit": how, "side": side, "fill_price": fill, "exit_price": exit_price,
            "fill_time": fill_t, "exit_time": exit_t, "gross_pct": gross, "return_pct": gross - cost_pct(side)}


def stats(trades: list[dict]) -> dict:
    """Net of the provisional cost (ev_pct, win_rate_pct, pf) and gross (before cost)."""
    returns = [t["return_pct"] for t in trades]
    n = len(returns)
    if not n:
        return {"n": 0, "status": "INSUFFICIENT"}
    gross = [t["gross_pct"] for t in trades]
    exits = {}
    for t in trades:
        exits[t["exit"]] = exits.get(t["exit"], 0) + 1
    wins = [r for r in returns if r > 0]
    loss = -sum(r for r in returns if r < 0)
    return {
        "n": n, "win_rate_pct": round(len(wins) / n * 100, 1),
        "ev_pct": round(sum(returns) / n, 3),
        "pf": round(sum(wins) / loss, 2) if loss > 0 else None,
        "gross_ev_pct": round(sum(gross) / n, 3),
        # the slippage per side at which this group's average net return is zero
        "breakeven_slippage_pct_per_side": round((sum(returns) / n) / 2 + SLIPPAGE_PCT_PER_SIDE, 4),
        "gross_win_rate_pct": round(sum(1 for g in gross if g > 0) / n * 100, 1),
        "exits": exits,
        "status": "OK" if n >= MIN_N else "INSUFFICIENT",
    }


def build(records: Path, *, now: datetime, days: list[str] | None = None) -> dict:
    by_strategy, by_ticker, used_days = {}, {}, []
    counts = {"signals": 0, "filled": 0, "not_filled": 0, "invalid": 0, "overlapping_skipped": 0}
    local = now.astimezone(JST)
    today = local.date().isoformat()
    today_complete = local.strftime("%H:%M") >= "15:30"
    for day_dir in sorted(p for p in records.iterdir() if p.is_dir()):
        day = day_dir.name
        # completed sessions only: past days, and today once the 15:30 close has passed
        if (days and day not in days) or day > today or (day == today and not today_complete):
            continue
        sig_path = day_dir / "trade_signals.csv"
        if not sig_path.is_file():
            continue
        ticks = load_ticks(day_dir / "ticks.csv")
        if not ticks:
            continue
        used_days.append(day)
        open_until = {}
        with open(sig_path, newline="", encoding="utf-8-sig") as f:
            for s in csv.DictReader(f):
                counts["signals"] += 1
                setup = (s.get("ticker", ""), s.get("strategy", ""), s.get("signal", ""))
                stamp = str(s.get("captured_at", ""))[11:19]
                if setup in open_until and stamp <= open_until[setup]:
                    counts["overlapping_skipped"] += 1
                    continue
                got = replay(s, ticks.get(s.get("ticker", ""), []))
                if got is None:
                    counts["invalid"] += 1
                    continue
                if got["state"] != "FILLED":
                    counts["not_filled"] += 1
                    continue
                counts["filled"] += 1
                open_until[setup] = got["exit_time"]
                key = s["strategy"] + "|" + s["signal"]
                by_strategy.setdefault(key, []).append(got)
                by_ticker.setdefault(key + "|" + s["ticker"], []).append(got)
    return {
        "schema_version": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "basis": "BACKTEST_OF_RECORDED_COCKPIT_SIGNALS_ON_RECORDED_MS2_TICKS",
        "days": used_days,
        "assumptions": {"fill_window_minutes": FILL_WINDOW.total_seconds() / 60, "exit_time_jst": EXIT_TIME,
                        "fill_and_exit_price": "touching tick price (gaps included); same-second target+stop = stop",
                        "ticks_used": "strictly after the signal bar close; overlapping trades of one setup skipped",
                        "commission_pct_per_side": COMMISSION_PCT_PER_SIDE,
                        "long_interest_pct_per_year": LONG_INTEREST_PCT_PER_YEAR,
                        "short_lending_fee_pct_per_year": SHORT_LENDING_FEE_PCT_PER_YEAR,
                        "financing_days_per_day_trade": FINANCING_DAYS_PER_DAY_TRADE,
                        "slippage_pct_per_side": SLIPPAGE_PCT_PER_SIDE, "min_n": MIN_N,
                        "status": "楽天証券ゼロコース・制度信用 (OWNER 2026-10-21; rates checked 2026-10-21); "
                                  "1 financing day per day trade UNVERIFIED; slippage 0 PROVISIONAL (break-even shown); "
                                  "fill window PROVISIONAL"},
        "counts": counts,
        "by_strategy": {k: stats(v) for k, v in sorted(by_strategy.items())},
        "by_strategy_ticker": {k: stats(v) for k, v in sorted(by_ticker.items())},
        "real_submit_allowed": False,
        "trade_instruction": False,
    }


# OWNER 2026-10-21 「①②でSHADOW開始」: rules chosen on 2026-09-24..10-21 records
# (first 14 days chosen, last 7 days checked). Forward results count only days from
# RULES_FORWARD_FROM, i.e. after the rules were fixed. Virtual only; no orders.
RULES_SCHEMA = "100b-v10-rule-shadow-v1"
# Recomputed by build_rule_shadow's own replay (reference-price gaps, split-sized gaps
# skipped) on 2026-09-19..10-21; test = the last third of the days (from 2026-10-14).
R4_BACKTEST = {"train": {"n": 188, "ev_pct": 0.111, "pf": 1.63}, "test": {"n": 93, "ev_pct": 0.103, "pf": 1.54}}
R5_BACKTEST = {"train": {"n": 24, "ev_pct": 0.15, "pf": 1.75}, "test": {"n": 44, "ev_pct": 0.387, "pf": 4.19}}
RULES_FORWARD_FROM = "2026-10-22"
RULES = {
    "R1": {"label": "① 買い 9:15〜10:00・目標2倍・損切り2倍", "side": 1, "from": "09:15", "to": "10:00",
           "market": None, "target_mult": 2.0, "stop_mult": 2.0, "max_hold_minutes": None,
           "selection": "TRAIN_THEN_TEST", "backtest_weight": 0.5,
           "backtest": {"train": {"n": 102, "ev_pct": 0.097, "pf": 1.39}, "test": {"n": 54, "ev_pct": 0.096, "pf": 1.51}}},
    # OWNER 2026-10-22: 地合い弱い = at most 40 % of the watched issues above their reference
    # price (基準値) at the signal time, not the Collector's above-VWAP breadth.
    "R2": {"label": "② 売り 地合い弱い日（基準値より値上がりの銘柄が40%以下） 9:15〜10:00・目標3倍・損切り2倍・最長60分",
           "side": -1, "from": "09:15",
           "to": "10:00", "market": None, "advance_max_pct": 40.0, "target_mult": 3.0, "stop_mult": 2.0, "max_hold_minutes": 60,
           "selection": "TRAIN_THEN_TEST", "backtest_weight": 0.5,
           # Recomputed 2026-10-22 for the 基準値 definition by this module's replay on the
           # 2026-09-24..10-21 records (train = first 14 days, test = the last 6).
           "backtest": {"train": {"n": 25, "ev_pct": 0.096, "pf": 1.51}, "test": {"n": 56, "ev_pct": 0.211, "pf": 1.94}}},
    # OWNER 2026-10-22 「④⑤もSHADOW追加」: round-2 search on 2026-09-19..10-21 records,
    # kept only because each of three equal day blocks was positive (train = first two).
    # All three blocks chose them, so no block is out of sample: the Brain gives their
    # backtest a small weight (PROVISIONAL) until forward trades accumulate. Only the
    # strategy the search saw (押し目 for buys, 戻り for shorts) matches.
    "R4": {"label": "④ 買い 寄りから+0.5%以上上げている銘柄の押し目・目標2倍・損切り2倍", "side": 1, "from": "09:00",
           "to": "15:20", "market": None, "target_mult": 2.0, "stop_mult": 2.0, "max_hold_minutes": None,
           "strategy": "OR15押し目", "min_move_pct": 0.5, "selection": "IN_SAMPLE_ALL_BLOCKS", "backtest_weight": 0.1,
           "backtest": R4_BACKTEST},
    "R5": {"label": "⑤ 売り 窓を1%以上下に開けた日の戻り売り・目標3倍・損切り2倍・最長60分", "side": -1, "from": "09:00",
           "to": "15:20", "market": None, "target_mult": 3.0, "stop_mult": 2.0, "max_hold_minutes": 60,
           "strategy": "OR15戻り", "gap": "down", "selection": "IN_SAMPLE_ALL_BLOCKS", "backtest_weight": 0.1,
           "backtest": R5_BACKTEST},
}


# OWNER 2026-10-21 「③」: record only, both directions. Every watched issue that opens
# >= 1 % away from the previous close: R3A follows the gap from the first tick at or
# after 09:00 to the last tick by 10:00; R3B fades it. (21 recorded days favoured
# following; 3 years of 60-minute bars favoured fading: no stable edge yet.)
# OWNER 2026-10-21 「9時15分と9時30に決済も検証」: three exit times for each direction.
GAP_RULES = {
    f"R3{d}_{hm.replace(':', '')}": {"label": f"③{d} 窓{'の方向' if sign > 0 else 'と反対'}に寄りで入り{hm}決済（記録のみ）",
                                      "direction": sign, "min_gap_pct": 1.0, "exit": hm + ":00"}
    for d, sign in (("A", 1), ("B", -1)) for hm in ("09:15", "09:30", "10:00")
}


# The recorded ticks stop before the 15:30 closing auction, so the last tick is not the
# official close: the previous close is the exchange reference price (基準値, already
# adjusted for splits) from that morning's preopen.csv when it was recorded. A gap this
# large is a corporate action (split) rather than a market gap and is skipped.
MAX_GAP_PCT = 20.0


def load_reference_prices(path: Path) -> dict:
    """Last reference price per issue logged before 09:00 in preopen.csv ({} if none)."""
    out = {}
    if not path.is_file():
        return out
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            price = _f(r.get("reference_price"))
            if price and price > 0 and str(r.get("captured_at", ""))[11:19] < "09:00:00":
                out[r.get("ticker", "")] = price
    return out


def gap_trades(prev_ticks: dict, ticks: dict, rule: dict, reference: dict | None = None) -> list[dict]:
    out = []
    for ticker, rows in ticks.items():
        before = [p for t, _, p in prev_ticks.get(ticker, []) if t <= "15:30:00"]
        day = [(t, p) for t, _, p in rows if t >= "09:00:00"]
        close = (reference or {}).get(ticker) or (before[-1] if before else None)
        if not close or not day:
            continue
        open_t, open_ = day[0]
        gap = (open_ / close - 1) * 100
        if abs(gap) < rule["min_gap_pct"] or abs(gap) >= MAX_GAP_PCT:
            continue
        side = rule["direction"] * (1 if gap > 0 else -1)
        upto = [(t, p) for t, p in day if t <= rule["exit"]]
        if not upto:  # no trade before the exit time: not entered
            continue
        exit_t, exit_p = upto[-1]
        gross = side * (exit_p / open_ - 1) * 100
        out.append({"state": "FILLED", "exit": "TIME_EXIT", "side": side, "fill_price": open_, "exit_price": exit_p,
                    "fill_time": open_t, "exit_time": exit_t, "gap_pct": round(gap, 3), "gross_pct": gross,
                    "return_pct": gross - cost_pct(side), "ticker": ticker, "name": "", "signal_at": open_t})
    return out


# R2's breadth needs at least this many issues with a reference price and a trade.
MIN_BREADTH_ISSUES = 20


def advance_pct_at(context: dict | None, at: str) -> float | None:
    """Share in % of the issues whose last trade at or before `at` (from 09:00) is above
    the reference price (基準値). None with fewer than MIN_BREADTH_ISSUES issues."""
    up = n = 0
    for ticker, (times, prices) in ((context or {}).get("series") or {}).items():
        ref = ((context or {}).get("ref") or {}).get(ticker)
        i = bisect.bisect_right(times, at) - 1
        if not ref or i < 0 or times[i] < "09:00:00":
            continue
        n += 1
        up += prices[i] > ref
    return up * 100.0 / n if n >= MIN_BREADTH_ISSUES else None


def day_context(prev_ticks: dict | None, ticks: dict, reference: dict | None = None) -> dict:
    """Each issue's open (first tick at or after 09:00) and opening gap in % against the
    reference price, else the previous day's last tick (None when unknown or split-sized)."""
    opens, open_times, gaps, refs, series = {}, {}, {}, {}, {}
    for ticker, rows in ticks.items():
        day = [p for t, _, p in rows if t >= "09:00:00"]
        if not day:
            continue
        opens[ticker] = day[0]
        open_times[ticker] = next(t for t, _, _ in rows if t >= "09:00:00")
        before = [p for t, _, p in (prev_ticks or {}).get(ticker, []) if t <= "15:30:00"]
        close = (reference or {}).get(ticker) or (before[-1] if before else None)
        if close:
            gap = (day[0] / close - 1) * 100
            gaps[ticker] = gap if abs(gap) < MAX_GAP_PCT else None
            if abs(gap) < MAX_GAP_PCT:
                refs[ticker] = close
        series[ticker] = ([t for t, _, _ in rows], [p for _, _, p in rows])
    return {"open": opens, "open_time": open_times, "gap": gaps, "ref": refs, "series": series}


def context_matches(rule: dict, side: int, ticker: str, entry, context: dict | None, at: str = "") -> bool:
    """The R4 move-from-open and R5 gap-down conditions (True for rules without them).
    The open must already have traded at the signal time (no look-ahead)."""
    if rule.get("min_move_pct") is not None or rule.get("gap"):
        open_t = ((context or {}).get("open_time") or {}).get(ticker)
        if not open_t or not at or open_t > at:
            return False
    if rule.get("min_move_pct") is not None:
        open_ = ((context or {}).get("open") or {}).get(ticker)
        if not open_ or entry is None or side * (entry / open_ - 1) * 100 < rule["min_move_pct"]:
            return False
    if rule.get("gap") == "down":
        gap = ((context or {}).get("gap") or {}).get(ticker)
        if gap is None or gap > -1.0:
            return False
    if rule.get("advance_max_pct") is not None:
        breadth = advance_pct_at(context, at) if at else None
        if breadth is None or breadth > rule["advance_max_pct"]:
            return False
    return True


def rule_matches(rule: dict, signal: dict, context: dict | None = None) -> bool:
    side = SIDES.get(signal.get("signal"))
    hm = str(signal.get("captured_at", ""))[11:16]
    return (side == rule["side"] and rule["from"] <= hm < rule["to"]
            and (rule["market"] is None or rule["market"] in str(signal.get("market_state", "")))
            and (not rule.get("strategy") or rule["strategy"] == signal.get("strategy"))
            and context_matches(rule, side, signal.get("ticker", ""), _f(signal.get("entry")), context,
                                str(signal.get("captured_at", ""))[11:19]))


def brain_trades(picks_path: Path, ticks: dict) -> list[dict]:
    """Replay the Brain core's own picks (records/<day>/brain_picks.csv), each with the
    target/stop of the rule it was picked under, skipping picks made while an earlier
    pick of the same setup was still open."""
    with open(picks_path, newline="", encoding="utf-8-sig") as f:
        picks = list(csv.DictReader(f))
    out, open_until = [], {}
    for s in picks:
        rule = RULES.get(s.get("rule") or "") or {}
        setup = (s.get("ticker", ""), s.get("strategy", ""), s.get("signal", ""))
        stamp = str(s.get("captured_at", ""))[11:19]
        if setup in open_until and stamp <= open_until[setup]:
            continue
        got = replay(s, ticks.get(s.get("ticker", ""), []), target_mult=rule.get("target_mult", 1.0),
                     stop_mult=rule.get("stop_mult", 1.0), max_hold_minutes=rule.get("max_hold_minutes"))
        if not got or got.get("state") != "FILLED":
            continue
        open_until[setup] = got["exit_time"]
        out.append(dict(got, ticker=s.get("ticker", ""), name=s.get("name", ""), signal_at=s.get("captured_at", "")))
    return out


def build_rule_shadow(records: Path, *, now: datetime) -> dict:
    """Virtual trades of each rule on completed days from RULES_FORWARD_FROM."""
    local = now.astimezone(JST)
    today, complete = local.date().isoformat(), local.strftime("%H:%M") >= "15:30"
    trades = {k: [] for k in list(RULES) + list(GAP_RULES) + ["BRAIN"]}
    days = []
    prev_ticks = None
    for day_dir in sorted(p for p in records.iterdir() if p.is_dir()):
        day = day_dir.name
        if day > today or (day == today and not complete):
            continue
        ticks = load_ticks(day_dir / "ticks.csv")
        if not ticks:
            continue
        if day < RULES_FORWARD_FROM:
            prev_ticks = ticks
            continue
        reference = load_reference_prices(day_dir / "preopen.csv")
        context = day_context(prev_ticks, ticks, reference)
        if prev_ticks is not None:
            for key, rule in GAP_RULES.items():
                trades[key].extend(dict(t, day=day) for t in gap_trades(prev_ticks, ticks, rule, reference))
        prev_ticks = ticks
        if (day_dir / "brain_picks.csv").is_file():
            trades["BRAIN"].extend(dict(t, day=day) for t in brain_trades(day_dir / "brain_picks.csv", ticks))
        sig_path = day_dir / "trade_signals.csv"
        if not sig_path.is_file():
            continue
        days.append(day)
        with open(sig_path, newline="", encoding="utf-8-sig") as f:
            signals = list(csv.DictReader(f))
        for key, rule in RULES.items():
            open_until = {}
            for s in signals:
                if not rule_matches(rule, s, context):
                    continue
                setup = (s.get("ticker", ""), s.get("strategy", ""), s.get("signal", ""))
                stamp = str(s.get("captured_at", ""))[11:19]
                if setup in open_until and stamp <= open_until[setup]:
                    continue
                got = replay(s, ticks.get(s.get("ticker", ""), []), target_mult=rule["target_mult"],
                             stop_mult=rule["stop_mult"], max_hold_minutes=rule["max_hold_minutes"])
                if not got or got.get("state") != "FILLED":
                    continue
                open_until[setup] = got["exit_time"]
                trades[key].append(dict(got, day=day, ticker=s.get("ticker", ""), name=s.get("name", ""),
                                        signal_at=s.get("captured_at", "")))
    return {
        "schema_version": RULES_SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "forward_from": RULES_FORWARD_FROM, "days": days,
        "rules": {k: {k2: v for k2, v in r.items()} for k, r in RULES.items()},
        "gap_rules": GAP_RULES,
        "brain": {"label": "ブレインの選択（上位3銘柄）"},
        "forward": {k: dict(stats(v), recent=[{x: t[x] for x in ("day", "ticker", "name", "signal_at", "exit",
                                                               "fill_price", "exit_price", "return_pct")}
                                              for t in v[-10:]]) for k, v in trades.items()},
        "basis": "VIRTUAL_REPLAY_OF_RECORDED_SIGNALS_ON_RECORDED_MS2_TICKS",
        "real_submit_allowed": False, "trade_instruction": False,
    }


def write_table(records: Path, target: Path, *, now: datetime) -> dict:
    table = build(records, now=now)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(table, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temp.replace(target)
    shadow = build_rule_shadow(records, now=now)
    rule_target = target.with_name("rule_shadow_v1.json")
    temp = rule_target.with_name(rule_target.name + ".tmp")
    temp.write_text(json.dumps(shadow, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temp.replace(rule_target)
    table["rule_shadow_days"] = len(shadow["days"])
    return table


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backtest expected value of recorded cockpit signals")
    ap.add_argument("--records", required=True, type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    table = write_table(args.records, args.output, now=now) if args.output else build(args.records, now=now)
    print(json.dumps({"days": len(table["days"]), "counts": table["counts"], "by_strategy": table["by_strategy"]},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
