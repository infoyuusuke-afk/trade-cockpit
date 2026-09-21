#!/usr/bin/env python3
"""Evidence-gated opening-state enrichment from MS2/order-book/tape data.

TradingView OHLCV alone must remain DELAYED_OPEN_UNCLASSIFIED.
"""

VALID_STATES=("NORMAL_OPEN","DELAYED_OPEN_UNCLASSIFIED","SPECIAL_BUY","SPECIAL_SELL","HALT_OR_OTHER")

def enrich_open_state(base_state, evidence):
    if base_state not in VALID_STATES:
        raise ValueError("invalid base_state")
    if base_state=="NORMAL_OPEN":
        return {"open_state":"NORMAL_OPEN","evidence_level":"OHLCV","research_only":True}
    if base_state!="DELAYED_OPEN_UNCLASSIFIED":
        return {"open_state":base_state,"evidence_level":"EXISTING","research_only":True}

    source=evidence.get("source")
    observed_at=evidence.get("observed_at")
    quote_state=evidence.get("quote_state")
    if source!="MS2" or not observed_at:
        return {"open_state":"DELAYED_OPEN_UNCLASSIFIED","evidence_level":"INSUFFICIENT","research_only":True}
    if quote_state=="SPECIAL_BUY":
        state="SPECIAL_BUY"
    elif quote_state=="SPECIAL_SELL":
        state="SPECIAL_SELL"
    elif quote_state in ("HALT","OTHER"):
        state="HALT_OR_OTHER"
    else:
        state="DELAYED_OPEN_UNCLASSIFIED"
    return {"open_state":state,"evidence_level":"MS2_OBSERVED","evidence_observed_at":observed_at,"research_only":True}
