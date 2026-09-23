#!/usr/bin/env python3
"""C-189: evaluate incremental predictive value of DEX features.

Input is one row per TSE session. This is research-only and deliberately
separates open-gap targets from post-open targets.
"""
from __future__ import annotations
import argparse, csv, json, math, statistics

def finite(x):
    try: return math.isfinite(float(x))
    except (TypeError,ValueError): return False

def pearson(xs,ys):
    if len(xs)<3: return None
    mx,my=statistics.fmean(xs),statistics.fmean(ys)
    num=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx=sum((x-mx)**2 for x in xs); dy=sum((y-my)**2 for y in ys)
    return None if dx==0 or dy==0 else num/math.sqrt(dx*dy)

def summarize(rows, feature, target):
    pairs=[(float(r[feature]),float(r[target])) for r in rows
           if finite(r.get(feature)) and finite(r.get(target))]
    if not pairs: return {"n":0}
    xs,ys=zip(*pairs)
    signs=[(x>0)==(y>0) for x,y in pairs if x!=0 and y!=0]
    return {"n":len(pairs),"corr":pearson(xs,ys),
            "direction_hit_rate":(sum(signs)/len(signs) if signs else None),
            "mean_target":statistics.fmean(ys)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--features",default="dex_0830_gap_pct,dex_0845_gap_pct,dex_0855_gap_pct")
    p.add_argument("--targets",default="open_gap_pct,open_to_or5_pct,or5_to_or15_pct,open_to_0930_pct,open_to_1000_pct")
    p.add_argument("--out",required=True)
    a=p.parse_args()
    with open(a.input,newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
    report={"rows":len(rows),"results":{}}
    for feature in a.features.split(","):
        report["results"][feature]={}
        for target in a.targets.split(","):
            report["results"][feature][target]=summarize(rows,feature,target)
    with open(a.out,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)

if __name__=="__main__": main()
