"""Build bilingual review copy and English comic beats from verified Tokyo-close facts.

The output is a draft package only. It never publishes and never issues trade instructions.
"""
from scripts.tokyo_close_wall_street import build_package

ROLE_ORDER = ("ham", "meru", "mugi", "kuu")

def _fact_line(fact: dict, lang: str) -> str:
    label, value = fact["label"], fact["value"]
    if lang == "ja":
        return f"{label}: {value}"
    return f"{label}: {value}"

def build_review(session_day: str, facts: list[dict], event_keys: list[str] | None = None) -> dict:
    base = build_package(session_day, facts, event_keys)
    fact_lines_ja = [_fact_line(f, "ja") for f in base["observed_facts"]]
    fact_lines_en = [_fact_line(f, "en") for f in base["observed_facts"]]

    # Facts are intentionally not embellished. Natural-language generation may
    # later wrap these lines, but may not introduce new numeric market claims.
    ja_review = {
        "title": f"{session_day} 東京市場レビュー",
        "facts": fact_lines_ja,
        "note": "確認済みデータのみ。米国市場の方向を断定しません。",
    }
    en_broadcast = {
        "title": "TOKYO CLOSE -> WALL STREET",
        "facts": fact_lines_en,
        "note": "Observed Tokyo-market facts only. Not a prediction of the U.S. session.",
    }

    comic_beats = [
        {"character": "ham", "purpose": "verified_data", "source": "observed_facts"},
        {"character": "meru", "purpose": "market_structure", "source": "observed_facts"},
        {"character": "mugi", "purpose": "human_reaction", "source": "no_new_market_claims"},
        {"character": "kuu", "purpose": "risk_and_watchlist", "source": "no_directional_guarantee"},
    ]
    assert tuple(x["character"] for x in comic_beats) == ROLE_ORDER

    return {
        "owner_review_ja": ja_review,
        "broadcast_en": en_broadcast,
        "comic_beats": comic_beats,
        "source_package": base,
        "owner_approval_required": True,
        "publish_ready": False,
    }
