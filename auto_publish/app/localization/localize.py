"""LOCALIZE: render the canonical story into en-US (primary) and ja-JP.

Every sentence is produced from a fixed template filled with verified fact
values; the post keeps the fact_ids of every segment so evidence is traceable
from the final text back to the SHA256-locked source file.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
LANGS = ("en-US", "ja-JP")


def load_template(lang: str) -> dict:
    return json.loads((TEMPLATES_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _date_long(session_date: str, lang: str) -> str:
    d = date.fromisoformat(session_date)
    if lang == "ja-JP":
        return f"{d.year}年{d.month}月{d.day}日"
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _move(change: float, t: dict) -> str:
    if change > 0:
        return t["move_words"]["up"]
    if change < 0:
        return t["move_words"]["down"]
    return t["move_words"]["flat"]


def render_segment(seg: dict, script: dict, t: dict, lang: str) -> str:
    inst = script["instrument"]
    d = seg["data"]
    common = {"name_en": inst["name_en"], "name_ja": inst["name_ja"], "code": inst["code"]}
    typ = seg["type"]
    if typ == "hook":
        return t["hook"].format(**common, move=_move(d["change_pct"], t), abs_change=abs(d["change_pct"]),
                                date_long=_date_long(script["session_date"], lang))
    if typ == "close":
        return t["close"].format(**d)
    if typ == "volume":
        return t["volume"].format(**d)
    if typ == "radar":
        return t["radar"].format(time_jst=d["time_jst"], event_text=t["radar_events"][d["event"]])
    if typ == "paper":
        side = t["sides"].get(d["side"], d["side"])
        if d["result_closed"]:
            return t["paper_closed"].format(side=side, entry=d["entry"], r=d["r"])
        return t["paper_open"].format(side=side, entry=d["entry"])
    if typ == "disclaimer":
        text = t["disclaimer"]
        if d["has_paper"]:
            text += t["disclaimer_paper"]
        if d["fixture"]:
            text += t["disclaimer_fixture"]
        return text
    raise ValueError(f"unknown segment type {typ}")


def localize(script: dict, lang: str) -> dict:
    t = load_template(lang)
    inst = script["instrument"]
    hook_change = script["segments"][0]["data"]["change_pct"]
    segments = [{"id": s["id"], "type": s["type"], "fact_ids": list(s["fact_ids"]),
                 "text": render_segment(s, script, t, lang)} for s in script["segments"]]
    hashtags = [h.format(code=inst["code"]) for h in t["hashtags"]]
    body = "\n".join(s["text"] for s in segments)
    return {
        "schema": "auto_publish.post.v1",
        "story_id": script["story_id"],
        "session_date": script["session_date"],
        "lang": lang,
        "fixture": script["fixture"],
        "title": t["title"].format(name_en=inst["name_en"], name_ja=inst["name_ja"], code=inst["code"],
                                   change_pct=hook_change),
        "segments": segments,
        "hashtags": hashtags,
        "caption": body + "\n\n" + " ".join(hashtags),
        "source_refs": [{k: r[k] for k in ("fact_id", "kind", "basis", "session_date", "rel_path", "sha256", "pointer")}
                        for r in script["source_refs"]],
    }
