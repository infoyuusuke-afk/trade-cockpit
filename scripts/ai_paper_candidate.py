#!/usr/bin/env python3
"""C-193 validation only. Does not submit orders."""
def validate_candidate(x):
    errors=[]
    if x.get("candidate_source")=="AI" and x.get("planned_qty")!=100:
        errors.append("AI equity validation lot must be 100 shares")
    if x.get("status")=="EXECUTED" and x.get("actual_qty") is None:
        errors.append("executed record requires actual_qty")
    if x.get("candidate_source")=="AI" and x.get("actual_qty") is not None and x.get("actual_qty")!=100:
        errors.append("AI executed validation lot must be exactly 100 shares")
    if not x.get("invalidation"): errors.append("invalidation required before approval")
    if not x.get("thesis"): errors.append("thesis required before approval")
    return errors

def can_execute(x):
    """Eligibility gate only; this module never submits an order."""
    return x.get("status")=="APPROVED" and not validate_candidate(x)
