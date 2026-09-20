#!/usr/bin/env python3
"""Build mobile approvals by joining signals with empirical EV calibration."""
from __future__ import annotations
import argparse,json
from datetime import datetime,timezone
from pathlib import Path

def load(path,default=None):
    try:
        with Path(path).open("r",encoding="utf-8-sig") as f:return json.load(f)
    except FileNotFoundError:return default if default is not None else {}

def strategy_key(s):
    # Explicit key wins. Never guess a strategy from a numeric score.
    return s.get("strategy_key") or s.get("setup_key")

def build(signals,cal,limit=10):
    groups=cal.get("groups") or {}; out=[]
    for i,s in enumerate((signals.get("prepared") or [])[:limit],1):
        code=str(s.get("code") or s.get("ticker") or "-").replace(".T","")
        key=strategy_key(s); ev=groups.get(key) if key else None
        passed=bool(ev and ev.get("risk_gate")=="PASS")
        raw_action=str(s.get("action") or s.get("side") or "WAIT").upper()
        action=raw_action if passed and raw_action in {"LONG","SHORT","EXIT"} else "WAIT"
        reason=(s.get("reason") or s.get("setup") or "")
        if not key: risk_reason="STRATEGY_KEY_MISSING"
        elif not ev: risk_reason="EMPIRICAL_EV_NOT_AVAILABLE"
        else: risk_reason=ev.get("risk_reason","BLOCKED")
        out.append({
          "request_id":f"SIG-{s.get('signal_date','NA')}-{code}-{i:02d}",
          "request_type":"trade","symbol":code,"name":s.get("name",""),"action":action,
          "proposed_action":raw_action,"strategy_key":key,
          "ev_score":ev.get("ev_score") if ev else None,
          "technical_score":s.get("technical_score",s.get("score")),
          "sample_size":ev.get("sample_size") if ev else None,
          "win_rate":ev.get("win_rate") if ev else None,
          "profit_factor":ev.get("profit_factor") if ev else None,
          "avg_pl_pct":ev.get("avg_pl_pct") if ev else None,
          "max_dd_pct":ev.get("max_dd_pct") if ev else None,
          "trigger_summary":reason,"source_signal_date":s.get("signal_date"),
          "source_updated_at":signals.get("updated_at"),"data_freshness_sec":s.get("data_freshness_sec"),
          "risk_gate":"PASS" if passed else "BLOCK","risk_reason":"OK" if passed else risk_reason,
          "status":"pending","expires_in_sec":int(s.get("expires_in_sec") or (300 if passed else 0)),
          "paper_only":True,"trigger_price":s.get("trigger"),"stop_price":s.get("stop"),
          "target1":s.get("target1"),"target2":s.get("target2")
        })
    return {"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"paper",
      "source":"signals + empirical EV calibration","score_is_probability":False,"requests":out}

def main():
    p=argparse.ArgumentParser();p.add_argument("--input",default="signals.json");p.add_argument("--ev",default="data/ev_calibration.json");p.add_argument("--output",default="data/mobile_approval_requests.json");p.add_argument("--limit",type=int,default=10);a=p.parse_args()
    payload=build(load(a.input,{}),load(a.ev,{}),a.limit);dst=Path(a.output);dst.parent.mkdir(parents=True,exist_ok=True);dst.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"wrote {len(payload['requests'])} requests; PASS={sum(x['risk_gate']=='PASS' for x in payload['requests'])}")
if __name__=="__main__":main()
