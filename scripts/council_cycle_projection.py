"""Fan out a completed Council cycle to safe read-only projections."""
from __future__ import annotations
from scripts.live_commentary import select_commentary
from scripts.journal_projection import journal_rows
from scripts.entertainment_pipeline import story_candidates
from scripts.commentary_scheduler import schedule
def project_cycle(events,orchestration,*,last_spoken_at=None,cooldown_seconds=20):
    commentary=select_commentary(events,limit=10)
    spoken=schedule(commentary,last_spoken_at=last_spoken_at,cooldown_seconds=cooldown_seconds,max_items=1)
    return {"council_status":orchestration["council"]["status"],"command_center":orchestration["command_center"],"commentary":spoken,"journal":journal_rows(events),"stories":story_candidates(events),"owner_approval_required":True,"real_submit_allowed":False,"external_publish_allowed":False}
