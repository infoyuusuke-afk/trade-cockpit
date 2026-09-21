#!/usr/bin/env python3
"""Research-only comparison of entry latency after the first observed print.

This module does NOT choose trade direction. Callers must supply LONG/SHORT from
information available at decision time. All variants share the same EOD exit,
so the experiment isolates entry timing rather than mixing exit policies.
"""
from scripts.run_research_pipeline import parse_ts
from datetime import datetime, timedelta

ENTRY_DELAYS_SEC=(0,15,30,60,300)
CLOCK_OR5_TIME="09:05:00"

def _entry_index(rows, delay_sec):
    if not rows: return None
    first=parse_ts(rows[0]["ts"])
    for i,row in enumerate(rows):
        if (parse_ts(row["ts"])-first).total_seconds()>=delay_sec:
            return i
    return None

def _clock_or5_index(rows):
    if not rows: return None
    d=parse_ts(rows[0]["ts"]).date()
    target=datetime.combine(d,datetime.strptime(CLOCK_OR5_TIME,"%H:%M:%S").time())
    first=parse_ts(rows[0]["ts"])
    if getattr(first,"tzinfo",None) is not None:
        target=target.replace(tzinfo=first.tzinfo)
    for i,row in enumerate(rows):
        if parse_ts(row["ts"])>=target: return i
    return None

def compare_entry_delays(rows, side, cost_pct=0.10):
    if side not in ("LONG","SHORT"): raise ValueError("side must be LONG or SHORT")
    if not rows: return []
    exit_bar=rows[-1]
    out=[]
    for delay in ENTRY_DELAYS_SEC:
        i=_entry_index(rows,delay)
        if i is None: continue
        entry=rows[i]["open"]; exit_px=exit_bar["close"]
        actual_delay=(parse_ts(rows[i]["ts"])-parse_ts(rows[0]["ts"])).total_seconds()
        gross=((exit_px/entry)-1)*100
        if side=="SHORT": gross=-gross
        future=rows[i:]
        if side=="LONG":
            mfe=(max(x["high"] for x in future)/entry-1)*100
            mae=(min(x["low"] for x in future)/entry-1)*100
            missed=((entry/rows[0]["open"])-1)*100
        else:
            mfe=(1-min(x["low"] for x in future)/entry)*100
            mae=(1-max(x["high"] for x in future)/entry)*100
            missed=((rows[0]["open"]/entry)-1)*100
        net=gross-cost_pct
        out.append({
          "side":side,"entry_delay_sec":delay,"requested_entry_delay_sec":delay,
          "actual_entry_delay_sec":actual_delay,
          "entry_delay_slippage_sec":actual_delay-delay,
          "decision_ts":rows[i]["ts"],
          "information_cutoff_ts":rows[i]["ts"],"entry_ts":rows[i]["ts"],
          "exit_ts":exit_bar["ts"],"entry":entry,"exit":exit_px,
          "gross_pnl_pct":gross,"cost_pct":cost_pct,"net_pnl_pct":net,
          "pnl_pct":net,"mfe_pct":mfe,"mae_pct":mae,
          "missed_move_pct_vs_open":missed,
          "entry_policy":"OPEN" if delay==0 else ("OR5_WAIT" if delay==300 else f"WAIT_{delay}S"),
          "information_policy":"PREOPEN_PLUS_FIRST_PRINT" if delay==0 else f"OBSERVED_THROUGH_{delay}S"
        })
    # Separate clock-time OR5 from five minutes after the first observed print.
    ci=_clock_or5_index(rows)
    if ci is not None:
        entry=rows[ci]["open"]; exit_px=exit_bar["close"]
        gross=((exit_px/entry)-1)*100
        if side=="SHORT": gross=-gross
        future=rows[ci:]
        if side=="LONG":
            mfe=(max(x["high"] for x in future)/entry-1)*100
            mae=(min(x["low"] for x in future)/entry-1)*100
            missed=((entry/rows[0]["open"])-1)*100
        else:
            mfe=(1-min(x["low"] for x in future)/entry)*100
            mae=(1-max(x["high"] for x in future)/entry)*100
            missed=((rows[0]["open"]/entry)-1)*100
        actual=(parse_ts(rows[ci]["ts"])-parse_ts(rows[0]["ts"])).total_seconds()
        out.append({"side":side,"entry_delay_sec":None,"requested_entry_delay_sec":None,
          "actual_entry_delay_sec":actual,"entry_delay_slippage_sec":None,
          "decision_ts":rows[ci]["ts"],"information_cutoff_ts":rows[ci]["ts"],
          "entry_ts":rows[ci]["ts"],"exit_ts":exit_bar["ts"],"entry":entry,"exit":exit_px,
          "gross_pnl_pct":gross,"cost_pct":cost_pct,"net_pnl_pct":gross-cost_pct,
          "pnl_pct":gross-cost_pct,"mfe_pct":mfe,"mae_pct":mae,
          "missed_move_pct_vs_open":missed,"entry_policy":"CLOCK_OR5_WAIT",
          "information_policy":"OBSERVED_THROUGH_CLOCK_09_05"})
    return out


def summarize_entry_policies(results):
    """Aggregate comparable entry policies. Descriptive research, not a live gate."""
    groups={}
    for r in results:
        groups.setdefault(r["entry_policy"],[]).append(r)
    out=[]
    for policy,rs in sorted(groups.items()):
        pnls=[float(x["net_pnl_pct"]) for x in rs]
        wins=sum(x for x in pnls if x>0)
        losses=-sum(x for x in pnls if x<0)
        pf=(wins/losses) if losses>0 else (float("inf") if wins>0 else 0.0)
        ordered=sorted(pnls)
        tail_n=max(1,(len(ordered)+9)//10)
        equity=0.0; peak=0.0; max_dd=0.0
        for p in pnls:
            equity+=p
            peak=max(peak,equity)
            max_dd=min(max_dd,equity-peak)
        out.append({
          "entry_policy":policy,"sample_size":len(rs),
          "win_rate":sum(1 for x in pnls if x>0)/len(rs),
          "avg_net_pnl_pct":sum(pnls)/len(rs),
          "profit_factor":pf,
          "worst_net_pnl_pct":ordered[0],
          "bottom_10pct_avg_net_pnl_pct":sum(ordered[:tail_n])/tail_n,
          "max_drawdown_pct":max_dd,
          "avg_mfe_pct":sum(float(x["mfe_pct"]) for x in rs)/len(rs),
          "avg_mae_pct":sum(float(x["mae_pct"]) for x in rs)/len(rs),
          "worst_mae_pct":min(float(x["mae_pct"]) for x in rs),
          "avg_missed_move_pct_vs_open":sum(float(x["missed_move_pct_vs_open"]) for x in rs)/len(rs),
          "avg_actual_entry_delay_sec":sum(float(x["actual_entry_delay_sec"]) for x in rs)/len(rs),
          "avg_entry_delay_slippage_sec":sum(float(x["entry_delay_slippage_sec"]) for x in rs)/len(rs),
          "research_only":True
        })
    return out


def fixed_preopen_regime_labels(context):
    """Only labels knowable no later than the opening decision boundary.

    Never use same-day realized range, OR5/OR15, VWAP, or later tape here.
    """
    gap=context.get("gap_pct")
    state=context.get("open_state")
    prior_vol=context.get("prior_day_range_pct")
    return {
      "gap_regime": "UNKNOWN" if gap is None else ("GD_LT_-1" if gap < -1 else ("GU_GT_1" if gap > 1 else "FLAT_-1_TO_1")),
      "open_regime": state or "UNKNOWN",
      "prior_vol_regime": "UNKNOWN" if prior_vol is None else ("LOW_LT_1" if prior_vol < 1 else ("HIGH_GE_2" if prior_vol >= 2 else "MID_1_TO_2"))
    }

def attach_preopen_regime(results, context):
    labels=fixed_preopen_regime_labels(context)
    return [{**r,**labels} for r in results]

def summarize_by_regime(results, regime_key):
    groups={}
    for r in results:
        groups.setdefault(r.get(regime_key,"UNKNOWN"),[]).append(r)
    return {k:summarize_entry_policies(v) for k,v in sorted(groups.items())}


def compare_policy_tradeoffs(summary):
    """Compare waiting policies with OPEN. Positive risk improvement is better."""
    by={x["entry_policy"]:x for x in summary}
    base=by.get("OPEN")
    if not base: raise ValueError("OPEN baseline required")
    out=[]
    for policy,x in sorted(by.items()):
        if policy=="OPEN": continue
        out.append({
          "entry_policy":policy,
          "avg_pnl_delta_vs_open_pct":x["avg_net_pnl_pct"]-base["avg_net_pnl_pct"],
          "avg_mae_improvement_vs_open_pct":x["avg_mae_pct"]-base["avg_mae_pct"],
          "worst_loss_improvement_vs_open_pct":x["worst_net_pnl_pct"]-base["worst_net_pnl_pct"],
          "max_dd_improvement_vs_open_pct":x["max_drawdown_pct"]-base["max_drawdown_pct"],
          "missed_move_delta_vs_open_pct":x["avg_missed_move_pct_vs_open"]-base["avg_missed_move_pct_vs_open"],
          "research_only":True
        })
    return out
