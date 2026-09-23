#!/usr/bin/env python3
"""C-191 market-structure context for behavior events. No trade decisions."""
def structure(*,price,vwap,or5_low,or5_high,or15_low=None,or15_high=None,volume_ratio=None):
    facts=[]
    if vwap is not None:facts.append("above_vwap" if price>=vwap else "below_vwap")
    for name,val in (("or5_low",or5_low),("or5_high",or5_high),("or15_low",or15_low),("or15_high",or15_high)):
        if val is not None:facts.append(("above_" if price>=val else "below_")+name)
    if volume_ratio is not None:facts.append("volume_expanded" if volume_ratio>1 else "volume_not_expanded")
    return facts

def classify_sweep(*,prior_low,current_low,current_close,reclaim_level):
    """Descriptive label only: pierce below prior low then close back above chosen level."""
    if None in (prior_low,current_low,current_close,reclaim_level):return None
    if current_low<prior_low and current_close>=reclaim_level:return "liquidity_sweep_reclaim"
    if current_low<prior_low and current_close<reclaim_level:return "breakdown_unreclaimed"
    return "no_downside_sweep"
