"""Pure calibration diagnostics for Shadow Fill Model evidence.

``submitted_at`` is the shadow-order time, ``predicted_at`` is when the model
output was frozen, and ``observed_at`` is the later outcome-evidence time.
Optional book/regime context is usable only with an explicit, fresh
``context_observed_at`` that is no later than ``predicted_at``.

No I/O, no broker access, no parameter fitting. Actual MS2 evidence stays private.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import math

SCHEMA_VERSION="fill-model-calibration-0.1"
MIN_SAMPLE=50
MIN_SESSION_DAYS=5
MAX_SAFE_INTEGER=9_007_199_254_740_991
REQUIRED=("shadow_order_id","model_version","submitted_at","predicted_at","observed_at","order_type","side","requested_qty","predicted_fill_qty","observed_fill_qty")
OPTIONAL_CONTEXT=("spread_yen","visible_qty","tick_size")
CONTEXT_FIELDS=OPTIONAL_CONTEXT+("visible_qty_side","market_regime")
EVIDENCE_FIELDS=REQUIRED+CONTEXT_FIELDS+("context_observed_at","context_freshness","predicted_fill_price","observed_fill_price")
ALLOWED_FIELDS=frozenset(EVIDENCE_FIELDS)
VALID_VISIBLE_QTY_SIDES=("BID","ASK")
VALID_REGIMES=("TREND_UP","TREND_DOWN","RANGE","HIGH_VOL","UNKNOWN")
JST=timezone(timedelta(hours=9))
def _jst(x): return x.astimezone(JST)
def _num(x):
    if not isinstance(x,(int,float)) or isinstance(x,bool): return False
    try: return math.isfinite(x)
    except (OverflowError,TypeError,ValueError): return False
def _aware(x): return isinstance(x,datetime) and x.tzinfo is not None and x.utcoffset() is not None
def _time_normalizable(x):
    if not _aware(x): return False
    try:
        x.astimezone(timezone.utc); x.astimezone(JST)
        return True
    except (OverflowError,ValueError):
        return False
def _identifier(x, *, stratum_safe=False):
    return isinstance(x,str) and bool(x) and x==x.strip() and (not stratum_safe or "|" not in x)
def _whole_nonnegative(x): return _num(x) and int(x)==x and 0<=x<=MAX_SAFE_INTEGER
def _mean(values):
    values=list(values)
    return math.fsum(x/len(values) for x in values) if values else None
def _spread_ticks(spread,tick):
    if not _num(spread) or not _num(tick) or spread < 0 or tick <= 0: return None
    try: ratio=spread/tick
    except (OverflowError,ZeroDivisionError): return None
    if not _num(ratio): return None
    nearest=round(ratio)
    return nearest if math.isclose(ratio,nearest,rel_tol=0.0,abs_tol=1e-9) else None
def _evidence_signature(r): return tuple((k in r,r.get(k)) for k in EVIDENCE_FIELDS)
def _valid_record(r, now):
    if not isinstance(r,dict) or any(k not in r for k in REQUIRED): return False
    if any(k not in ALLOWED_FIELDS for k in r): return False
    if not _identifier(r["shadow_order_id"]): return False
    if not _identifier(r["model_version"],stratum_safe=True): return False
    if not all(_time_normalizable(r[k]) for k in ("submitted_at","predicted_at","observed_at")): return False
    if not r["submitted_at"] <= r["predicted_at"] < r["observed_at"]: return False
    if now is not None and any(r[k] > now for k in ("submitted_at","predicted_at","observed_at")): return False
    if r["order_type"] not in ("MARKET","LIMIT") or r["side"] not in ("BUY","SELL"): return False
    nums=(r["requested_qty"],r["predicted_fill_qty"],r["observed_fill_qty"])
    if not all(_whole_nonnegative(x) for x in nums) or r["requested_qty"]<=0: return False
    if r["predicted_fill_qty"]>r["requested_qty"] or r["observed_fill_qty"]>r["requested_qty"]: return False
    if any(k in r and (not _num(r[k]) or r[k] < 0) for k in ("spread_yen","tick_size")): return False
    spread_present="spread_yen" in r; tick_present="tick_size" in r
    if spread_present != tick_present or (tick_present and r["tick_size"]<=0): return False
    if tick_present and _spread_ticks(r["spread_yen"],r["tick_size"]) is None: return False
    visible_present="visible_qty" in r; visible_side_present="visible_qty_side" in r
    if visible_present != visible_side_present: return False
    if visible_present:
        if not _whole_nonnegative(r["visible_qty"]) or r["visible_qty_side"] not in VALID_VISIBLE_QTY_SIDES: return False
        expected_visible_side="ASK" if r["side"]=="BUY" else "BID"
        if r["visible_qty_side"] != expected_visible_side: return False
    context_present=any(k in r for k in CONTEXT_FIELDS)
    context_time_present="context_observed_at" in r; context_freshness_present="context_freshness" in r
    if context_present != context_time_present or context_present != context_freshness_present: return False
    if context_present:
        if not _time_normalizable(r["context_observed_at"]): return False
        if not r["submitted_at"] <= r["context_observed_at"] <= r["predicted_at"]: return False
        if r["context_freshness"] != "OK": return False
    predicted_price_present="predicted_fill_price" in r; observed_price_present="observed_fill_price" in r
    if predicted_price_present != observed_price_present: return False
    if predicted_price_present:
        if not _num(r["predicted_fill_price"]) or not _num(r["observed_fill_price"]): return False
        if r["predicted_fill_price"]<=0 or r["observed_fill_price"]<=0: return False
        if r["predicted_fill_qty"]<=0 or r["observed_fill_qty"]<=0: return False
        relative_error_bps=(r["predicted_fill_price"]-r["observed_fill_price"])/r["observed_fill_price"]*10000
        if not _num(relative_error_bps): return False
    if "market_regime" in r and r["market_regime"] not in VALID_REGIMES: return False
    return True
def evaluate(records, *, now=None):
    if not isinstance(records,list): raise ValueError("records must be list")
    if now is not None and not _time_normalizable(now): raise ValueError("now must be timezone-aware and normalizable")
    validated_by_order={}; invalid=0
    for r in records:
        if not _valid_record(r,now): invalid+=1; continue
        validated_by_order.setdefault(r["shadow_order_id"],[]).append(r)
    valid=[]; duplicate_record_n=0; conflicting_duplicate_n=0; conflicting_order_id_n=0
    for order_id in sorted(validated_by_order):
        variants={}
        for r in validated_by_order[order_id]: variants.setdefault(_evidence_signature(r),[]).append(r)
        duplicate_record_n+=sum(len(same)-1 for same in variants.values())
        if len(variants)>1:
            conflicting_duplicate_n+=len(variants)-1
            conflicting_order_id_n+=1
            continue
        valid.append(next(iter(variants.values()))[0])
    valid.sort(key=lambda r:r["shadow_order_id"])
    n=len(valid)
    model_versions=sorted({r["model_version"] for r in valid})
    model_version_status="SINGLE_MODEL_VERSION" if len(model_versions)<=1 else "MIXED_MODEL_VERSIONS"
    session_days=sorted({_jst(r["submitted_at"]).date().isoformat() for r in valid})
    pred_rate=sum(1 for r in valid if r["predicted_fill_qty"]>0)/n if n else None
    obs_rate=sum(1 for r in valid if r["observed_fill_qty"]>0)/n if n else None
    qty_mae=_mean(abs(r["predicted_fill_qty"]-r["observed_fill_qty"]) for r in valid)
    qty_bias=_mean(r["predicted_fill_qty"]-r["observed_fill_qty"] for r in valid)
    predicted_full_n=sum(1 for r in valid if r["predicted_fill_qty"]==r["requested_qty"])
    false_full_n=sum(1 for r in valid if r["predicted_fill_qty"]==r["requested_qty"] and r["observed_fill_qty"]<r["requested_qty"])
    false_full_rate=(false_full_n/predicted_full_n) if predicted_full_n else None
    price_pairs=[r for r in valid if _num(r.get("predicted_fill_price")) and _num(r.get("observed_fill_price")) and r["predicted_fill_price"]>0 and r["observed_fill_price"]>0]
    price_pair_n=len(price_pairs)
    price_evidence_coverage=(price_pair_n/n) if n else None
    price_evidence_status="PRICE_EVIDENCE_AVAILABLE" if price_pair_n else "PRICE_EVIDENCE_UNAVAILABLE"
    price_mae=_mean(abs(r["predicted_fill_price"]-r["observed_fill_price"]) for r in price_pairs)
    price_mae_bps=_mean(abs(r["predicted_fill_price"]-r["observed_fill_price"])/r["observed_fill_price"]*10000 for r in price_pairs)
    price_bias_bps=_mean((r["predicted_fill_price"]-r["observed_fill_price"])/r["observed_fill_price"]*10000 for r in price_pairs)
    adverse_price_bias_bps=_mean(((r["observed_fill_price"]-r["predicted_fill_price"]) if r["side"]=="BUY" else (r["predicted_fill_price"]-r["observed_fill_price"]))/r["observed_fill_price"]*10000 for r in price_pairs)
    def bucket(r):
        spread=r.get("spread_yen"); tick=r.get("tick_size"); visible=r.get("visible_qty")
        spread_ticks=_spread_ticks(spread,tick)
        spread_bucket="SPREAD_UNKNOWN" if spread_ticks is None else ("SPREAD_1T" if spread_ticks<=1 else ("SPREAD_2_3T" if spread_ticks<=3 else "SPREAD_4P_T"))
        liquidity_ratio=(visible/r["requested_qty"]) if _num(visible) else None
        liq_bucket="LIQ_UNKNOWN" if liquidity_ratio is None else ("LIQ_LT1X" if liquidity_ratio<1 else ("LIQ_1_3X" if liquidity_ratio<3 else "LIQ_3P_X"))
        submitted_jst=_jst(r["submitted_at"]); h=submitted_jst.hour; time_bucket="OPEN_0900_0930" if h==9 and submitted_jst.minute<30 else ("CLOSE_1430_1530" if (h==14 and submitted_jst.minute>=30) or (h==15 and submitted_jst.minute<=30) else "MID_SESSION")
        regime=r.get("market_regime","UNKNOWN")
        return spread_bucket,liq_bucket,time_bucket,regime
    strata={}
    context_strata={}
    for key in sorted({(r["model_version"],r["order_type"],r["side"]) for r in valid}):
        rows=[r for r in valid if (r["model_version"],r["order_type"],r["side"])==key]
        sn=len(rows); pr=sum(1 for r in rows if r["predicted_fill_qty"]>0)/sn; orate=sum(1 for r in rows if r["observed_fill_qty"]>0)/sn
        row_session_days=sorted({_jst(r["submitted_at"]).date().isoformat() for r in rows})
        strata["|".join(key)]={"sample_size":sn,"status":"CALIBRATION_REVIEW_ELIGIBLE" if sn>=MIN_SAMPLE else "INSUFFICIENT_SAMPLE","unique_session_days":len(row_session_days),"session_days":row_session_days,"day_coverage_status":"DAY_COVERAGE_SUFFICIENT" if len(row_session_days)>=MIN_SESSION_DAYS else "DAY_COVERAGE_INSUFFICIENT","fill_rate_bias":pr-orate,"fill_qty_mae":_mean(abs(r["predicted_fill_qty"]-r["observed_fill_qty"]) for r in rows),"fill_qty_bias":_mean(r["predicted_fill_qty"]-r["observed_fill_qty"] for r in rows),"false_full_fill_rate":(sum(1 for r in rows if r["predicted_fill_qty"]==r["requested_qty"] and r["observed_fill_qty"]<r["requested_qty"])/sum(1 for r in rows if r["predicted_fill_qty"]==r["requested_qty"])) if any(r["predicted_fill_qty"]==r["requested_qty"] for r in rows) else None}
    for key in sorted({(r["model_version"],r["order_type"],r["side"],*bucket(r)) for r in valid}):
        rows=[r for r in valid if (r["model_version"],r["order_type"],r["side"],*bucket(r))==key]; sn=len(rows)
        context_strata["|".join(key)]={"sample_size":sn,"status":"CALIBRATION_REVIEW_ELIGIBLE" if sn>=MIN_SAMPLE else "INSUFFICIENT_SAMPLE","fill_qty_mae":_mean(abs(r["predicted_fill_qty"]-r["observed_fill_qty"]) for r in rows)}
    required_base=[f"{mv}|{ot}|{side}" for mv in sorted({r["model_version"] for r in valid}) for ot in ("MARKET","LIMIT") for side in ("BUY","SELL")]
    missing_base=[k for k in required_base if k not in strata or strata[k]["status"]!="CALIBRATION_REVIEW_ELIGIBLE"]
    insufficient_base_day_strata=[k for k in required_base if k not in strata or strata[k]["day_coverage_status"]!="DAY_COVERAGE_SUFFICIENT"]
    base_strata_day_coverage_status="BASE_STRATA_DAY_COVERAGE_SUFFICIENT" if required_base and not insufficient_base_day_strata else "BASE_STRATA_DAY_COVERAGE_INSUFFICIENT"
    day_coverage_status="DAY_COVERAGE_SUFFICIENT" if len(session_days)>=MIN_SESSION_DAYS else "DAY_COVERAGE_INSUFFICIENT"
    known_regime_n=sum(1 for r in valid if r.get("market_regime","UNKNOWN")!="UNKNOWN")
    regime_diagnostic_status="REGIME_CONTEXT_AVAILABLE" if known_regime_n else "REGIME_CONTEXT_UNKNOWN"
    context_evidence_n=sum(1 for r in valid if "context_observed_at" in r)
    context_provenance_status="CONTEXT_PROVENANCE_AVAILABLE" if context_evidence_n else "CONTEXT_PROVENANCE_UNAVAILABLE"
    point_in_time_status="AS_OF_BOUND" if now is not None else "AS_OF_REQUIRED"
    evidence_integrity_issues=[]
    if invalid: evidence_integrity_issues.append("INVALID_RECORDS")
    if conflicting_order_id_n: evidence_integrity_issues.append("CONFLICTING_DUPLICATE")
    if model_version_status=="MIXED_MODEL_VERSIONS": evidence_integrity_issues.append("MIXED_MODEL_VERSIONS")
    evidence_integrity_status="OK" if not evidence_integrity_issues else (evidence_integrity_issues[0] if len(evidence_integrity_issues)==1 else "MULTIPLE_EVIDENCE_ISSUES")
    coverage_status="COVERAGE_SUFFICIENT" if required_base and not missing_base and not insufficient_base_day_strata and day_coverage_status=="DAY_COVERAGE_SUFFICIENT" and evidence_integrity_status=="OK" and point_in_time_status=="AS_OF_BOUND" else "COVERAGE_INSUFFICIENT"
    status="EVIDENCE_CONFLICT" if evidence_integrity_status!="OK" else ("AS_OF_REQUIRED" if n>=MIN_SAMPLE and point_in_time_status!="AS_OF_BOUND" else ("CALIBRATION_REVIEW_ELIGIBLE" if n>=MIN_SAMPLE else "INSUFFICIENT_SAMPLE"))
    evaluation_as_of=now.astimezone(timezone.utc).isoformat() if now is not None else None
    return {"schema_version":SCHEMA_VERSION,"model_versions":model_versions,"model_version_status":model_version_status,"strata":strata,"context_strata":context_strata,"coverage_status":coverage_status,"required_base_strata":required_base,"insufficient_base_strata":missing_base,"insufficient_base_day_strata":insufficient_base_day_strata,"base_strata_day_coverage_status":base_strata_day_coverage_status,"minimum_session_days":MIN_SESSION_DAYS,"unique_session_days":len(session_days),"session_days":session_days,"session_day_basis":"SUBMITTED_AT_JST","time_bucket_basis":"SUBMITTED_AT_JST","prediction_time_basis":"EXPLICIT_PREDICTED_AT","day_coverage_status":day_coverage_status,"point_in_time_status":point_in_time_status,"evaluation_as_of":evaluation_as_of,"regime_diagnostic_status":regime_diagnostic_status,"known_regime_n":known_regime_n,"context_evidence_n":context_evidence_n,"context_provenance_status":context_provenance_status,"status":status,"minimum_sample":MIN_SAMPLE,"sample_size":n,"invalid_record_n":invalid,"duplicate_record_n":duplicate_record_n,"conflicting_duplicate_n":conflicting_duplicate_n,"conflicting_order_id_n":conflicting_order_id_n,"evidence_integrity_status":evidence_integrity_status,"evidence_integrity_issues":evidence_integrity_issues,"predicted_fill_rate":pred_rate,"observed_fill_rate":obs_rate,"fill_rate_bias":(pred_rate-obs_rate) if n else None,"fill_qty_mae":qty_mae,"fill_qty_bias":qty_bias,"predicted_full_fill_n":predicted_full_n,"false_full_fill_n":false_full_n,"false_full_fill_rate":false_full_rate,"fill_price_mae_yen":price_mae,"fill_price_mae_bps":price_mae_bps,"fill_price_bias_bps":price_bias_bps,"adverse_price_bias_bps":adverse_price_bias_bps,"price_pair_n":price_pair_n,"price_evidence_coverage":price_evidence_coverage,"price_evidence_status":price_evidence_status,"parameter_update_allowed":False,"real_submit_allowed":False}
