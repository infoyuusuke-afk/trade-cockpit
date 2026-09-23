#!/usr/bin/env python3
"""C-189 walk-forward comparison: baseline vs DEX vs combined.

Research-only. Ordinary least squares is fitted using prior sessions only.
No sklearn dependency; missing rows are excluded rather than imputed.
"""
from __future__ import annotations
import argparse,csv,json,math

def num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except (TypeError,ValueError): return None

def solve(a,b):
    n=len(b)
    for i in range(n):
        pivot=max(range(i,n),key=lambda r:abs(a[r][i]))
        if abs(a[pivot][i])<1e-12:return None
        a[i],a[pivot]=a[pivot],a[i];b[i],b[pivot]=b[pivot],b[i]
        q=a[i][i]
        a[i]=[x/q for x in a[i]];b[i]/=q
        for r in range(n):
            if r==i:continue
            q=a[r][i];a[r]=[x-q*y for x,y in zip(a[r],a[i])];b[r]-=q*b[i]
    return b

def fit(rows,features,target):
    clean=[]
    for r in rows:
        xs=[num(r.get(f)) for f in features]; y=num(r.get(target))
        if y is not None and all(x is not None for x in xs):clean.append(([1.0]+xs,y))
    if len(clean)<len(features)+2:return None
    p=len(features)+1
    xtx=[[sum(x[i]*x[j] for x,_ in clean) for j in range(p)] for i in range(p)]
    xty=[sum(x[i]*y for x,y in clean) for i in range(p)]
    return solve(xtx,xty)

def predict(beta,row,features):
    xs=[num(row.get(f)) for f in features]
    if beta is None or any(x is None for x in xs):return None
    return beta[0]+sum(b*x for b,x in zip(beta[1:],xs))

def walk(rows,features,target,min_train):
    out=[]
    for i in range(min_train,len(rows)):
        beta=fit(rows[:i],features,target); pred=predict(beta,rows[i],features); actual=num(rows[i].get(target))
        if pred is not None and actual is not None:out.append((pred,actual))
    if not out:return {"n":0}
    mae=sum(abs(p-a) for p,a in out)/len(out)
    hit=sum((p>0)==(a>0) for p,a in out if p!=0 and a!=0)
    den=sum(1 for p,a in out if p!=0 and a!=0)
    return {"n":len(out),"mae":mae,"direction_hit_rate":hit/den if den else None}

def main():
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--target",required=True)
    p.add_argument("--baseline-features",required=True);p.add_argument("--dex-features",default="dex_0830_gap_pct,dex_0845_gap_pct,dex_0855_gap_pct")
    p.add_argument("--min-train",type=int,default=30);p.add_argument("--out",required=True);a=p.parse_args()
    with open(a.input,newline="",encoding="utf-8") as f:rows=list(csv.DictReader(f))
    rows.sort(key=lambda r:r["session_day"])
    base=a.baseline_features.split(",");dex=a.dex_features.split(",")
    result={"target":a.target,"min_train":a.min_train,
      "baseline":walk(rows,base,a.target,a.min_train),
      "dex":walk(rows,dex,a.target,a.min_train),
      "combined":walk(rows,base+dex,a.target,a.min_train)}
    b=result["baseline"];c=result["combined"]
    result["incremental"]={"mae_improvement":(b.get("mae")-c.get("mae")) if b.get("mae") is not None and c.get("mae") is not None else None,
      "direction_hit_rate_improvement":(c.get("direction_hit_rate")-b.get("direction_hit_rate")) if b.get("direction_hit_rate") is not None and c.get("direction_hit_rate") is not None else None}
    with open(a.out,"w",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
if __name__=="__main__":main()
