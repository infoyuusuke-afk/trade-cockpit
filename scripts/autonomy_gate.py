"""Evidence-gated autonomy promotion. Never enables broker submission."""
LEVELS=("OBSERVE","EXPLAIN","SIMULATE","SHADOW","CONTROLLED_LIVE_ELIGIBLE")
def evaluate(metrics):
    failures=[]
    required=("sample_size","max_drawdown_pct","evidence_integrity","deterministic","kill_switch_tested")
    for k in required:
        if k not in metrics: failures.append("MISSING_"+k.upper())
    if failures: return {"level":"OBSERVE","promotion":False,"failures":failures}
    if metrics["evidence_integrity"] is not True: failures.append("EVIDENCE_INTEGRITY")
    if metrics["deterministic"] is not True: failures.append("NON_DETERMINISTIC")
    if metrics["kill_switch_tested"] is not True: failures.append("KILL_SWITCH_UNTESTED")
    if metrics["sample_size"] < 30: failures.append("INSUFFICIENT_SAMPLE")
    if metrics["max_drawdown_pct"] < 0 or metrics["max_drawdown_pct"] > 100: failures.append("INVALID_DRAWDOWN")
    if failures: return {"level":"SIMULATE","promotion":False,"failures":failures}
    if metrics.get("shadow_completed") is not True:
        return {"level":"SHADOW","promotion":False,"failures":["SHADOW_NOT_COMPLETED"]}
    return {"level":"CONTROLLED_LIVE_ELIGIBLE","promotion":True,"failures":[],
            "real_submit_allowed":False,"requires_separate_live_approval":True}
