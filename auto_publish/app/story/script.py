"""SCRIPT: language-neutral canonical story object (facts + source refs only).

Deterministic and template-driven in R1 -- no generative model is involved, so
every number in the output is copied from a verified fact.
"""
from __future__ import annotations

import json

SCHEMA = "auto_publish.story.v1"


def _code(ticker: str) -> str:
    return ticker.split(".")[0]


def build_script(story: dict, refs: list[dict]) -> dict:
    plan = json.loads(story["plan_json"])
    by_id = {r["fact_id"]: r for r in refs}
    mover = by_id[plan["hook"]["fact_ids"][0]]["value"]

    def seg_data(btype: str, fact_ids: list[str]) -> dict:
        v = by_id[fact_ids[0]]["value"]
        if btype in ("hook", "close"):
            return {"close": v["close"], "change_pct": v["change_pct"]}
        if btype == "volume":
            return {"volume_ratio": v["volume_ratio"]}
        if btype == "radar":
            d = {"time_jst": v["time_jst"], "event": v["event"]}
            if v.get("vwap_relation") in ("above", "below"):
                d["vwap_relation"] = v["vwap_relation"]
            return d
        if btype == "paper":
            closed = bool(v.get("closed", v.get("r") is not None)) and v.get("r") is not None
            return {"side": v.get("side", "LONG"), "entry": v["entry"], "r": v.get("r") if closed else None,
                    "result_closed": closed}
        raise ValueError(btype)

    segments = [{"id": "hook", "type": "hook", "fact_ids": plan["hook"]["fact_ids"],
                 "data": seg_data("hook", plan["hook"]["fact_ids"])}]
    for i, b in enumerate(plan["bullets"], start=1):
        segments.append({"id": f"b{i}", "type": b["type"], "fact_ids": b["fact_ids"],
                         "data": seg_data(b["type"], b["fact_ids"])})
    bases = sorted({by_id[f]["basis"] for s in segments for f in s["fact_ids"]})
    segments.append({"id": "disclaimer", "type": "disclaimer", "fact_ids": [],
                     "data": {"has_paper": "paper" in bases or "shadow" in bases, "fixture": bool(story["fixture"])}})
    return {
        "schema": SCHEMA,
        "story_id": story["story_id"],
        "session_date": story["session_date"],
        "topic": story["topic"],
        "fixture": bool(story["fixture"]),
        "instrument": {"ticker": mover["ticker"], "code": _code(mover["ticker"]),
                       "name_en": mover["name_en"], "name_ja": mover["name_ja"]},
        "bases": bases,
        "segments": segments,
        "source_refs": refs,
    }
