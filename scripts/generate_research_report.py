#!/usr/bin/env python3
import argparse,json
from pathlib import Path
def evidence_label(g):
    n=int(g.get("sample_size",0))
    if n<30:return "REFERENCE_ONLY"
    if g.get("risk_gate")=="PASS":return "INITIAL_EVIDENCE"
    return "NO_EMPIRICAL_EDGE"
def render(data):
    rows=data.get("feature_groups",data.get("groups",[]))
    out=["# AI Cockpit Research Report","","Research only. EV score is not a probability. No bucket is a live trading rule.","","| Strategy | Feature | Bucket | N | Win | Avg P/L % | PF | Max DD % | Evidence |","|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for g in rows:
        out.append("| {strategy_key} | {feature} | {bucket} | {sample_size} | {win:.1%} | {avg:.4f} | {pf:.3f} | {dd:.4f} | {evidence} |".format(strategy_key=g.get("strategy_key",""),feature=g.get("feature",""),bucket=g.get("bucket",""),sample_size=g.get("sample_size",0),win=float(g.get("win_rate",0)),avg=float(g.get("avg_pl_pct",0)),pf=float(g.get("profit_factor",0)),dd=float(g.get("max_dd_pct",0)),evidence=evidence_label(g)))
    out += ["","## Interpretation guardrails","- REFERENCE_ONLY: N < 30. Do not promote to a trading condition.","- INITIAL_EVIDENCE: minimum sample and current empirical gate passed; still requires walk-forward/OOS validation.","- NO_EMPIRICAL_EDGE: sufficient sample but current empirical gate did not pass.","- Fixed buckets are descriptive and must not be re-cut after seeing results merely to improve performance."]
    return "\n".join(out)+"\n"
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="data/research_run/ev_feature_buckets.json");ap.add_argument("--output",default="data/research_run/REPORT.md");a=ap.parse_args()
    data=json.loads(Path(a.input).read_text(encoding="utf-8"));Path(a.output).write_text(render(data),encoding="utf-8")
if __name__=="__main__":main()
