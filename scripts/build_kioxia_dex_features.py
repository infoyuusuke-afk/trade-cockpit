#!/usr/bin/env python3
"""Build leakage-safe point-in-time DEX features for C-189."""
from __future__ import annotations
import argparse, csv
from bisect import bisect_right
from datetime import datetime
from zoneinfo import ZoneInfo

JST=ZoneInfo("Asia/Tokyo")
SNAPS=("08:00","08:30","08:45","08:55")

def ms_at(day, hhmm):
    dt=datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=JST)
    return int(dt.timestamp()*1000)

def last_close(rows, cutoff):
    ts=[int(r["t"]) for r in rows]
    i=bisect_right(ts,cutoff)-1
    return None if i<0 else float(rows[i]["c"])

def build(rows, session_day, prev_tse_close):
    rows=sorted(rows,key=lambda r:int(r["t"]))
    out={"session_day":session_day,"prev_tse_close":prev_tse_close}
    for s in SNAPS:
        px=last_close(rows,ms_at(session_day,s))
        key="dex_"+s.replace(":","")
        out[key]=px
        out[key+"_gap_pct"]=None if px is None else (px/prev_tse_close-1)*100
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dex-csv",required=True)
    p.add_argument("--session-day",required=True)
    p.add_argument("--prev-tse-close",type=float,required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    with open(a.dex_csv,newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
    result=build(rows,a.session_day,a.prev_tse_close)
    with open(a.out,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=result.keys()); w.writeheader(); w.writerow(result)

if __name__=="__main__": main()
