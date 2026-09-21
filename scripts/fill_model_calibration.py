"""Pure calibration diagnostics for Shadow Fill Model evidence.

No I/O, no broker access, no parameter fitting. Actual MS2 evidence stays private.
"""
from __future__ import annotations
from datetime import datetime
import math

SCHEMA_VERSION="fill-model-calibration-0.1"
MIN_SAMPLE=50
REQUIRED=("model_version","observed_at","order_type","side","requested_qty","predicted_fill_qty","observed_fill_qty")
def _num(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def _aware(x): return isinstance(x,datetime) and x.tzinfo is not None and x.utcoffset() is not None
def evaluate(records):
    if not isinstance(records,list): raise ValueError("records must be list")
    valid=[]; invalid=0
    for r in records:
        if not isinstance(r,dict) or any(k not in r for k in REQUIRED): invalid+=1; continue
        if not _aware(r["observed_at"]) or r["order_type"] not in ("MARKET","LIMIT") or r["side"] not in ("BUY","SELL"): invalid+=1; continue
        nums=(r["requested_qty"],r["predicted_fill_qty"],r["observed_fill_qty"])
        if not all(_num(x) and int(x)==x and x>=0 for x in nums) or r["requested_qty"]<=0: invalid+=1; continue
        if r["predicted_fill_qty"]>r["requested_qty"] or r["observed_fill_qty"]>r["requested_qty"]: invalid+=1; continue
        valid.append(r)
    n=len(valid)
    pred_rate=sum(1 for r in valid if r["predicted_fill_qty"]>0)/n if n else None
    obs_rate=sum(1 for r in valid if r["observed_fill_qty"]>0)/n if n else None
    qty_mae=sum(abs(r["predicted_fill_qty"]-r["observed_fill_qty"]) for r in valid)/n if n else None
    price_pairs=[r for r in valid if _num(r.get("predicted_fill_price")) and _num(r.get("observed_fill_price")) and r["predicted_fill_price"]>0 and r["observed_fill_price"]>0]
    price_mae=(sum(abs(r["predicted_fill_price"]-r["observed_fill_price"]) for r in price_pairs)/len(price_pairs)) if price_pairs else None
    return {"schema_version":SCHEMA_VERSION,"status":"CALIBRATION_REVIEW_ELIGIBLE" if n>=MIN_SAMPLE else "INSUFFICIENT_SAMPLE","minimum_sample":MIN_SAMPLE,"sample_size":n,"invalid_record_n":invalid,"predicted_fill_rate":pred_rate,"observed_fill_rate":obs_rate,"fill_rate_bias":(pred_rate-obs_rate) if n else None,"fill_qty_mae":qty_mae,"fill_price_mae_yen":price_mae,"price_pair_n":len(price_pairs),"parameter_update_allowed":False,"real_submit_allowed":False}
