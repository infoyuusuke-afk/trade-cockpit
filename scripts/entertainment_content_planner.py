"""Turn internal Entertainment Department queue records into channel briefs.

This module plans structure only. It does not call a generative model or publish.
"""
from __future__ import annotations

CHARACTERS={
 "MUGI":{"name":"ムギ","function":"emotion_and_momentum"},
 "MERU":{"name":"メル","function":"market_structure"},
 "KUU":{"name":"くうちゃん","function":"risk_and_invalidation"},
 "HAMU":{"name":"ハム","function":"evidence_and_research"},
}

def _cast_for(channel):
    if channel=="MANGA": return ["MUGI","MERU","KUU","HAMU"]
    if channel=="X": return ["MUGI","HAMU"]
    if channel=="YOUTUBE": return ["MUGI","MERU","KUU","HAMU"]
    raise ValueError("UNKNOWN_CHANNEL")

def plan_content(item):
    if item.get("status")!="DRAFT_INTERNAL" or item.get("external_publish_allowed") is not False:
        raise ValueError("UNSAFE_EDITORIAL_ITEM")
    channel=item.get("channel")
    cast=_cast_for(channel)
    beats={"MANGA":["hook","reaction","turn","aftertaste"],
           "X":["specific_observation","human_reaction","open_loop"],
           "YOUTUBE":["cold_open","what_happened","character_conflict","evidence","next_watch"]}[channel]
    return {
      "source_event_id":item["source_event_id"],"channel":channel,
      "working_title":item["working_title"],"cast":[CHARACTERS[x] for x in cast],
      "beats":beats,"continuity_required":True,"character_voice_required":True,
      "avoid_generic_ai_prose":True,"status":"BRIEF_INTERNAL",
      "owner_approval_required":True,"external_publish_allowed":False,
    }

def plan_queue(queue):
    return [plan_content(x) for x in queue]
