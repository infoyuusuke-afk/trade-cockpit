#!/usr/bin/env python3
"""C-189 regime labels; deterministic, no external calendar dependency."""
from datetime import date
def regime(prev_session:str, session:str)->dict:
    a,b=date.fromisoformat(prev_session),date.fromisoformat(session)
    gap=(b-a).days
    return {"calendar_gap_days":gap,"is_multi_day_gap":gap>=3,
            "regime":"multi_day_gap" if gap>=3 else ("weekend_or_holiday" if gap>1 else "weekday_overnight")}
