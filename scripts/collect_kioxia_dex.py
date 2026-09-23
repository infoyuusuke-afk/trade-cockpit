#!/usr/bin/env python3
"""C-189: collect Hyperliquid xyz:KIOXIA candles for research only.

No trading/signalling/order path is touched. Output is append-safe CSV input for
Strategy Lab. Hyperliquid candleSnapshot currently exposes up to 5000 candles.
"""
from __future__ import annotations
import argparse, csv, json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.hyperliquid.xyz/info"
FIELDS = ["t","T","s","i","o","h","l","c","v","n"]

def fetch(coin: str, interval: str, start_ms: int, end_ms: int):
    body=json.dumps({"type":"candleSnapshot","req":{"coin":coin,"interval":interval,
        "startTime":start_ms,"endTime":end_ms}}).encode()
    req=urllib.request.Request(API,data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=20) as r:
        data=json.load(r)
    if not isinstance(data,list):
        raise RuntimeError(f"unexpected response: {data!r}")
    return data

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--coin",default="xyz:KIOXIA")
    p.add_argument("--interval",default="1m")
    p.add_argument("--start-ms",type=int,required=True)
    p.add_argument("--end-ms",type=int,default=lambda: int(time.time()*1000))
    p.add_argument("--out",default="data/research/kioxia_dex_candles.csv")
    a=p.parse_args()
    end_ms = int(time.time()*1000) if callable(a.end_ms) else a.end_ms
    rows=fetch(a.coin,a.interval,a.start_ms,end_ms)
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    existing={}
    if out.exists():
        with out.open(newline="",encoding="utf-8") as f:
            for r in csv.DictReader(f): existing[(r["s"],r["i"],r["t"])]=r
    for r in rows:
        existing[(str(r.get("s",a.coin)),str(r.get("i",a.interval)),str(r["t"]))] = {
            k:r.get(k,"") for k in FIELDS
        }
    ordered=sorted(existing.values(),key=lambda r:(r["s"],r["i"],int(r["t"])))
    with out.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(ordered)
    print(json.dumps({"coin":a.coin,"interval":a.interval,"fetched":len(rows),
      "stored":len(ordered),"out":str(out),"collected_at_utc":datetime.now(timezone.utc).isoformat()},
      ensure_ascii=False))

if __name__=="__main__":
    main()
