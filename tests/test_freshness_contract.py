from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.freshness_contract import assess_freshness, gate_payload

JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 9, 24, 14, 30, 0, tzinfo=JST)

def test_ms2_quote_is_live_inside_15_seconds():
    r = assess_freshness("ms2_quote", "2026-09-24T14:29:50+09:00", NOW)
    assert r.status == "LIVE"
    assert r.usable is True

def test_ms2_quote_is_not_current_after_ttl():
    r = assess_freshness("ms2_quote", "2026-09-24T14:29:30+09:00", NOW)
    assert r.status == "DELAYED"
    assert r.usable is False

def test_old_policy_material_is_stale():
    r = assess_freshness("policy", "2026-03-19T09:00:00+09:00", NOW)
    assert r.status == "STALE"
    assert r.usable is False

def test_missing_timestamp_is_invalid():
    r = assess_freshness("news", None, NOW)
    assert r.status == "INVALID"
    assert r.usable is False

def test_stale_payload_cannot_masquerade_as_current():
    p = gate_payload(
        {"observed_at": "2026-09-24T14:29:00+09:00", "current_value": 1234.0},
        "ms2_quote", NOW,
    )
    assert p["display_as_current"] is False
    assert p["current_value"] is None

def test_quote_at_exact_ttl_is_still_live():
    r = assess_freshness("ms2_quote", "2026-09-24T14:29:45+09:00", NOW)
    assert r.status == "LIVE"
    assert r.usable is True

def test_future_quote_is_invalid():
    r = assess_freshness("ms2_quote", "2026-09-24T14:30:06+09:00", NOW)
    assert r.status == "INVALID"
    assert r.usable is False

def test_failed_source_is_never_current_even_with_fresh_timestamp():
    r = assess_freshness("ms2_quote", "2026-09-24T14:29:59+09:00", NOW, source_ok=False)
    assert r.status == "INVALID"
    assert r.usable is False
