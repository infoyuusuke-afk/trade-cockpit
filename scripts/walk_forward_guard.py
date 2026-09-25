"""Chronological walk-forward and multiple-testing guard. Research only."""
from math import isfinite

def evaluate_folds(strategy_id, folds, hypotheses_tested=1):
    reasons=[]
    if not folds: reasons.append("NO_FOLDS")
    ordered=sorted(folds,key=lambda x:x.get("train_end",""))
    if ordered!=folds: reasons.append("NON_CHRONOLOGICAL")
    for f in folds:
        if not all(k in f for k in ("train_end","test_start","test_end","test_expectancy","p_value")):
            reasons.append("INCOMPLETE_FOLD"); continue
        if not (f["train_end"] < f["test_start"] <= f["test_end"]): reasons.append("TIME_LEAKAGE")
        if not isfinite(f["test_expectancy"]) or f["test_expectancy"]<=0: reasons.append("NON_POSITIVE_FOLD")
    alpha=.05/max(1,hypotheses_tested)  # Bonferroni v1: deliberately conservative.
    complete=[f for f in folds if "p_value" in f]
    if complete and any((not isfinite(f["p_value"]) or f["p_value"]>alpha) for f in complete):
        reasons.append("MULTIPLE_TESTING_NOT_CLEARED")
    return {"strategy_id":strategy_id,"status":"PASS" if not reasons else "FAIL",
            "reasons":sorted(set(reasons)),"adjusted_alpha":alpha,
            "promotion_eligible":not reasons,"real_submit_allowed":False}
