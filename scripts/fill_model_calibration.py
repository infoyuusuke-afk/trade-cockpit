"""Pure calibration diagnostics for Shadow Fill Model evidence.

No I/O, no broker access, no parameter fitting. Actual MS2 evidence stays private.
"""
from __future__ import annotations
from datetime import datetime
import math

SCHEMA_VERSION="fill-model-calibration-0.1"
MIN_SAMPLE=50
MIN_SESSION_DAYS=5
REQUIRED=("shadow_order_id","model_version","observed_at","order_type","side","requested_qty","predicted_fill_qty","observed_fill_qty")
OPTIONAL_CONTEXT=("spread_yen","visible_qty","tick_size")
VALID_REGIMES=("TREND_UP","TREND_DOWN","RANGE","HIGH_VOL","UNKNOWN")
def _num(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def _aware(x): return isinstance(x,datetime) and x.tzinfo is not None and x.utcoffset() is not None
def evaluate(records):
    if not isinstance(records,list): raise ValueError("records must be list")
    valid=[]; invalid=0; duplicate_record_n=0; conflicting_duplicate_n=0; seen_order_records={}
    for r in records:
        if not isinstance(r,dict) or any(k not in r for k in REQUIRED): invalid+=1; continue
        if not isinstance(r["shadow_order_id"],str) or not r["shadow_order_id"].strip(): invalid+=1; continue
        if r["shadow_order_id"] in seen_order_records:
            prior=seen_order_records[r["shadow_order_id"]]
            comparable={k:r.get(k) for k in REQUIRED if k!="observed_at"} | {"observed_at":r["observed_at"]}
            if comparable != prior: conflicting_duplicate_n+=1
            else: duplicate_record_n+=1
            continue
        if not _aware(r["observed_at"]) or r["order_type"] not in ("MARKET","LIMIT") or r["side"] not in ("BUY","SELL"): invalid+=1; continue
        nums=(r["requested_qty"],r["predicted_fill_qty"],r["observed_fill_qty"])
        if not all(_num(x) and int(x)==x and x>=0 for x in nums) or r["requested_qty"]<=0: invalid+=1; continue
        if r["predicted_fill_qty"]>r["requested_qty"] or r["observed_fill_qty"]>r["requested_qty"]: invalid+=1; continue
        if any(k in r and (not _num(r[k]) or r[k] < 0) for k in OPTIONAL_CONTEXT): invalid+=1; continue
        if "market_regime" in r and r["market_regime"] not in VALID_REGIMES: invalid+=1; continue
        seen_order_records[r["shadow_order_id"]]={k:r.get(k) for k in REQUIRED if k!="observed_at"} | {"observed_at":r["observed_at"]}
        valid.append(r)
    n=len(valid)
    session_days=sorted({r["observed_at"].date().isoformat() for r in valid})
    pred_rate=sum(1 for r in valid if r["predicted_fill_qty"]>0)/n if n else None
    obs_rate=sum(1 for r in valid if r["observed_fill_qty"]>0)/n if n else None
    qty_mae=sum(abs(r["predicted_fill_qty"]-r["observed_fill_qty"]) for r in valid)/n if n else None
    price_pairs=[r for r in valid if _num(r.get("predicted_fill_price")) and _num(r.get("observed_fill_price")) and r["predicted_fill_price"]>0 and r["observed_fill_price"]>0]
    price_mae=(sum(abs(r["predicted_fill_price"]-r["observed_fill_price"]) for r in price_pairs)/len(price_pairs)) if price_pairs else None
    def bucket(r):
        spread=r.get("spread_yen"); tick=r.get("tick_size"); visible=r.get("visible_qty")
        spread_ticks=(spread/tick) if _num(spread) and _num(tick) and tick>0 else None
        spread_bucket="SPREAD_UNKNOWN" if spread_ticks is None else ("SPREAD_1T" if spread_ticks<=1 else ("SPREAD_2_3T" if spread_ticks<=3 else "SPREAD_4P_T"))
        liquidity_ratio=(visible/r["requested_qty"]) if _num(visible) else None
        liq_bucket="LIQ_UNKNOWN" if liquidity_ratio is None else ("LIQ_LT1X" if liquidity_ratio<1 else ("LIQ_1_3X" if liquidity_ratio<3 else "LIQ_3P_X"))
        h=r["observed_at"].hour; time_bucket="OPEN_0900_0930" if h==9 and r["observed_at"].minute<30 else ("CLOSE_1430_1530" if (h==14 and r["observed_at"].minute>=30) or h==15 else "MID_SESSION")
        regime=r.get("market_regime","UNKNOWN")
        return spread_bucket,liq_bucket,time_bucket,regime
    strata={}
    context_strata={}
    for key in sorted({(r["model_version"],r["order_type"],r["side"]) for r in valid}):
        rows=[r for r in valid if (r["model_version"],r["order_type"],r["side"])==key]
        sn=len(rows); pr=sum(1 for r in rows if r["predicted_fill_qty"]>0)/sn; orate=sum(1 for r in rows if r["observed_fill_qty"]>0)/sn
        strata["|".join(key)]={"sample_size":sn,"status":"CALIBRATION_REVIEW_ELIGIBLE" if sn>=MIN_SAMPLE else "INSUFFICIENT_SAMPLE","fill_rate_bias":pr-orate,"fill_qty_mae":sum(abs(r["predicted_fill_qty"]-r["observed_fill_qty"]) for r in rows)/sn}
    for key in sorted({(r["model_version"],r["order_type"],r["side"],*bucket(r)) for r in valid}):
        rows=[r for r in valid if (r["model_version"],r["order_type"],r["side"],*bucket(r))==key]; sn=len(rows)
        context_strata["|".join(key)]={"sample_size":sn,"status":"CALIBRATION_REVIEW_ELIGIBLE" if sn>=MIN_SAMPLE else "INSUFFICIENT_SAMPLE","fill_qty_mae":sum(abs(r["predicted_fill_qty"]-r["observed_fill_qty"]) for r in rows)/sn}
    required_base=[f"{mv}|{ot}|{side}" for mv in sorted({r["model_version"] for r in valid}) for ot in ("MARKET","LIMIT") for side in ("BUY","SELL")]
    missing_base=[k for k in required_base if k not in strata or strata[k]["status"]!="CALIBRATION_REVIEW_ELIGIBLE"]
    day_coverage_status="DAY_COVERAGE_SUFFICIENT" if len(session_days)>=MIN_SESSION_DAYS else "DAY_COVERAGE_INSUFFICIENT"
    known_regime_n=sum(1 for r in valid if r.get("market_regime","UNKNOWN")!="UNKNOWN")
    regime_diagnostic_status="REGIME_CONTEXT_AVAILABLE" if known_regime_n else "REGIME_CONTEXT_UNKNOWN"
    coverage_status="COVERAGE_SUFFICIENT" if required_base and not missing_base and day_coverage_status=="DAY_COVERAGE_SUFFICIENT" else "COVERAGE_INSUFFICIENT"
    return {"schema_version":SCHEMA_VERSION,"strata":strata,"context_strata":context_strata,"coverage_status":coverage_status,"required_base_strata":required_base,"insufficient_base_strata":missing_base,"minimum_session_days":MIN_SESSION_DAYS,"unique_session_days":len(session_days),"session_days":session_days,"day_coverage_status":day_coverage_status,"regime_diagnostic_status":regime_diagnostic_status,"known_regime_n":known_regime_n,"status":"CALIBRATION_REVIEW_ELIGIBLE" if n>=MIN_SAMPLE else "INSUFFICIENT_SAMPLE","minimum_sample":MIN_SAMPLE,"sample_size":n,"invalid_record_n":invalid,"duplicate_record_n":duplicate_record_n,"conflicting_duplicate_n":conflicting_duplicate_n,"evidence_integrity_status":"CONFLICTING_DUPLICATE" if conflicting_duplicate_n else "OK","predicted_fill_rate":pred_rate,"observed_fill_rate":obs_rate,"fill_rate_bias":(pred_rate-obs_rate) if n else None,"fill_qty_mae":qty_mae,"fill_price_mae_yen":price_mae,"price_pair_n":len(price_pairs),"parameter_update_allowed":False,"real_submit_allowed":False}
