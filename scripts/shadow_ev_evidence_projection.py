"""Evidence-first PAPER roundtrip projection (pure functions).

This is NOT an execution engine. The shadow fill model's "PROBABLE"/"CERTAIN"
estimates do not become OBSERVED executions here. Only separately witnessed
entry/exit fills, verified costs and joined strategy identity can be projected.
No IO, real orders, telemetry or account fields are accepted.
"""
from datetime import datetime
import math

def _ts(raw):
    if not isinstance(raw,str):
        return None
    try:
        dt=datetime.fromisoformat(raw)
    except (ValueError,TypeError,OverflowError):
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt

def _positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0

def _id(value):
    return isinstance(value,str) and bool(value.strip())

def project(intent,entry,exit_,cost):
    """Yield (eligible-paper-record, reason). Never silently repair evidence."""
    if not all(isinstance(x,dict) for x in (intent,entry,exit_,cost)):
        return None,"EVIDENCE_TYPE_INVALID"
    if any("account" in str(k).lower() or "broker" in str(k).lower() or "credential" in str(k).lower() for x in (intent,entry,exit_,cost) for k in x):
        return None,"PRIVATE_FIELD_REJECTED"
    strategy=intent.get("strategy_id")
    if not _id(strategy) or not _id(intent.get("intent_hash")) or not _id(intent.get("symbol")):
        return None,"INTENT_IDENTITY_MISSING"
    side=intent.get("side")
    if side not in ("BUY","SELL"):
        return None,"INTENT_SIDE_INVALID"
    if any(x.get("intent_hash")!=intent["intent_hash"] or x.get("strategy_id")!=strategy for x in (entry,exit_)):
        return None,"LINEAGE_MISMATCH"
    if entry.get("event_type")!="ENTRY_FILL" or exit_.get("event_type")!="EXIT_FILL":
        return None,"FILL_EVENT_TYPE_INVALID"
    if any(x.get("evidence_source")!="INDEPENDENT_OBSERVED_FILL" for x in (entry,exit_)):
        return None,"INDEPENDENT_FILL_EVIDENCE_MISSING"
    if any(not _id(x.get("fill_id")) or not _positive(x.get("fill_price")) or not _positive(x.get("filled_qty")) for x in (entry,exit_)):
        return None,"FILL_DATA_MISSING"
    if entry["fill_id"]==exit_["fill_id"]:
        return None,"FILL_ID_COLLISION"
    if any(x.get("fill_confidence") in ("PROBABLE","UNCERTAIN","UNOBSERVABLE") or x.get("slippage_model_status")=="NOT_MODELED_V0_1" for x in (entry,exit_)):
        return None,"ESTIMATED_FILL_REJECTED"
    if entry["filled_qty"]!=exit_["filled_qty"] or int(entry["filled_qty"])!=entry["filled_qty"]:
        return None,"UNMATCHED_FILLED_QTY"
    first=_ts(entry.get("observed_at"));last=_ts(exit_.get("observed_at"))
    if first is None or last is None or not first<last:
        return None,"FILL_TIME_INVALID"
    if cost.get("cost_model_status")!="VERIFIED" or cost.get("intent_hash")!=intent["intent_hash"]:
        return None,"COST_EVIDENCE_NOT_VERIFIED"
    cost_pct=cost.get("cost_pct")
    if type(cost_pct) not in (int,float) or not math.isfinite(cost_pct) or cost_pct<0:
        return None,"COST_VALUE_MISSING"
    # This record is research-only, never evidence of *real* broker P&L.
    return {
        "strategy_id":strategy,"strategy_key":strategy,
        "ticker":intent["symbol"],"side":"LONG" if side=="BUY" else "SHORT",
        "triggered":True,"execution_type":"PAPER_OBSERVED",
        "fill_evidence":{
            "entry_fill_id":entry["fill_id"],"exit_fill_id":exit_["fill_id"],
            "entry_source":"OBSERVED","exit_source":"OBSERVED"
        },
        "entry_fill_price":entry["fill_price"],"exit_fill_price":exit_["fill_price"],
        "entry_ts":first.isoformat(),"exit_ts":last.isoformat(),
        "cost_pct":cost_pct,"cost_model_status":"VERIFIED",
        "real_submit_allowed":False,
    },None
