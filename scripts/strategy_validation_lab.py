"""Validation metrics for research strategies. Pure computation; no trading side effects."""
def validate_run(x):
    required=("strategy_id","trades","train_expectancy","test_expectancy","gross_expectancy","cost_per_trade","mae_mean","mfe_mean","regime","symbol_class")
    missing=[k for k in required if k not in x]
    if missing:return {"strategy_id":x.get("strategy_id"),"status":"INVALID","reasons":["MISSING:"+",".join(missing)],"promotion_eligible":False}
    net=x["gross_expectancy"]-x["cost_per_trade"]
    reasons=[]
    if x["trades"]<30: reasons.append("INSUFFICIENT_SAMPLE")
    if x["test_expectancy"]<=0: reasons.append("OOS_NON_POSITIVE")
    if net<=0: reasons.append("COST_ADJUSTED_NON_POSITIVE")
    if x["mae_mean"]<0 or x["mfe_mean"]<0: reasons.append("INVALID_MAE_MFE")
    if x["train_expectancy"]>0 and x["test_expectancy"]/x["train_expectancy"]<0.35: reasons.append("OOS_DECAY")
    return {"strategy_id":x["strategy_id"],"status":"PASS" if not reasons else "FAIL","reasons":reasons,
            "net_expectancy":net,"regime":x["regime"],"symbol_class":x["symbol_class"],
            "promotion_eligible":not reasons,"real_submit_allowed":False}

def aggregate_partitions(rows):
    out={}
    for r in rows:
        v=validate_run(r); key=(r.get("strategy_id"),r.get("regime"),r.get("symbol_class"))
        out[key]=v
    return out
