#!/usr/bin/env python3
"""C-191 deterministic behavior state machine. Advisory only."""
from dataclasses import dataclass,field
from typing import Optional

@dataclass
class State:
    side:str="FLAT"; entry:Optional[float]=None; worst:Optional[float]=None; best:Optional[float]=None
    had_adverse:bool=False; exited_after_recovery:bool=False; last_exit_side:Optional[str]=None
    events:list=field(default_factory=list)

def update(s:State, *, side:str, price:float, adverse_trigger_pct:float=None, recovery_band_pct:float=None):
    """Thresholds must come from calibrated config; None disables classification."""
    ev=[]
    if side!="FLAT" and s.side=="FLAT":
        s.side=side;s.entry=price;s.worst=price;s.best=price;s.had_adverse=False
        if s.last_exit_side and side!=s.last_exit_side:
            ev.append("post_exit_flip")
    elif side!="FLAT" and s.side==side:
        if side=="LONG": s.worst=min(s.worst,price);s.best=max(s.best,price); adverse=(price/s.entry-1)*100
        else: s.worst=max(s.worst,price);s.best=min(s.best,price); adverse=(s.entry/price-1)*100
        if adverse_trigger_pct is not None and adverse<=-abs(adverse_trigger_pct) and not s.had_adverse:
            s.had_adverse=True;ev.append("rapid_adverse_move")
        if s.had_adverse and recovery_band_pct is not None:
            gap=abs(price/s.entry-1)*100
            if gap<=abs(recovery_band_pct):ev.append("breakeven_recovery")
    elif side=="FLAT" and s.side!="FLAT":
        prior=s.side;s.last_exit_side=prior
        if s.had_adverse and recovery_band_pct is not None and abs(price/s.entry-1)*100<=abs(recovery_band_pct):
            ev.append("relief_exit");s.exited_after_recovery=True
        s.side="FLAT";s.entry=None;s.worst=None;s.best=None;s.had_adverse=False
    s.events.extend(ev);return ev
