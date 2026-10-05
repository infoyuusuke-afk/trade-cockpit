"""Production research candidates. A market total is not a symbol pick.

candidate_id is created only when one observation already names a symbol
inside the limited precision-watch scope. Fixtures and full-market claims
stay out of the production file.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research_candidates"
CANDIDATES = STORE / "candidates.jsonl"
LATEST = STORE / "latest.json"
UNIVERSE_SCOPE = "LIMITED / PRECISION_WATCH_ONLY"
SIDES = {"LONG", "SHORT", "WATCH", "NO-TRADE"}
MARKET_LANE_IDS = {"short_sale_ratio", "investor_futures_flow", "arbitrage_balance"}
FORBIDDEN_LABEL = "BRAIN ENTRY"


def _full_market(value) -> bool:
    if not isinstance(value, str):
        return False
    compact = re.sub(r"\s+", "", value).upper()
    if "全市場" in value or "市場全体" in value:
        return True
    return "FULL_MARKET" in compact or compact == "FULL" or "WHOLEMARKET" in compact


def _clock(value):
    if isinstance(value, str) and "T" in value and "+" in value and FORBIDDEN_LABEL not in value:
        return value.strip()
    return None


def _reason(value):
    if isinstance(value, str) and value.strip() and FORBIDDEN_LABEL not in value:
        return value.strip()
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        text = " / ".join(item.strip() for item in value)
        if FORBIDDEN_LABEL not in text:
            return text
    return None


def candidate_from_observation(raw) -> dict | None:
    """Return one production candidate, or nothing.

    Missing clocks stay missing. This function does not invent a symbol,
    a side, or a time from a market-wide total.
    """
    if not isinstance(raw, dict):
        return None
    if raw.get("id") in MARKET_LANE_IDS:
        return None
    if raw.get("fixture") is True or raw.get("acceptance_class") == "synthetic":
        return None
    if raw.get("source_stage") in {"SYNTHETIC/REPLAY", "SYNTHETIC"}:
        return None
    if raw.get("execution_authority") is True or raw.get("real_submit_allowed") is True:
        return None
    if raw.get("trading_adoption") is True:
        return None
    symbol = raw.get("symbol")
    side = raw.get("side")
    if not isinstance(symbol, str) or not symbol.strip() or _full_market(symbol):
        return None
    if side not in SIDES:
        return None
    scope = raw.get("universe_scope")
    if isinstance(scope, str) and scope and (scope != UNIVERSE_SCOPE or _full_market(scope)):
        return None
    if _full_market(scope if isinstance(scope, str) else ""):
        return None
    created = _clock(raw.get("candidate_created_at") or raw.get("discovered_at"))
    entry_at = _clock(raw.get("entry_candidate_at"))
    available = _clock(raw.get("available_at"))
    generator = raw.get("source_generator") or raw.get("candidate_generator")
    trigger = raw.get("trigger") or raw.get("entry_trigger")
    regime = raw.get("market_regime")
    reason = _reason(raw.get("main_reasons") if raw.get("main_reasons") is not None else raw.get("reason"))
    if raw.get("data_quality") != "OK":
        return None
    if not created or not entry_at or not available or reason is None:
        return None
    if not isinstance(generator, str) or not generator.strip() or FORBIDDEN_LABEL in generator:
        return None
    if not isinstance(trigger, str) or not trigger.strip() or FORBIDDEN_LABEL in trigger:
        return None
    if not isinstance(regime, str) or not regime.strip() or FORBIDDEN_LABEL in regime:
        return None
    if available > entry_at:
        return None
    canonical = "|".join([symbol.strip(), side, created, generator.strip(), trigger.strip()])
    row = {
        "record_class": "research_candidate",
        "candidate_id": "rc-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
        "symbol": symbol.strip(),
        "side": side,
        "candidate_created_at": created,
        "discovered_at": created,
        "entry_candidate_at": entry_at,
        "source_generator": generator.strip(),
        "candidate_generator": generator.strip(),
        "trigger": trigger.strip(),
        "entry_trigger": trigger.strip(),
        "main_reasons": reason,
        "reason": reason,
        "market_regime": regime.strip(),
        "available_at": available,
        "data_quality": "OK",
        "universe_scope": UNIVERSE_SCOPE,
        "execution_authority": False,
        "trading_adoption": False,
        "real_submit_allowed": False,
        "counts_as_production": True,
        "fixture": False,
        "price_fresh": False,
    }
    price = raw.get("price")
    if raw.get("price_fresh") is True and isinstance(price, (int, float)) and not isinstance(price, bool):
        row["price"] = price
        row["price_fresh"] = True
    return row


def _read_rows(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError("MALFORMED")
        rows.append(item)
    return rows


def load_production(path: Path | None = None) -> list:
    """Read the production file. A fixture row is dropped."""
    try:
        rows = _read_rows(path or CANDIDATES)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return []
    accepted = []
    seen = set()
    for raw in rows:
        row = candidate_from_observation(raw)
        if row is None or row["candidate_id"] in seen:
            continue
        seen.add(row["candidate_id"])
        accepted.append(row)
    return accepted


def publish_production(observations=None, *, candidates_path: Path | None = None, latest_path: Path | None = None) -> dict:
    """Rewrite the production file from real observations only."""
    source = observations
    if source is None:
        try:
            source = _read_rows(candidates_path or CANDIDATES)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            source = []
    accepted = []
    seen = set()
    for raw in source:
        row = candidate_from_observation(raw)
        if row is None or row["candidate_id"] in seen:
            continue
        seen.add(row["candidate_id"])
        accepted.append(row)
    path = candidates_path or CANDIDATES
    latest = latest_path or LATEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in accepted), encoding="utf-8")
    payload = {
        "universe_scope": UNIVERSE_SCOPE,
        "production_candidate_count": len(accepted),
        "fixtures_excluded": True,
        "reason": "NO_SYMBOL_LEVEL_OBSERVATION" if not accepted else "SYMBOL_LEVEL",
        "trading_adoption": False,
        "real_submit_allowed": False,
        "live_signal_changed": False,
        "execution_authority": False,
    }
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
