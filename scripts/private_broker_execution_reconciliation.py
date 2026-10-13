"""Read-only exact reconciliation policy for private REAL execution records.

Never ingests broker credentials, writes private logs, exports data to public CI,
or changes a ledger's reconciliation_status. A caller must validate its source
file and independent evidence with the private provenance mechanism separately.
"""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import math

def _num(v,positive=False):
    if type(v) not in (int,float,str) or isinstance(v,bool):
        return None
    try:
        n=Decimal(str(v))
    except InvalidOperation:
        return None
    if not n.is_finite() or n<0 or (positive and n==0):
        return None
    return n

def _time(v):
    if not isinstance(v,str):
        return None
    try:
        dt=datetime.fromisoformat(v.replace(" ","T"))
    except (ValueError,TypeError):
        return None
    # Never infer a timezone on legacy naive manually-entered rows.
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None and dt.utcoffset() is not None else None

def match_real_execution(local,broker,*,verified_source=False):
    """Return a status and error codes, never data or automatic promotion."""
    errors=[]
    if not isinstance(local,dict) or not isinstance(broker,dict):
        return {"status":"BLOCKED","reasons":["INVALID_RECORD"],"real_submit_allowed":False}
    if local.get("reconciliation_status") not in (None,"未照合"):
        errors.append("LOCAL_ALREADY_RECONCILED_OR_INVALID")
    # The ingestion caller must independently establish the broker-file origin
    # from non-user-overridable retained private evidence. A JSON string is not proof.
    if verified_source is not True or broker.get("observation_source")!="BROKER_EXECUTION_EXPORT":
        errors.append("INDEPENDENT_BROKER_SOURCE_UNVERIFIED")
    for key in ("execution_id","order_id","ticker","side"):
        a,b=local.get(key),broker.get(key)
        if not isinstance(a,str) or not a.strip() or not isinstance(b,str) or a!=b:
            errors.append("MISMATCH_"+key.upper())
    for key,broker_key in (("price","price"),("quantity","quantity"),("fee","fee")):
        a,b=_num(local.get(key),key!="fee"),_num(broker.get(broker_key),key!="fee")
        if a is None or b is None or a!=b:
            errors.append("MISMATCH_"+key.upper())
    a,b=_time(local.get("executed_at")),_time(broker.get("executed_at"))
    if a is None or b is None or a!=b:
        errors.append("EXECUTED_AT_UNVERIFIABLE_OR_MISMATCH")
    # Joining execution to a strategy is a separate provenance problem. Require
    # explicit identical decision snapshots before considering it usable as EV.
    strategy_link=(isinstance(local.get("decision_snapshot_id"),str)
                   and bool(local["decision_snapshot_id"].strip())
                   and local["decision_snapshot_id"]==broker.get("decision_snapshot_id"))
    if not strategy_link:
        errors.append("DECISION_PROVENANCE_MISSING")
    return {"status":"MATCH_CANDIDATE_ONLY" if not errors else "BLOCKED",
            "reasons":errors,
            "automatic_reconciliation_allowed":False,
            "ev_training_allowed":False,
            "real_submit_allowed":False}
