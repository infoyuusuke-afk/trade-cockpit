#!/usr/bin/env python3
"""15-second research backtest core. Confirmed bars only; no live orders."""
import csv, argparse
from pathlib import Path
from scripts.strategy_registry import validate
from scripts.signal_features import signal_features

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

def backtest_or_breakout(rows, side="LONG", cost_pct=0.10, stop_pct=None, target_pct=None, prev_close=None, market=None):
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
        exit_px=rows[-1]["close"]; exit_ts=rows[-1]["ts"]; exit_reason="EOD"
        # Evaluate exits only after the entry bar. If stop and target are both touched
        # in one 15s bar, choose STOP (conservative; intrabar order is unknowable).
        for x in rows[i+2:]:
            if side=="LONG":
                stop_hit=stop_pct is not None and x["low"] <= entry*(1-stop_pct/100)
                target_hit=target_pct is not None and x["high"] >= entry*(1+target_pct/100)
                stop_px=entry*(1-stop_pct/100) if stop_hit else None
                target_px=entry*(1+target_pct/100) if target_hit else None
            else:
                stop_hit=stop_pct is not None and x["high"] >= entry*(1+stop_pct/100)
                target_hit=target_pct is not None and x["low"] <= entry*(1-target_pct/100)
                stop_px=entry*(1+stop_pct/100) if stop_hit else None
                target_px=entry*(1-target_pct/100) if target_hit else None
            if stop_hit or target_hit:
                if stop_hit:
                    exit_px=stop_px; exit_reason="STOP"
                else:
                    exit_px=target_px; exit_reason="TARGET"
                exit_ts=x["ts"]; break
        gross=((exit_px-entry)/entry*100)*(1 if side=="LONG" else -1)
        trade={"strategy_key":key,"entry_ts":rows[i+1]["ts"],"exit_ts":exit_ts,"side":side,"entry":entry,"exit":exit_px,"pnl_pct":round(gross-cost_pct,6),"cost_pct":cost_pct,"exit_reason":exit_reason}\n        trade.update(signal_features(rows,i,prev_close,market)); trades.append(trade)
        break
    return trades

def rolling_vwap(rows, end):
    return vwap(rows[:end+1])

def find_or5_vwap_signal(rows, side="LONG"):
    """OR5 = first 20x15s bars. After OR5, require a VWAP cross on a completed bar.
    LONG: previous close <= previous VWAP and current close > current VWAP.
    SHORT: previous close >= previous VWAP and current close < current VWAP.
    The current close must also be beyond OR5 midpoint in trade direction.
    Returns signal bar index; caller enters next bar open.
    """
    if len(rows)<22: return None
    hi,lo=or_range(rows,20); mid=(hi+lo)/2
    for i in range(20,len(rows)-1):
        pv=rolling_vwap(rows,i-1); cv=rolling_vwap(rows,i)
        if pv is None or cv is None: continue
        if side=="LONG":
            ok=rows[i-1]["close"]<=pv and rows[i]["close"]>cv and rows[i]["close"]>mid
        else:
            ok=rows[i-1]["close"]>=pv and rows[i]["close"]<cv and rows[i]["close"]<mid
        if ok: return i
    return None

def backtest_or5_vwap(rows, side="LONG", cost_pct=0.10, prev_close=None, market=None):
    key="OR5_VWAP_RECLAIM_LONG" if side=="LONG" else "OR5_VWAP_REJECT_SHORT"
    if not validate(key): raise ValueError("unregistered strategy_key")
    i=find_or5_vwap_signal(rows,side)
    if i is None: return []
    entry=rows[i+1]["open"]; exit_px=rows[-1]["close"]
    gross=((exit_px-entry)/entry*100)*(1 if side=="LONG" else -1)
    return [{"strategy_key":key,"entry_ts":rows[i+1]["ts"],"exit_ts":rows[-1]["ts"],"side":side,
             "entry":entry,"exit":exit_px,"pnl_pct":round(gross-cost_pct,6),
             "cost_pct":cost_pct,"exit_reason":"EOD"}]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--side",choices=["LONG","SHORT"],default="LONG")
    ap.add_argument("--cost-pct",type=float,default=0.10)
    ap.add_argument("--stop-pct",type=float)
    ap.add_argument("--target-pct",type=float)
    ap.add_argument("--out",default="data/backtest_trade_results.csv")
    a=ap.parse_args()
    rows=load_bars(a.csv); trades=backtest_or_breakout(rows,a.side,a.cost_pct,a.stop_pct,a.target_pct)
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    fields=["strategy_key","entry_ts","exit_ts","side","entry","exit","pnl_pct","cost_pct","exit_reason"]
    with Path(a.out).open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields);w.writeheader();w.writerows(trades)
if __name__=="__main__": main()
