#!/usr/bin/env python3
"""Research-only comparison of entry latency after the first observed print.

This module does NOT choose trade direction. Callers must supply LONG/SHORT from
information available at decision time. All variants share the same EOD exit,
so the experiment isolates entry timing rather than mixing exit policies.
"""
from scripts.run_research_pipeline import parse_ts

ENTRY_DELAYS_SEC=(0,15,30,60,300)

def _entry_index(rows, delay_sec):
    if not rows: return None
    first=parse_ts(rows[0]["ts"])
    for i,row in enumerate(rows):
        if (parse_ts(row["ts"])-first).total_seconds()>=delay_sec:
            return i
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
          "side":side,"entry_delay_sec":delay,"decision_ts":rows[i]["ts"],
          "information_cutoff_ts":rows[i]["ts"],"entry_ts":rows[i]["ts"],
          "exit_ts":exit_bar["ts"],"entry":entry,"exit":exit_px,
          "gross_pnl_pct":gross,"cost_pct":cost_pct,"net_pnl_pct":net,
          "pnl_pct":net,"mfe_pct":mfe,"mae_pct":mae,
          "missed_move_pct_vs_open":missed,
          "entry_policy":"OPEN" if delay==0 else ("OR5_WAIT" if delay==300 else f"WAIT_{delay}S"),
          "information_policy":"PREOPEN_PLUS_FIRST_PRINT" if delay==0 else f"OBSERVED_THROUGH_{delay}S"
        })
    return out
