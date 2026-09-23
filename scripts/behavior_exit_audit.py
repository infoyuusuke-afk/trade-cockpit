#!/usr/bin/env python3
"""C-191 offline audit: separate relief exits from structurally justified exits."""
def exit_context(*,had_adverse,near_breakeven,sweep_label,facts):
    reclaimed=("above_vwap" in facts and "above_or5_low" in facts)
    broken=(sweep_label=="breakdown_unreclaimed" and "below_vwap" in facts and "below_or5_low" in facts)
    if had_adverse and near_breakeven and reclaimed:return "relief_exit_candidate"
    if broken:return "structure_exit_candidate"
    return "ambiguous_exit"

def summarize(rows):
    out={"relief_exit_candidate":0,"structure_exit_candidate":0,"ambiguous_exit":0}
    for r in rows:out[r]+=1
    return {"n":len(rows),"counts":out}
