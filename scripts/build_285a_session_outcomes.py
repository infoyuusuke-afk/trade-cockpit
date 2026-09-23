#!/usr/bin/env python3
"""C-189: build TSE:285A session outcomes from confirmed intraday bars."""
from __future__ import annotations
import argparse,csv,json
from datetime import datetime,time
from zoneinfo import ZoneInfo
JST=ZoneInfo("Asia/Tokyo")

def pct(a,b): return (b/a-1)*100 if a else None
def parse_ts(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None: d=d.replace(tzinfo=JST)
    return d.astimezone(JST)
def build(rows,prev_close):
    xs=sorted(rows,key=lambda r:parse_ts(r["time"]))
    xs=[r for r in xs if time(9,0)<=parse_ts(r["time"]).time()<=time(15,30)]
    if not xs: raise ValueError("no regular-session bars")
    op=float(xs[0]["open"])
    def before(h,m):
        ys=[r for r in xs if parse_ts(r["time"]).time()<time(h,m)]
        return ys
    or5=before(9,5); or15=before(9,15)
    if not or5 or not or15: raise ValueError("insufficient bars for OR5/OR15")
    def close_at_or_before(h,m):
        ys=[r for r in xs if parse_ts(r["time"]).time()<=time(h,m)]
        return float(ys[-1]["close"]) if ys else None
    vol=sum(float(r["volume"]) for r in xs)
    vwap=(sum(((float(r["high"])+float(r["low"])+float(r["close"]))/3)*float(r["volume"]) for r in xs)/vol) if vol else None
    or5c=float(or5[-1]["close"]); or15c=float(or15[-1]["close"])
    return {
      "session_day":parse_ts(xs[0]["time"]).date().isoformat(),
      "prev_close":prev_close,"open":op,"open_gap_pct":pct(prev_close,op),
      "or5_high":max(float(r["high"]) for r in or5),"or5_low":min(float(r["low"]) for r in or5),
      "or15_high":max(float(r["high"]) for r in or15),"or15_low":min(float(r["low"]) for r in or15),
      "open_to_or5_pct":pct(op,or5c),"or5_to_or15_pct":pct(or5c,or15c),
      "open_to_0930_pct":pct(op,close_at_or_before(9,30)),
      "open_to_1000_pct":pct(op,close_at_or_before(10,0)),
      "session_vwap":vwap,"close":float(xs[-1]["close"]),"open_to_close_pct":pct(op,float(xs[-1]["close"]))
    }
def main():
    p=argparse.ArgumentParser();p.add_argument("--bars",required=True);p.add_argument("--prev-close",type=float,required=True);p.add_argument("--out",required=True);a=p.parse_args()
    with open(a.bars,newline="",encoding="utf-8-sig") as f: rows=list(csv.DictReader(f))
    out=build(rows,a.prev_close)
    with open(a.out,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
if __name__=="__main__":main()
