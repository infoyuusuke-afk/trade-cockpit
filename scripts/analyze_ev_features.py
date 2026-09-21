#!/usr/bin/env python3
"""Descriptive EV segmentation by fixed point-in-time feature buckets."""
import argparse,csv,json
from collections import defaultdict
from pathlib import Path
from datetime import datetime,timezone
from scripts.calibrate_ev import stats

BUCKETS={
 "volume_ratio_20":[(0,1,"<1x"),(1,2,"1-2x"),(2,float("inf"),">=2x")],
 "gap_pct":[(-float("inf"),-1,"GD<-1%"),(-1,1,"-1%..+1%"),(1,float("inf"),"GU>+1%")],
 "vwap_deviation_pct":[(-float("inf"),-0.5,"<-0.5%"),(-0.5,0.5,"-0.5%..+0.5%"),(0.5,float("inf"),">=+0.5%")],
 "intraday_range_pct":[(0,1,"<1%"),(1,2,"1-2%"),(2,float("inf"),">=2%")],
}
def bucket(name,value):
    try: x=float(value)
    except (TypeError,ValueError): return None
    for lo,hi,label in BUCKETS[name]:
        if lo<=x<hi:return label
    return None

def analyze(path):
    groups=defaultdict(list)
    with Path(path).open(encoding="utf-8-sig",newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                pnl=float(r["pnl_pct"])-float(r.get("cost_pct") or 0)
                key=r["strategy_key"]
            except (KeyError,TypeError,ValueError):continue
            for feature in BUCKETS:
                b=bucket(feature,r.get(feature))
                if b is not None: groups[(key,feature,b)].append(pnl)
    return [{"strategy_key":k[0],"feature":k[1],"bucket":k[2],**stats(v)} for k,v in sorted(groups.items())]

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="data/trade_results.csv");ap.add_argument("--output",default="data/ev_feature_buckets.json");a=ap.parse_args()
    out={"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"score_is_probability":False,"bucket_policy":"fixed_v0.1_not_optimized","groups":analyze(a.input) if Path(a.input).exists() else []}
    dst=Path(a.output);dst.parent.mkdir(parents=True,exist_ok=True);dst.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
