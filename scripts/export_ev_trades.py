#!/usr/bin/env python3
"""Export only evidenced, complete PAPER round trips for EV research.

Legacy closing marks, speculative fills, missing costs, missing timestamps and
ambiguous strategy labels remain excluded. No order or broker access.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime
import json
import math
from pathlib import Path

FIELDS=["strategy_key","gross_pnl_pct","cost_pct","net_pnl_pct","pnl_pct","symbol","side","entry_ts","exit_ts"]
REQUIRED_EVIDENCE=("entry_fill_id","exit_fill_id","entry_source","exit_source")


def _positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


def _timestamp(value):
    if not isinstance(value,str) or not value.strip():
        return None
    try:
        ts=datetime.fromisoformat(value)
        return ts if ts.tzinfo is not None and ts.utcoffset() is not None else None
    except (TypeError,ValueError,OverflowError):
        return None


def review(record):
    """Return (CSV row, failure code); fail closed without inferred backfills."""
    if not isinstance(record,dict):
        return None,"INVALID_RECORD"
    if record.get("triggered") is not True:
        return None,"NOT_TRIGGERED"
    key=record.get("strategy_key")
    if not isinstance(key,str) or not key.strip():
        return None,"STRATEGY_KEY_MISSING"
    if record.get("strategy_id") and record["strategy_id"]!=key:
        return None,"STRATEGY_ID_DISAGREEMENT"
    if record.get("execution_type")!="PAPER_OBSERVED":
        return None,"EXECUTION_PROVENANCE_MISSING"
    evidence=record.get("fill_evidence")
    if not isinstance(evidence,dict) or any(
        not isinstance(evidence.get(k),str) or not evidence[k].strip()
        for k in REQUIRED_EVIDENCE
    ):
        return None,"FILL_EVIDENCE_MISSING"
    if evidence["entry_source"]!="OBSERVED" or evidence["exit_source"]!="OBSERVED":
        return None,"FILL_NOT_OBSERVED"
    if evidence["entry_fill_id"]==evidence["exit_fill_id"]:
        return None,"FILL_ID_COLLISION"
    entry=record.get("entry_fill_price")
    exit_price=record.get("exit_fill_price")
    if not _positive(entry) or not _positive(exit_price):
        return None,"EXECUTED_PRICE_MISSING"
    start=_timestamp(record.get("entry_ts"))
    end=_timestamp(record.get("exit_ts"))
    if start is None or end is None or end<=start:
        return None,"EXECUTION_TIME_INVALID"
    cost=record.get("cost_pct")
    if type(cost) not in (int,float) or not math.isfinite(cost) or cost<0:
        return None,"EXPLICIT_COST_MISSING"
    if record.get("cost_model_status")!="VERIFIED":
        return None,"COST_UNVERIFIED"
    side=str(record.get("side") or "").upper()
    if side not in ("LONG","SHORT"):
        return None,"SIDE_INVALID"
    symbol=record.get("ticker")
    if not isinstance(symbol,str) or not symbol.strip():
        return None,"SYMBOL_MISSING"
    gross=(exit_price-entry)/entry*100*(1 if side=="LONG" else -1)
    net=gross-cost
    if not all(math.isfinite(v) for v in (gross,net)):
        return None,"PNL_NONFINITE"
    return {
        "strategy_key":key.strip(),"gross_pnl_pct":round(gross,6),
        "cost_pct":cost,"net_pnl_pct":round(net,6),"pnl_pct":round(net,6),
        "symbol":symbol.replace(".T",""),"side":side,
        "entry_ts":start.isoformat(),"exit_ts":end.isoformat()
    },None


def audit(history):
    if not isinstance(history,list):
        raise ValueError("HISTORY_MUST_BE_LIST")
    exported=[]
    reasons=Counter()
    for item in history:
        result,reason=review(item)
        if reason: reasons[reason]+=1
        else: exported.append(result)
    return exported,{
        "schema_version":"ev-eligibility-audit-v1",
        "records_examined":len(history),
        "eligible_records":len(exported),
        "excluded_records":len(history)-len(exported),
        "exclusions":dict(sorted(reasons.items())),
        "execution_lane":"PAPER_OBSERVED_ONLY",
        "real_submit_allowed":False,
        "contains_raw_prices":False
    }


def rows(history):
    return audit(history)[0]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",default="paper_trade_history.json")
    parser.add_argument("--output",default="data/trade_results.csv")
    parser.add_argument("--audit-output",default="data/ev_eligibility_audit.json")
    args=parser.parse_args()
    history=json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    data,report=audit(history)
    dest=Path(args.output)
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS)
        w.writeheader()
        w.writerows(data)
    target=Path(args.audit_output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"EV provenance audit: {report['eligible_records']}/{report['records_examined']} eligible")


if __name__=="__main__":
    main()
