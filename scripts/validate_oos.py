#!/usr/bin/env python3
"""Chronological holdout validation for empirical trade results. Research only."""
import argparse,csv,json
from pathlib import Path
from collections import defaultdict
from scripts.calibrate_ev import stats

def split_rows(rows, train_ratio=0.70):
    if not 0.5 <= train_ratio < 1.0: raise ValueError("train_ratio must be >=0.5 and <1.0")
    ordered=sorted(rows,key=lambda r:r.get("entry_ts",""))
    cut=int(len(ordered)*train_ratio)
    return ordered[:cut],ordered[cut:]

def net_pnl(r):
    # Current trade-result contract: pnl_pct is already net of cost.
    return float(r["pnl_pct"])

def summarize(rows):
    groups=defaultdict(list)
    for r in rows:
        try: groups[r["strategy_key"]].append(net_pnl(r))
        except (KeyError,TypeError,ValueError): continue
    return {k:stats(v) for k,v in sorted(groups.items())}

def validate(path,train_ratio=.70):
    with Path(path).open(encoding="utf-8-sig",newline="") as f: rows=[r for r in csv.DictReader(f) if str(r.get("promotion_eligible","")).strip().lower()=="true"]
    train,oos=split_rows(rows,train_ratio)
    return {"schema_version":1,"split_policy":"chronological_holdout","train_ratio":train_ratio,
      "pnl_semantics":"pnl_pct_is_net_cost_already_applied","train":{"n":len(train),"groups":summarize(train)},
      "oos":{"n":len(oos),"groups":summarize(oos)}}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="data/research_run/trade_results.csv");ap.add_argument("--output",default="data/research_run/oos_validation.json");ap.add_argument("--train-ratio",type=float,default=.70);a=ap.parse_args()
    out=validate(a.input,a.train_ratio);Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
