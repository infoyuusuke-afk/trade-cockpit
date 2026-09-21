#!/usr/bin/env python3
"""Research-to-candidate promotion gate. Never promotes directly to LIVE."""
import argparse,json
from pathlib import Path

MIN_N=30
MIN_PF=1.10
MIN_AVG_PL=0.0
MAX_DD_FLOOR=-10.0
MIN_OOS_N=10
MIN_WF_FOLDS=2
MIN_WF_EDGE_RATE=0.60

def evaluate(strategy_key, calibration, oos, wf):
    reasons=[]
    base=calibration.get("groups",{}).get(strategy_key)
    og=oos.get("oos",{}).get("groups",{}).get(strategy_key)
    stab=wf.get("stability",{}).get(strategy_key)
    if not base: reasons.append("BASE_EVIDENCE_MISSING")
    else:
        if base.get("sample_size",0)<MIN_N: reasons.append("BASE_SAMPLE_LOW")
        if base.get("profit_factor",0)<MIN_PF: reasons.append("BASE_PF_LOW")
        if base.get("avg_pl_pct",0)<=MIN_AVG_PL: reasons.append("BASE_AVG_PL_NON_POSITIVE")
        if base.get("max_dd_pct",0)<MAX_DD_FLOOR: reasons.append("BASE_DD_EXCESSIVE")
    if not og: reasons.append("OOS_EVIDENCE_MISSING")
    else:
        if og.get("sample_size",0)<MIN_OOS_N: reasons.append("OOS_SAMPLE_LOW")
        if og.get("profit_factor",0)<MIN_PF: reasons.append("OOS_PF_LOW")
        if og.get("avg_pl_pct",0)<=MIN_AVG_PL: reasons.append("OOS_AVG_PL_NON_POSITIVE")
    if not stab: reasons.append("WF_EVIDENCE_MISSING")
    else:
        if stab.get("oos_folds",0)<MIN_WF_FOLDS: reasons.append("WF_FOLDS_LOW")
        if stab.get("positive_edge_fold_rate",0)<MIN_WF_EDGE_RATE: reasons.append("WF_STABILITY_LOW")
    return {"strategy_key":strategy_key,"status":"CANDIDATE" if not reasons else "RESEARCH",
      "live_eligible":False,"reasons":reasons or ["INITIAL_EVIDENCE_ONLY_MANUAL_REVIEW_REQUIRED"]}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--calibration",default="data/ev_calibration.json");ap.add_argument("--oos",default="data/research_run/oos_validation.json");ap.add_argument("--walk-forward",default="data/research_run/walk_forward.json");ap.add_argument("--output",default="data/research_run/promotion_gate.json");a=ap.parse_args()
    cal=json.loads(Path(a.calibration).read_text());oos=json.loads(Path(a.oos).read_text());wf=json.loads(Path(a.walk_forward).read_text())
    keys=sorted(set(cal.get("groups",{}))|set(oos.get("oos",{}).get("groups",{}))|set(wf.get("stability",{})))
    out={"schema_version":1,"policy":"fixed_conservative_v0.1","direct_live_promotion":False,"results":[evaluate(k,cal,oos,wf) for k in keys]}
    Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
