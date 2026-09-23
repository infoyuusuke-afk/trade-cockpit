#!/usr/bin/env python3
"""C-189 regime-stratified walk-forward comparison."""
from __future__ import annotations
import argparse,csv,json
from scripts.compare_kioxia_dex_models import walk

REGIMES=("weekday_overnight","weekend_or_holiday","multi_day_gap")
TARGETS=("open_gap_pct","open_to_or5_pct","or5_to_or15_pct","open_to_0930_pct","open_to_1000_pct","open_to_close_pct")

def compare(rows,base,dex,min_train):
    out={}
    for regime in ("all",)+REGIMES:
        rs=rows if regime=="all" else [r for r in rows if r.get("regime")==regime]
        out[regime]={"sessions":len(rs),"targets":{}}
        for target in TARGETS:
            b=walk(rs,base,target,min_train);d=walk(rs,dex,target,min_train);c=walk(rs,base+dex,target,min_train)
            out[regime]["targets"][target]={"baseline":b,"dex":d,"combined":c,
              "incremental":{"mae_improvement":(b.get("mae")-c.get("mae")) if b.get("mae") is not None and c.get("mae") is not None else None,
              "direction_hit_rate_improvement":(c.get("direction_hit_rate")-b.get("direction_hit_rate")) if b.get("direction_hit_rate") is not None and c.get("direction_hit_rate") is not None else None}}
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--baseline-features",required=True)
    p.add_argument("--dex-features",default="dex_0830_gap_pct,dex_0845_gap_pct,dex_0855_gap_pct");p.add_argument("--min-train",type=int,default=30);p.add_argument("--out",required=True);a=p.parse_args()
    with open(a.input,newline="",encoding="utf-8") as f:rows=list(csv.DictReader(f))
    rows.sort(key=lambda r:r["session_day"])
    report=compare(rows,a.baseline_features.split(","),a.dex_features.split(","),a.min_train)
    with open(a.out,"w",encoding="utf-8") as f:json.dump(report,f,ensure_ascii=False,indent=2)
if __name__=="__main__":main()
