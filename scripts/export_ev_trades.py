#!/usr/bin/env python3
"""Export only strategy-labelled, triggered paper trades into EV calibration CSV."""
import csv,json,argparse
from pathlib import Path

FIELDS=["strategy_key","pnl_pct","cost_pct","symbol","side","entry_ts","exit_ts"]

def rows(history):
    out=[]
    for r in history:
        key=r.get("strategy_key")
        if not key or not r.get("triggered"): continue
        entry=r.get("entry"); close=r.get("close"); side=str(r.get("side") or "").upper()
        if not entry or close is None or side not in {"LONG","SHORT"}: continue
        raw=(float(close)-float(entry))/float(entry)*100
        if side=="SHORT": raw=-raw
        out.append({"strategy_key":key,"pnl_pct":round(raw,6),"cost_pct":float(r.get("cost_pct") or 0),
          "symbol":str(r.get("ticker") or "").replace(".T",""),"side":side,
          "entry_ts":r.get("entry_ts") or r.get("date") or "","exit_ts":r.get("exit_ts") or r.get("date") or ""})
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="paper_trade_history.json");ap.add_argument("--output",default="data/trade_results.csv");a=ap.parse_args()
    history=json.loads(Path(a.input).read_text(encoding="utf-8-sig")); data=rows(history)
    dst=Path(a.output);dst.parent.mkdir(parents=True,exist_ok=True)
    with dst.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(data)
    print(f"exported {len(data)} strategy-labelled triggered trades")
if __name__=="__main__":main()
