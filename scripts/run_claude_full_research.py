#!/usr/bin/env python3
"""One-command Claude TradingView handoff -> promotion-evidence research run. Never LIVE."""
import argparse,csv,json
from collections import defaultdict
from pathlib import Path
from scripts.run_claude_tradingview_handoff import run_handoff
from scripts.calibrate_ev import stats
from scripts.validate_oos import validate as validate_oos
from scripts.walk_forward import validate as validate_wf
from scripts.promotion_gate import evaluate

def eligible_rows(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        return [r for r in csv.DictReader(f) if str(r.get("promotion_eligible","")).strip().lower()=="true"]

def calibrate_eligible(path):
    groups=defaultdict(list)
    for r in eligible_rows(path):
        try: groups[r["strategy_key"]].append(float(r.get("net_pnl_pct") or r["pnl_pct"]))
        except (KeyError,TypeError,ValueError): continue
    return {"schema_version":1,"score_is_probability":False,
      "promotion_filter":"promotion_eligible=true only",
      "groups":{k:stats(v) for k,v in sorted(groups.items())}}

def run(payload,out_dir,cost_pct=.10,prev_close=None,train_ratio=.70,min_train=30,test_size=10):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    receipt,trade,feature_ev,source_manifest,summary=run_handoff(payload,out,"15S",cost_pct,prev_close)
    calibration=calibrate_eligible(trade)
    cal_path=out/"ev_calibration_promotion.json";cal_path.write_text(json.dumps(calibration,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    oos=validate_oos(trade,train_ratio);oos_path=out/"oos_validation.json";oos_path.write_text(json.dumps(oos,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    wf=validate_wf(trade,min_train,test_size);wf_path=out/"walk_forward.json";wf_path.write_text(json.dumps(wf,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    keys=sorted(set(calibration["groups"])|set(oos["oos"]["groups"])|set(wf["stability"]))
    gate={"schema_version":1,"policy":"fixed_conservative_v0.1","direct_live_promotion":False,
      "research_only":True,"auto_execute":False,
      "results":[evaluate(k,calibration,oos,wf) for k in keys]}
    gate_path=out/"promotion_gate.json";gate_path.write_text(json.dumps(gate,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest={"receipt":str(receipt),"trade_results":str(trade),"feature_ev":str(feature_ev),
      "source_manifest":str(source_manifest),"calibration":str(cal_path),"oos":str(oos_path),
      "walk_forward":str(wf_path),"promotion_gate":str(gate_path),
      "eligible_trade_count":len(eligible_rows(trade)),"research_only":True,"auto_execute":False}
    mp=out/"full_research_manifest.json";mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return mp,manifest

def main():
    ap=argparse.ArgumentParser();ap.add_argument("payload");ap.add_argument("--out-dir",default="data/claude_full_research")
    ap.add_argument("--cost-pct",type=float,default=.10);ap.add_argument("--prev-close",type=float)
    ap.add_argument("--train-ratio",type=float,default=.70);ap.add_argument("--min-train",type=int,default=30);ap.add_argument("--test-size",type=int,default=10)
    a=ap.parse_args();mp,m=run(a.payload,a.out_dir,a.cost_pct,a.prev_close,a.train_ratio,a.min_train,a.test_size)
    print(json.dumps({"manifest":str(mp),**m},ensure_ascii=False))
if __name__=="__main__":main()
