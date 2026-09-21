#!/usr/bin/env python3
"""Research-only pretrade completeness gate for EV signals."""
REQUIRED_CORE=("DATA_FRESH","MARKET_REGIME","CATALYST","TIME_REGIME")
CONDITIONAL={"SEMICON":["US_SEMICON","KOREA_SEMICON"],"INDEX_SENSITIVE":["INDEX_FUTURES"]}

def required_checks(tags):
    req=set(REQUIRED_CORE)
    for tag in tags or []:
        req.update(CONDITIONAL.get(tag,[]))
    return sorted(req)

def pretrade_gate(signal, completed_checks, tags=None):
    req=required_checks(tags)
    done=set(completed_checks or [])
    missing=[x for x in req if x not in done]
    data_ok="DATA_FRESH" in done and bool(signal.get("data_fresh",False))
    if not data_ok and "DATA_FRESH" not in missing:
        missing.append("DATA_FRESH")
    decision="WAIT" if missing else signal.get("proposed_action","WAIT")
    return {"decision":decision,"proposed_action":signal.get("proposed_action"),
            "required_checks":req,"completed_checks":sorted(done),
            "missing_checks":sorted(set(missing)),
            "gate_pass":not missing,"research_only":True,"auto_execute":False}
