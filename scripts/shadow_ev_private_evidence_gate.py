"""Private Shadow evidence acceptance boundary for EV (pure, inactive).

Gate ordering: durable independent evidence/anchor -> finalized hash chain ->
strictly scoped observed witness events -> paper-only EV row. No local PC I/O,
network, order routing, automatic writes, or mutable global state.
"""
from datetime import datetime
from scripts.shadow_ev_evidence_projection import project
from scripts import shadow_forward_evidence_chain as chain
from scripts import shadow_forward_persistence_pair as pair_gate

REQUIRED_STEPS=("ENTRY_FILL","EXIT_FILL","COST_VERIFIED")

def accept_private_roundtrip(events, retained_pair, *, now):
    """Return (paper row, reason). Reject caller-supplied untrusted assumptions."""
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        return None,"NOW_NOT_TIMEZONE_AWARE"
    if not isinstance(events,list):
        return None,"INVALID_CHAIN"
    try:
        status=pair_gate.pair_status(retained_pair)
    except (TypeError,ValueError,AttributeError):
        return None,"PRIVATE_PAIR_INVALID"
    if status!="PAIR_DURABLE_MATCH":
        return None,status
    validated=chain.verify_chain(events,now=now,expected_anchor=retained_pair.retained_anchor)
    if not validated["valid"] or not validated["finalized"]:
        return None,"FINALIZED_CHAIN_NOT_VERIFIED"
    if len(events)!=5 or [e.get("event_type") for e in events]!=[
        "CAPTURE_START","LIFECYCLE_STEP","LIFECYCLE_STEP","LIFECYCLE_STEP","FINALIZE"
    ]:
        return None,"UNEXPECTED_CHAIN_STRUCTURE"
    start=events[0].get("payload")
    if not isinstance(start,dict) or set(start)!={"intent"}:
        return None,"INTENT_ENVELOPE_INVALID"
    steps={}
    for e in events[1:4]:
        wrapper=e.get("payload")
        if not isinstance(wrapper,dict) or set(wrapper)!={"kind","data"}:
            return None,"EVIDENCE_ENVELOPE_INVALID"
        kind=wrapper["kind"]
        if kind in steps or kind not in REQUIRED_STEPS or not isinstance(wrapper["data"],dict):
            return None,"EVIDENCE_STEP_INVALID"
        steps[kind]=wrapper["data"]
    if set(steps)!=set(REQUIRED_STEPS):
        return None,"EVIDENCE_STEP_MISSING"
    if events[-1].get("payload")!={"status":"CLOSED","research_only":True}:
        return None,"FINALIZATION_INVALID"
    # Even a valid hash/anchor proves record integrity, not independent
    # exchange fills or verified fees. Projection additionally checks each
    # source, cost provenance, strategy identity, quantity and time.
    row,reason=project(start["intent"],steps["ENTRY_FILL"],steps["EXIT_FILL"],steps["COST_VERIFIED"])
    if reason:
        return None,reason
    return row,None
