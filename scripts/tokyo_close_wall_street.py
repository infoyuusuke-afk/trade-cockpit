"""Deterministic factual package builder for TOKYO CLOSE -> WALL STREET.

No market prediction, order action, or external publication is performed here.
"""
from scripts.international_presentation import render_event

CHARACTERS = {
    "mugi": {"ja": "ムギ", "role": "trader_emotion"},
    "meru": {"ja": "メル", "role": "market_structure"},
    "kuu": {"ja": "くうちゃん", "role": "risk_control"},
    "ham": {"ja": "ハム", "role": "data_research"},
}

def _require_observed(item: dict) -> None:
    if item.get("observed") is not True:
        raise ValueError("unverified market fact: fail closed")
    if not item.get("label") or item.get("value") is None:
        raise ValueError("market fact requires label and value")

def build_package(session_day: str, facts: list[dict], event_keys: list[str] | None = None) -> dict:
    if not session_day:
        raise ValueError("session_day required")
    for item in facts:
        _require_observed(item)

    observed = [
        {"label": item["label"], "value": item["value"], "source_ts": item.get("source_ts")}
        for item in facts
    ]
    events = [render_event(k, "BROADCAST_EN")["primary"] for k in (event_keys or [])]

    return {
        "series": "TOKYO CLOSE -> WALL STREET",
        "session_day": session_day,
        "audience": "overseas_investors_interested_in_japanese_equities",
        "characters": CHARACTERS,
        "observed_facts": observed,
        "market_events_en": events,
        "sections": [
            "What happened in Tokyo?",
            "Japanese stocks and sectors to know",
            "Context for the coming U.S. session",
            "What to watch on Wall Street",
        ],
        "guardrails": {
            "prediction_is_fact": False,
            "correlation_is_causation": False,
            "publication_requires_owner_approval": True,
        },
        "publish_ready": False,
    }
