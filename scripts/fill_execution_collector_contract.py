"""Contract for a private independent execution-evidence collector.

This module defines the handoff only. It performs no broker/MS2 I/O, no order
submission, and never derives an execution outcome from market ticks/snapshots.
"""
from __future__ import annotations
from datetime import datetime
import math

ALLOWED_SOURCES=frozenset({"BROKER_EXECUTION_EXPORT","MANUAL_VERIFIED_EXECUTION"})
FORBIDDEN_DERIVED_SOURCES=frozenset({"MS2_TICKS","MS2_MARKET_SNAPSHOT","MS2_EXECUTION_OBSERVATION","SHADOW_FILL_MODEL"})

def _aware(x): return isinstance(x,datetime) and x.tzinfo is not None and x.utcoffset() is not None
def _text(x): return isinstance(x,str) and bool(x.strip())
def _qty(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>=0 and int(x)==x

def validate_collector_input(record:dict) -> list[str]:
    reasons=[]
    if not isinstance(record,dict): return ["COLLECTOR_RECORD_INVALID"]
    source=record.get("observation_source")
    if source not in ALLOWED_SOURCES: reasons.append("COLLECTOR_SOURCE_NOT_INDEPENDENT")
    for f in ("shadow_order_id","evidence_ref"):
        if not _text(record.get(f)): reasons.append("COLLECTOR_FIELD_MISSING_"+f.upper())
    if not _aware(record.get("observed_at")): reasons.append("COLLECTOR_OBSERVED_AT_INVALID")
    if not _qty(record.get("observed_fill_qty")): reasons.append("COLLECTOR_FILL_QTY_INVALID")
    price=record.get("observed_fill_price")
    if price is not None and (not isinstance(price,(int,float)) or isinstance(price,bool) or not math.isfinite(price) or price<=0):
        reasons.append("COLLECTOR_FILL_PRICE_INVALID")
    if source=="MANUAL_VERIFIED_EXECUTION" and not _text(record.get("verified_by")):
        reasons.append("COLLECTOR_VERIFIER_REQUIRED")
    if source=="BROKER_EXECUTION_EXPORT" and not _text(record.get("broker_execution_id")):
        reasons.append("COLLECTOR_BROKER_EXECUTION_ID_REQUIRED")
    return reasons
