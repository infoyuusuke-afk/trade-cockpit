"""Zero-token Strategy Lab v1: offline, bounded, point-in-time research only.

Strategy exploration is statistical/algorithmic, NOT cloud-LLM inference.
This module imports no broker, network, market-data client or paid API.
No real or Shadow order is generated or authorized. All profitability remains
unverified until actual future, independently captured Shadow results.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, time, timezone
from collections import defaultdict
from hashlib import sha256
from itertools import product
import io
import json
import math
from pathlib import Path
import random
import re
from statistics import mean

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "zero_token_strategy_lab_v1"
BAR_SECONDS = 15
BAR_COLS = ("symbol", "time", "available_at", "open", "high", "low",
            "close", "volume", "source", "quality")
SYMBOL_RE = re.compile(r"^(?:[0-9]{4}|[0-9]{3}[A-Z])(?:\.T)?$")
ALLOWED_SOURCES = frozenset({"MS2_RSS_15S_CONFIRMED", "SYNTHETIC_TEST_ONLY"})
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_BARS = 400_000
MIN_ROUND_TRIP_COST_BPS = 10.0
HOLDOUT_TRADE_MIN = 30
CANDIDATE_TRADE_MIN = 20
BOOTSTRAP_SAMPLES = 1200
ALPHA = 0.05


class ResearchBlocked(ValueError):
    """No silent repair, no fabricated market returns, no brokerage action."""


def _aware(value: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 40:
        raise ResearchBlocked("TIMESTAMP_INVALID")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchBlocked("TIMESTAMP_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ResearchBlocked("TIMESTAMP_NAIVE")
    return d.astimezone(JST)


def _number(value: str, *, allow_zero=False) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchBlocked("NUMERIC_INVALID") from exc
    if not math.isfinite(v) or (v < 0 if allow_zero else v <= 0):
        raise ResearchBlocked("NUMERIC_INVALID")
    return v


def _session_ok(d: datetime) -> bool:
    t = d.timetz().replace(tzinfo=None)
    return (time(9, 0) < t <= time(11, 30)
            or time(12, 30) < t <= time(15, 30))


def _read_csv(raw: bytes) -> list[dict]:
    """UTC-aware availability, 15-sec *completed-end* bars. Fail whole file."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise ResearchBlocked("SOURCE_SIZE_INVALID")
    try:
        text = raw.decode("utf-8-sig")
        f = io.StringIO(text, newline="")
        reader = csv.DictReader(f, strict=True)
        if not reader.fieldnames or tuple(reader.fieldnames) != BAR_COLS:
            raise ResearchBlocked("BAR_HEADER_MISMATCH")
        bars = []
        seen = set()
        for row in reader:
            if len(bars) >= MAX_BARS:
                raise ResearchBlocked("TOO_MANY_BARS")
            if None in row or any(x is None for x in row.values()):
                raise ResearchBlocked("BAR_FORMAT_INVALID")
            symbol = row["symbol"]
            if not SYMBOL_RE.fullmatch(symbol):
                raise ResearchBlocked("SYMBOL_INVALID")
            # Codes "285A" and "285A.T" must not be separate universes.
            symbol = symbol.removesuffix(".T")
            at = _aware(row["time"])
            available = _aware(row["available_at"])
            if (at.weekday() >= 5 or not _session_ok(at)
                    or (at.second % BAR_SECONDS) != 0 or at.microsecond != 0):
                raise ResearchBlocked("BAR_SESSION_OR_GRANULARITY_INVALID")
            if available < at or available > at + timedelta(seconds=120):
                raise ResearchBlocked("BAR_AVAILABLE_AT_INVALID")
            if row["source"] not in ALLOWED_SOURCES or row["quality"] != "CONFIRMED":
                raise ResearchBlocked("SOURCE_OR_QUALITY_NOT_CONFIRMED")
            op, hi, lo, cl = (_number(row[k]) for k in ("open", "high", "low", "close"))
            vol = _number(row["volume"], allow_zero=True)
            if not (lo <= min(op, cl) <= max(op, cl) <= hi):
                raise ResearchBlocked("OHLC_CONTRADICTION")
            key = (symbol, at)
            if key in seen:
                raise ResearchBlocked("DUPLICATE_SYMBOL_TIME")
            seen.add(key)
            bars.append({"symbol": symbol, "time": at, "available_at": available,
                         "open": op, "high": hi, "low": lo, "close": cl,
                         "volume": vol, "date": at.date().isoformat(),
                         "source": row["source"]})
        return bars
    except UnicodeError as exc:
        raise ResearchBlocked("CSV_UTF8_INVALID") from exc
    except csv.Error as exc:
        raise ResearchBlocked("CSV_PARSE_INVALID") from exc


def load_bars_bytes(raw: bytes) -> tuple[list[dict], str]:
    bars = _read_csv(raw)
    if not bars:
        raise ResearchBlocked("NO_BARS")
    sources = {r["source"] for r in bars}
    if len(sources) != 1:
        raise ResearchBlocked("MIXED_SYNTHETIC_REAL_INPUT")
    ordered = sorted(bars, key=lambda r: (r["symbol"], r["time"]))
    # Comparing canonical sorted data instead of input row order prevents
    # accidental mutation of trade ordering between two equivalent files.
    fingerprint = sha256(raw).hexdigest()
    return ordered, fingerprint


def variants() -> list[dict]:
    """Deterministic fixed hypothesis budget, no unbounded parameter mining."""
    result = []
    for opening, side, setup, stop, reward, hold in product(
        (20, 60), ("LONG", "SHORT"), ("BREAK", "VWAP"),
        (30, 50), (1.5, 2.0), (40, 80),
    ):
        result.append({
            "id": f"OR{opening//4}_{side}_{setup}_S{stop}_R{reward:g}_H{hold}",
            "or_bars": opening, "side": side, "setup": setup,
            "stop_bps": stop, "reward_r": reward, "hold_bars": hold,
        })
    # 2*2*2*2*2*2 = 64 total fixed hypotheses.
    assert len(result) == 64
    return result


def _is_complete_opening(bars: list[dict], required: int) -> bool:
    if len(bars) < required + 3:
        return False
    start = bars[0]["time"]
    if start.timetz().replace(tzinfo=None) != time(9, 0, 15):
        return False
    for index in range(1, required):
        if bars[index]["time"] - bars[index-1]["time"] != timedelta(seconds=15):
            return False
    return True


def _signed_return_bps(side, entry, exit):
    return (exit-entry) / entry * 10_000 * (1 if side == "LONG" else -1)


def _simulate(bars, signal_i, v, cost_bps):
    """Signal on confirmed close; allow one 15s bar for feed/decision latency.

    Fill is at the OPEN of the *second* bar after the signal, but only if
    the source observation was known by that open. The immediate next
    15s bar is a mandatory causality buffer, not a synthetic fill.
    Entry bar high/low can hit either stop or target. If both, stop wins.
    Any missing 15s bar prevents using a fictional fill and blocks trade.
    All exits are inside the same session; never assumes a close on
    an unfinished/truncated price series.
    """
    if signal_i + 2 >= len(bars):
        return None
    signal = bars[signal_i]
    observation_buffer = bars[signal_i + 1]
    entry_bar = bars[signal_i + 2]
    if (signal["available_at"] > observation_buffer["time"]
            or observation_buffer["time"]-signal["time"] != timedelta(seconds=15)
            or entry_bar["time"]-observation_buffer["time"] != timedelta(seconds=15)):
        return None
    entry = entry_bar["open"]
    sign = 1 if v["side"] == "LONG" else -1
    stop = entry * (1 - sign * v["stop_bps"] / 10_000)
    target = entry * (1 + sign * v["stop_bps"] * v["reward_r"] / 10_000)
    max_exit = signal_i + v["hold_bars"]
    if max_exit >= len(bars):
        return None
    entry_clock = observation_buffer["time"]
    if entry_clock.timetz().replace(tzinfo=None) >= time(11, 30):
        return None
    for j in range(signal_i+2, max_exit+1):
        x = bars[j]
        if (j > signal_i+2
                and x["time"] - bars[j-1]["time"] != timedelta(seconds=15)):
            return None
        if x["time"].date() != entry_clock.date():
            return None
        # A stop-gap receives the worse entry-bar OPEN rather than
        # magically filling at stop; target gaps use target conservatively.
        if v["side"] == "LONG":
            stop_hit = x["low"] <= stop
            target_hit = x["high"] >= target
            stop_exit = min(x["open"], stop)
        else:
            stop_hit = x["high"] >= stop
            target_hit = x["low"] <= target
            stop_exit = max(x["open"], stop)
        if stop_hit:
            exit_px = stop_exit
            reason = "STOP_FIRST_IF_AMBIGUOUS" if target_hit else "STOP"
        elif target_hit:
            exit_px = target
            reason = "TARGET"
        elif j == max_exit:
            exit_px = x["close"]
            reason = "TIME"
        else:
            continue
        gross = _signed_return_bps(v["side"], entry, exit_px)
        net = gross-cost_bps
        return {
            "strategy_id": v["id"], "date": signal["date"],
            "symbol": signal["symbol"], "side": v["side"],
            "decision_at": signal["time"].isoformat(),
            "entry_bar_end": entry_bar["time"].isoformat(),
            "exit_bar_end": x["time"].isoformat(),
            "gross_bps": round(gross, 5),
            "cost_bps": cost_bps, "net_bps": round(net, 5),
            "exit_reason": reason,
            "source": signal["source"],
            "real_submit_allowed": False,
        }
    return None


def replay_one_day(bars: list[dict], v: dict, *, cost_bps: float):
    """At most one trade per symbol-day. Only observed, completed input."""
    if not _is_complete_opening(bars, v["or_bars"]):
        return None
    hi = max(x["high"] for x in bars[:v["or_bars"]])
    lo = min(x["low"] for x in bars[:v["or_bars"]])
    mid = (hi+lo)/2.0
    accum_value=accum_vol=0.0
    vwaps=[]
    for x in bars:
        accum_value += (x["high"]+x["low"]+x["close"])/3*x["volume"]
        accum_vol += x["volume"]
        vwaps.append(accum_value/accum_vol if accum_vol else None)
    # A VWAP crossover requires *every* earlier bar used by the previous
    # VWAP to have been observable at the preceding bar's close. The
    # signal bar itself may arrive late, but must be known before the
    # second-next-bar open. Older missing bars invalidate all later VWAP.
    known_by=[]
    latest=bars[0]["available_at"]
    for x in bars:
        latest=max(latest,x["available_at"])
        known_by.append(latest)
    for i in range(v["or_bars"], len(bars)-2):
        current, prev = bars[i], bars[i-1]
        if current["time"].timetz().replace(tzinfo=None) > time(10, 30):
            break
        if current["time"]-prev["time"] != timedelta(seconds=15):
            break  # No interpolation across an earlier data gap
        if (known_by[i-1] > prev["time"]
                or known_by[i] > bars[i+1]["time"]
                or vwaps[i] is None or vwaps[i-1] is None):
            continue
        if v["side"] == "LONG":
            breakout = prev["close"] <= hi and current["close"] > hi and current["close"] > vwaps[i]
            vwap_cross = prev["close"] <= vwaps[i-1] and current["close"] > vwaps[i] and current["close"] > mid
        else:
            breakout = prev["close"] >= lo and current["close"] < lo and current["close"] < vwaps[i]
            vwap_cross = prev["close"] >= vwaps[i-1] and current["close"] < vwaps[i] and current["close"] < mid
        signal = breakout if v["setup"] == "BREAK" else vwap_cross
        if signal:
            return _simulate(bars, i, v, cost_bps)
    return None


def _metric(trades: list[dict], *, cost_override=None) -> dict:
    values = [t["gross_bps"]-(t["cost_bps"] if cost_override is None else cost_override) for t in trades]
    n=len(values)
    if not n:
        return {"trades":0,"distinct_days":0,"mean_net_bps":None,"profit_factor":None,
                "win_rate":None,"max_drawdown_bps":None}
    equity=peak=dd=0.0
    for r in values:
        equity += r
        peak=max(peak,equity)
        dd=max(dd,peak-equity)
    gains=sum(max(0,x) for x in values)
    losses=-sum(min(0,x) for x in values)
    return {
        "trades":n, "distinct_days":len({t["date"] for t in trades}),
        "mean_net_bps":round(mean(values),5),
        "profit_factor":round(gains/losses,5) if losses>0 else None,
        "win_rate":round(sum(x>0 for x in values)/n,5),
        "max_drawdown_bps":round(dd,5),
    }


def _day_block_lower(trades, *, candidates: int, seed: str) -> float | None:
    if len(trades) < CANDIDATE_TRADE_MIN:
        return None
    groups=defaultdict(list)
    for t in trades:
        groups[t["date"]].append(t["net_bps"])
    if len(groups)<CANDIDATE_TRADE_MIN:
        return None
    ordered=[groups[k] for k in sorted(groups)]
    rand=random.Random(int(sha256(seed.encode("utf-8")).hexdigest()[:16],16))
    # Bonferroni correction over all 64 generated hypotheses.
    alpha=ALPHA/max(1,candidates)
    boot=[]
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled=[ordered[rand.randrange(len(ordered))] for _ in ordered]
        vals=[x for day in sampled for x in day]
        boot.append(mean(vals))
    boot.sort()
    return round(boot[max(0,int(alpha*len(boot))-1)],5)


def analyze(bars: list[dict], *, input_sha256: str, base_cost_bps: float=18.0) -> dict:
    """Single-file bounded search; uses the same scorer as cumulative history."""
    grouped=defaultdict(list)
    for row in bars:
        grouped[(row["date"],row["symbol"])].append(row)
    source={row["source"] for row in bars}
    if len(source)!=1:
        raise ResearchBlocked("MIXED_SYNTHETIC_REAL_INPUT")
    by_id={}
    for v in variants():
        by_id[v["id"]]=[
            t for bucket in grouped.values()
            if (t:=replay_one_day(bucket,v,cost_bps=base_cost_bps)) is not None
        ]
    return analyze_trade_records(
        by_id, sorted({key[0] for key in grouped}),
        input_sha256=input_sha256, source=next(iter(source)),
        base_cost_bps=base_cost_bps,
    )


def analyze_trade_records(
        trades_by_id: dict, observed_days: list[str], *,
        input_sha256: str, source: str, base_cost_bps: float=18.0) -> dict:
    """Long-lived compact evidence ledger scoring, same locked-day gates.

    Ingestion is performed by the separate local history writer. This
    function neither authenticates the issuer/source nor grants orders.
    """
    if (not isinstance(base_cost_bps,(int,float))
            or not math.isfinite(base_cost_bps)
            or base_cost_bps < MIN_ROUND_TRIP_COST_BPS):
        raise ResearchBlocked("ROUND_TRIP_COST_UNREALISTIC")
    if not isinstance(input_sha256,str) or not re.fullmatch("[0-9a-f]{64}",input_sha256):
        raise ResearchBlocked("INPUT_FINGERPRINT_INVALID")
    if source not in ALLOWED_SOURCES:
        raise ResearchBlocked("SOURCE_OR_QUALITY_NOT_CONFIRMED")
    if not isinstance(observed_days,list) or observed_days!=sorted(set(observed_days)):
        raise ResearchBlocked("INVALID_DATE_SERIES")
    days=observed_days
    allowed_ids={v["id"] for v in variants()}
    if not isinstance(trades_by_id,dict) or not set(trades_by_id).issubset(allowed_ids):
        raise ResearchBlocked("UNKNOWN_RESEARCH_VARIANT")
    for key,trade_list in trades_by_id.items():
        if not isinstance(trade_list,list):
            raise ResearchBlocked("TRADE_LEDGER_INVALID")
        seen=set()
        for row in trade_list:
            if (not isinstance(row,dict) or row.get("strategy_id")!=key
                    or row.get("source")!=source
                    or row.get("date") not in days
                    or row.get("real_submit_allowed") is not False
                    or type(row.get("symbol")) is not str
                    or not isinstance(row.get("gross_bps"),(float,int))
                    or not math.isfinite(row["gross_bps"])
                    or row.get("cost_bps")!=base_cost_bps
                    or abs(row["net_bps"]-(row["gross_bps"]-base_cost_bps))>0.00011):
                raise ResearchBlocked("TRADE_LEDGER_INTEGRITY_FAILURE")
            uniq=(row["symbol"],row["date"])
            if uniq in seen:
                raise ResearchBlocked("DUPLICATE_RESEARCH_TRADE")
            seen.add(uniq)
    hypotheses=variants()
    result={
        "schema_version":SCHEMA_VERSION,
        "input_sha256":input_sha256,
        "source":source,
        "llm_api_tokens_used":0,
        "requires_paid_api":False,
        "hypotheses_evaluated":len(hypotheses),
        "observed_days":len(days),
        "cost_assumption_roundtrip_bps":base_cost_bps,
        "live_trading_authorized":False,
        "real_submit_allowed":False,
        "shadow_order_created":False,
        "oos_selection_policy":"candidate selected using TRAIN+VALIDATION only; TEST not used for selection",
        "profitability_guaranteed":False,
        "promotion_eligible":False,
        "status":"INSUFFICIENT_HISTORY",
        "best_research_candidate":None,
        "reason":"NEEDS_HISTORICAL_BARS",
    }
    if len(days)<90:
        return result
    # Chronological day-disjoint windows, with a one-day purge gap
    # at train/validation and validation/test boundaries.
    a=max(1,int(len(days)*.60))
    b=max(a+2,int(len(days)*.80))
    train_days=set(days[:a])
    val_days=set(days[a+1:b])
    test_days=set(days[b+1:])
    result["windows"]={
        "train":[min(train_days),max(train_days),len(train_days)],
        "validation":[min(val_days),max(val_days),len(val_days)],
        "test":[min(test_days),max(test_days),len(test_days)],
        "purge_days":[days[a],days[b]],
    }
    candidate_pool=[]
    for v in hypotheses:
        trades=trades_by_id.get(v["id"],[])
        tr=[x for x in trades if x["date"] in train_days]
        va=[x for x in trades if x["date"] in val_days]
        tm=_metric(tr)
        vm=_metric(va)
        # Train-selection and validation gates prevent a brute-force winner
        # from being awarded a future shadow recommendation by chance.
        if (tm["trades"]<CANDIDATE_TRADE_MIN or
                vm["trades"]<CANDIDATE_TRADE_MIN or
                tm["distinct_days"]<CANDIDATE_TRADE_MIN or
                vm["distinct_days"]<CANDIDATE_TRADE_MIN or
                (tm["mean_net_bps"] or 0)<=0 or
                (vm["mean_net_bps"] or 0)<=0):
            continue
        lower=_day_block_lower(va,candidates=len(hypotheses),
                               seed=input_sha256+"|"+v["id"]+"|validation")
        stressed=_metric(va,cost_override=base_cost_bps*1.75)
        if (lower is None or lower<=0
                or (stressed["mean_net_bps"] or 0)<=0):
            continue
        candidate_pool.append((lower,tm["mean_net_bps"],v,tm,vm))
    if not candidate_pool:
        result.update(status="NO_VALIDATED_EDGE",
                      reason="NO_CANDIDATE_PASSED_COST_AND_MULTIPLE_TESTING")
        return result
    # The entire unseen TEST window is evaluated only for this preselected
    # variant. Never choose another variant based on TEST outcomes.
    candidate_pool.sort(key=lambda x:(-x[0],-x[1],x[2]["id"]))
    lower,_,winner,train_metrics,val_metrics=candidate_pool[0]
    test_trades=[x for x in trades_by_id.get(winner["id"],[]) if x["date"] in test_days]
    hold=_metric(test_trades)
    hold_lower=_day_block_lower(test_trades,candidates=1,
                                seed=input_sha256+"|"+winner["id"]+"|locked_test")
    stress=_metric(test_trades,cost_override=base_cost_bps*2)
    observed_n=(train_metrics["trades"]+val_metrics["trades"]+hold["trades"])
    strong=(source=="MS2_RSS_15S_CONFIRMED" and
            observed_n>=100 and
            hold["distinct_days"]>=HOLDOUT_TRADE_MIN and
            hold_lower is not None and hold_lower>0 and
            (stress["mean_net_bps"] or 0)>0)
    result.update({
        "status":"SHADOW_REVIEW_CANDIDATE" if strong else "EDGE_UNVERIFIED",
        "reason":"REQUIRES_OWNER_REVIEW_AND_FORWARD_SHADOW" if strong
                 else "INSUFFICIENT_REAL_OOS_OR_STRESSED_EDGE",
        "best_research_candidate":{
            "strategy":winner,"train":train_metrics,"validation":val_metrics,
            "validation_bonferroni_block_bootstrap_lower_bps":lower,
            "test":hold,
            "test_block_bootstrap_lower_bps":hold_lower,
            "test_double_cost":stress,
            "observed_trades":observed_n,
            "training_candidate_count":len(candidate_pool),
            "research_only":True,
            "real_submit_allowed":False,
        },
    })
    return result
