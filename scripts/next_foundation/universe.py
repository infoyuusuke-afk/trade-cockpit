"""Japan market universe.

Discovery sources (a future TradingView screener, a fixture, a public feed)
only propose candidates. The MS2/RSS roster is a separate high-frequency
monitor layer and cannot become the discovery universe from this process.
"""

from __future__ import annotations

from typing import Protocol

from scripts.next_foundation.config import MARKET_FEATURES


class DiscoveryNotConfigured(RuntimeError):
    """A discovery adapter exists, but phase 1 has no live client for it."""


class MonitorLayerError(RuntimeError):
    """Monitor-layer data was asked to act as a discovery feed."""


class UniverseSource(Protocol):
    source_id: str
    layer: str

    def load(self) -> list[dict]:
        ...


class TradingViewScreenerDiscovery:
    """Discovery adapter slot. Phase 1 does not call TradingView."""

    source_id = "tradingview_screener"
    layer = "discovery"

    def __init__(self, rows: list[dict] | None = None):
        self._rows = rows

    def load(self) -> list[dict]:
        if self._rows is None:
            raise DiscoveryNotConfigured(
                "TradingView Screener is a discovery adapter only. "
                "Phase 1 does not open a network client."
            )
        return list(self._rows)


class Ms2MonitorRoster:
    """Symbols already on the high-frequency monitor. No RSS read."""

    source_id = "ms2_rss_monitor"
    layer = "monitor"

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = tuple(_normalize_symbol(s) for s in (symbols or []) if _normalize_symbol(s))

    def load(self) -> list[dict]:
        raise MonitorLayerError(
            "MS2/RSS is the monitor layer and cannot supply discovery candidates"
        )


def _normalize_symbol(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text.endswith(".T"):
        text = text[:-2]
    if not text or any(ch not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" for ch in text):
        return None
    if not 3 <= len(text) <= 5:
        return None
    return text


def _blank_features() -> dict:
    return {name: None for name in MARKET_FEATURES}


def _as_feature_value(name: str, value):
    if value is None:
        return None
    if name in ("or5_state", "or15_state"):
        if not isinstance(value, str):
            return ("invalid", value)
        state = value.strip().upper()
        if state in ("", "UNKNOWN", "UNFORMED", "NONE", "NULL"):
            return None
        if state not in ("ABOVE", "INSIDE", "BELOW"):
            return ("invalid", value)
        return state
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ("invalid", value)
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return ("invalid", value)
    return number


def collect_universe(payload: dict) -> dict:
    """Merge discovery candidates. Monitor symbols are tags only."""

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        return {
            "candidates": [],
            "fail_closed": True,
            "fail_closed_reason": "EMPTY_DISCOVERY_UNIVERSE",
            "discovery_sources": [],
            "monitor_symbols": [],
            "warnings": ["EMPTY_DISCOVERY_UNIVERSE"],
        }

    monitor = set()
    for raw in payload.get("monitor_symbols") or []:
        symbol = _normalize_symbol(raw)
        if symbol:
            monitor.add(symbol)

    discovery_sources = []
    warnings = []
    merged: dict[str, dict] = {}

    for source in sources:
        if not isinstance(source, dict):
            warnings.append("INVALID_SOURCE")
            continue
        source_id = str(source.get("source_id") or "").strip()
        layer = str(source.get("layer") or "").strip().lower()
        if not source_id or layer not in ("discovery", "monitor"):
            warnings.append("INVALID_SOURCE")
            continue
        if layer == "monitor":
            for raw in source.get("symbols") or []:
                symbol = _normalize_symbol(raw)
                if symbol:
                    monitor.add(symbol)
            if source.get("candidates"):
                warnings.append("MONITOR_CANDIDATES_IGNORED")
            continue
        discovery_sources.append(source_id)
        for raw in source.get("candidates") or []:
            if not isinstance(raw, dict):
                continue
            symbol = _normalize_symbol(raw.get("symbol"))
            if not symbol:
                merged.setdefault("__invalid__", {"invalid": True})
                warnings.append("INVALID_SYMBOL")
                continue
            row = merged.get(symbol)
            if row is None:
                row = {
                    "symbol": symbol,
                    "name": raw.get("name") or None,
                    "price": None,
                    "sources": [source_id],
                    "features": _blank_features(),
                    "feature_sources": {},
                    "invalid_features": [],
                    "rank_history": raw.get("rank_history") or [],
                    "on_monitor_layer": symbol in monitor,
                }
                price = _as_feature_value("liquidity", raw.get("price")) if "price" in raw else None
                if isinstance(price, tuple):
                    row["invalid_features"].append("price")
                else:
                    row["price"] = price
                merged[symbol] = row
            else:
                if source_id not in row["sources"]:
                    row["sources"].append(source_id)
                if not row.get("name") and raw.get("name"):
                    row["name"] = raw.get("name")
            _merge_features(row, raw.get("features") or {}, source_id)
            if raw.get("rank_history") and not row["rank_history"]:
                row["rank_history"] = raw.get("rank_history") or []

    candidates = []
    for symbol, row in merged.items():
        if symbol == "__invalid__":
            continue
        row["on_monitor_layer"] = symbol in monitor
        candidates.append(row)
    candidates.sort(key=lambda item: item["symbol"])
    fail_closed = not candidates
    return {
        "candidates": candidates,
        "fail_closed": fail_closed,
        "fail_closed_reason": "EMPTY_DISCOVERY_UNIVERSE" if fail_closed else None,
        "discovery_sources": discovery_sources,
        "monitor_symbols": sorted(monitor),
        "warnings": warnings,
    }


def _merge_features(row: dict, features: dict, source_id: str) -> None:
    if not isinstance(features, dict):
        row["invalid_features"].append("features")
        return
    for name in MARKET_FEATURES:
        if name not in features:
            continue
        incoming = _as_feature_value(name, features.get(name))
        if isinstance(incoming, tuple):
            row["invalid_features"].append(name)
            continue
        current = row["features"].get(name)
        owner = row["feature_sources"].get(name)
        if current is None or owner is None:
            row["features"][name] = incoming
            row["feature_sources"][name] = source_id
            continue
        if current != incoming:
            row["features"][name] = None
            row["invalid_features"].append(name)
            row.setdefault("conflicts", []).append(name)
