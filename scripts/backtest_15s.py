#!/usr/bin/env python3
"""15-second research backtest core. Confirmed bars only; no live orders."""
import csv, argparse
from pathlib import Path
from scripts.strategy_registry import validate

def f(x): return float(x)

def load_bars(path):
    rows=[]
    with Path(path).open(encoding="utf-8-sig",newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append({"ts":r["time"],"open":f(r["open"]),"high":f(r["high"]),"low":f(r["low"]),"close":f(r["close"]),"volume":f(r["volume"])})
    return rows

def vwap(rows):
    pv=sum(((x["high"]+x["low"]+x["close"])/3)*x["volume"] for x in rows)
    vol=sum(x["volume"] for x in rows)
    return pv/vol if vol else None

def or_range(rows, bars):
    xs=rows[:bars]
    return max(x["high"] for x in xs),min(x["low"] for x in xs)

def backtest_or_breakout(rows, side="LONG", cost_pct=0.10):
    # 15 sec bars: OR15 = first 60 bars. Signal uses completed OR plus next completed bar.
    if len(rows)<62: return []
    key=f"OR15_BREAKOUT_{side}"
    if not validate(key): raise ValueError("unregistered strategy_key")
    hi,lo=or_range(rows,60)
    trades=[]
    for i in range(60,len(rows)-1):
        bar=rows[i]
        crossed=bar["close"]>hi if side=="LONG" else bar["close"]<lo
        if not crossed: continue
        # Conservative next-bar-open entry prevents same-bar lookahead.
        entry=rows[i+1]["open"]
        exit_px=rows[-1]["close"]
        gross=((exit_px-entry)/entry*100)*(1 if side=="LONG" else -1)
        trades.append({"strategy_key":key,"entry_ts":rows[i+1]["ts"],"exit_ts":rows[-1]["ts"],"side":side,"entry":entry,"exit":exit_px,"pnl_pct":round(gross-cost_pct,6),"cost_pct":cost_pct})
        break
    return trades

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--side",choices=["LONG","SHORT"],default="LONG")
    ap.add_argument("--cost-pct",type=float,default=0.10)
    ap.add_argument("--out",default="data/backtest_trade_results.csv")
    a=ap.parse_args()
    rows=load_bars(a.csv); trades=backtest_or_breakout(rows,a.side,a.cost_pct)
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    fields=["strategy_key","entry_ts","exit_ts","side","entry","exit","pnl_pct","cost_pct"]
    with Path(a.out).open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields);w.writeheader();w.writerows(trades)
if __name__=="__main__": main()
