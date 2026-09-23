"""Presentation-only localization for C-195.

This module does not create signals, predictions, orders, or publication actions.
"""
COPY = {
    "rapid_adverse_move": {"ja": "急落警戒", "en": "Sharp Drop Alert"},
    "vwap_reclaim": {"ja": "VWAP回復", "en": "VWAP Reclaim"},
    "or5_low_reclaim": {"ja": "OR5安値を奪回", "en": "OR5 Low Reclaimed"},
    "cautious_new_long": {"ja": "新規ロング慎重", "en": "Caution on New Longs"},
    "relief_exit_risk": {"ja": "安堵利確注意", "en": "Relief-Exit Risk"},
}

MODES = {"OWNER_JA", "BROADCAST_EN", "BILINGUAL"}

def render_event(event_key: str, mode: str) -> dict:
    if mode not in MODES:
        raise ValueError("unsupported presentation mode")
    copy = COPY.get(event_key)
    if copy is None:
        raise ValueError("unknown event key: fail closed")
    if mode == "OWNER_JA":
        return {"mode": mode, "primary": copy["ja"]}
    if mode == "BROADCAST_EN":
        return {"mode": mode, "primary": copy["en"]}
    return {"mode": mode, "primary": copy["ja"], "secondary": copy["en"]}
