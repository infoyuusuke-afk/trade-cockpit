"""Deterministic continuity ledger for sanitized Entertainment events."""
CHARACTERS={"MUGI","MERU","KUU","HAMU"}
def apply_event(state,event):
    if event.get("sanitized") is not True: raise ValueError("UNSANITIZED_EVENT")
    out={k:dict(v) for k,v in state.items()}
    for change in event.get("character_growth",[]):
        cid=change.get("character")
        if cid not in CHARACTERS: raise ValueError("UNKNOWN_CHARACTER")
        delta=change.get("delta")
        if delta not in (-1,0,1): raise ValueError("INVALID_GROWTH_DELTA")
        axis=change.get("axis")
        if not axis: raise ValueError("MISSING_AXIS")
        current=out.setdefault(cid,{}).get(axis,0)
        out[cid][axis]=current+delta
    return out
