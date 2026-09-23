"""Fail-closed adapter from frozen Shadow prediction + independently verified outcome to C-107 evidence."""
from __future__ import annotations
from datetime import datetime
import math
import fill_execution_evidence as fee

INDEPENDENT_OUTCOME_SOURCES=frozenset({"BROKER_EXECUTION_EXPORT","MANUAL_VERIFIED_EXECUTION"})
MARKET_OBSERVATION_SOURCES=frozenset({"MS2_TICKS","MS2_MARKET_SNAPSHOT","MS2_EXECUTION_OBSERVATION"})
def _aware(x): return isinstance(x,datetime) and x.tzinfo is not None and x.utcoffset() is not None
def _num(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def _qty(x): return _num(x) and int(x)==x and x>=0
def _text(x): return isinstance(x,str) and bool(x.strip())

def build_calibration_record(*, prediction:dict, outcome:dict) -> dict:
    if not isinstance(prediction,dict) or not isinstance(outcome,dict): raise ValueError("prediction/outcome must be dict")
    req=("shadow_order_id","model_version","submitted_at","predicted_at","order_type","side","requested_qty","predicted_fill_qty","trading_unit")
    if any(k not in prediction for k in req): raise ValueError("prediction missing required field")
    source=outcome.get("observation_source")
    if source not in INDEPENDENT_OUTCOME_SOURCES: raise ValueError("outcome source is not independently verified execution")
    if source=="MANUAL_VERIFIED_EXECUTION" and (not _text(outcome.get("verified_by")) or not _text(outcome.get("evidence_ref"))):
        raise ValueError("manual execution requires verifier and evidence reference")
    if source=="BROKER_EXECUTION_EXPORT" and not _text(outcome.get("evidence_ref")):
        raise ValueError("broker execution export requires evidence reference")
    if outcome.get("shadow_order_id") != prediction["shadow_order_id"]: raise ValueError("outcome order identity mismatch")
    evidence_reasons=fee.validate_execution_evidence(outcome.get("evidence_meta"),shadow_order_id=prediction["shadow_order_id"],observation_source=source)
    if evidence_reasons: raise ValueError("invalid execution evidence metadata: "+",".join(evidence_reasons))
    observed_at=outcome.get("observed_at")
    if not all(_aware(prediction[k]) for k in ("submitted_at","predicted_at")) or not _aware(observed_at): raise ValueError("timestamps must be timezone-aware")
    if not prediction["submitted_at"] <= prediction["predicted_at"] < observed_at: raise ValueError("invalid prediction/outcome chronology")
    requested=prediction["requested_qty"];pred_qty=prediction["predicted_fill_qty"];obs_qty=outcome.get("observed_fill_qty");unit=prediction["trading_unit"]
    if not _qty(requested) or requested<=0 or not _qty(pred_qty) or not _qty(obs_qty) or not _qty(unit) or unit<=0 or pred_qty>requested or obs_qty>requested: raise ValueError("invalid quantities")
    if requested%unit or pred_qty%unit or obs_qty%unit: raise ValueError("quantity is not aligned to trading_unit")
    if prediction["order_type"] not in ("MARKET","LIMIT") or prediction["side"] not in ("BUY","SELL"): raise ValueError("invalid order dimensions")
    r={k:prediction[k] for k in req if k!="trading_unit"};r["observed_at"]=observed_at;r["observed_fill_qty"]=int(obs_qty)
    context=("spread_yen","tick_size","visible_qty","visible_qty_side","market_regime");present=[k for k in context if k in prediction]
    if present:
        if "context_observed_at" not in prediction or prediction.get("context_freshness")!="OK": raise ValueError("context provenance incomplete")
        if not _aware(prediction["context_observed_at"]) or not prediction["submitted_at"]<=prediction["context_observed_at"]<=prediction["predicted_at"]: raise ValueError("context chronology invalid")
        for k in present:r[k]=prediction[k]
        r["context_observed_at"]=prediction["context_observed_at"];r["context_freshness"]="OK"
    pp=prediction.get("predicted_fill_price");op=outcome.get("observed_fill_price")
    if (pp is None)!=(op is None): raise ValueError("price evidence must be paired")
    if pp is not None:
        if not _num(pp) or not _num(op) or pp<=0 or op<=0 or pred_qty<=0 or obs_qty<=0: raise ValueError("invalid price evidence")
        r["predicted_fill_price"]=pp;r["observed_fill_price"]=op
    return r
