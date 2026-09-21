#!/usr/bin/env python3
"""Expanding-window walk-forward validation. Research only."""
import argparse,csv,json
from pathlib import Path
from collections import defaultdict
from scripts.calibrate_ev import stats

def windows(rows,min_train=30,test_size=10):
    if min_train<1 or test_size<1: raise ValueError("window sizes must be positive")
    ordered=sorted(rows,key=lambda r:r.get("entry_ts",""))
    out=[]; start=min_train
    while start < len(ordered):
        end=min(len(ordered),start+test_size)
        out.append((ordered[:start],ordered[start:end]))
        start=end
    return out

def summarize(rows):
    g=defaultdict(list)
    for r in rows:
        try:g[r["strategy_key"]].append(float(r["pnl_pct"]))
        except (KeyError,TypeError,ValueError):continue
    return {k:stats(v) for k,v in sorted(g.items())}

def validate(path,min_train=30,test_size=10):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:rows=[r for r in csv.DictReader(f) if str(r.get("promotion_eligible","")).strip().lower()=="true"]
    folds=[]
    for i,(train,test) in enumerate(windows(rows,min_train,test_size),1):
        folds.append({"fold":i,"train_n":len(train),"oos_n":len(test),
          "oos_start":test[0].get("entry_ts") if test else None,"oos_end":test[-1].get("entry_ts") if test else None,
          "oos_groups":summarize(test)})
    stability={}
    keys=sorted({k for f in folds for k in f["oos_groups"]})
    for k in keys:
        seen=[f["oos_groups"][k] for f in folds if k in f["oos_groups"]]
        positive=sum(1 for x in seen if x["avg_pl_pct"]>0 and x["profit_factor"]>=1.10)
        stability[k]={"oos_folds":len(seen),"positive_edge_folds":positive,
          "positive_edge_fold_rate":round(positive/len(seen),4) if seen else 0}
    return {"schema_version":1,"policy":"expanding_window_walk_forward","pnl_semantics":"pnl_pct_is_net_cost_already_applied",
      "min_train":min_train,"test_size":test_size,"folds":folds,"stability":stability}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="data/research_run/trade_results.csv");ap.add_argument("--output",default="data/research_run/walk_forward.json");ap.add_argument("--min-train",type=int,default=30);ap.add_argument("--test-size",type=int,default=10);a=ap.parse_args()
    out=validate(a.input,a.min_train,a.test_size);Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
