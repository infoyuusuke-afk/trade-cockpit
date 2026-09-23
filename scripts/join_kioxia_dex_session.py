#!/usr/bin/env python3
"""C-189 deterministic join of DEX features, TSE outcomes and regime labels."""
from __future__ import annotations
import argparse,csv,json
from scripts.kioxia_dex_regime import regime

def main():
    p=argparse.ArgumentParser();p.add_argument("--dex-features",required=True);p.add_argument("--tse-outcome",required=True)
    p.add_argument("--prev-session",required=True);p.add_argument("--out",required=True);a=p.parse_args()
    with open(a.dex_features,newline="",encoding="utf-8") as f:dex=next(csv.DictReader(f))
    with open(a.tse_outcome,encoding="utf-8") as f:tse=json.load(f)
    if dex["session_day"]!=tse["session_day"]:raise ValueError("session_day mismatch")
    out={**dex,**tse,**regime(a.prev_session,tse["session_day"])}
    fields=list(out.keys())
    try:
        with open(a.out,newline="",encoding="utf-8") as f:
            old=list(csv.DictReader(f))
    except FileNotFoundError: old=[]
    keyed={r["session_day"]:r for r in old};keyed[out["session_day"]]=out
    with open(a.out,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows([keyed[k] for k in sorted(keyed)])
if __name__=="__main__":main()
