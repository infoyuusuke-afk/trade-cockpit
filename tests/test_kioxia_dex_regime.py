from scripts.kioxia_dex_regime import regime
def test_three_day_gap_is_separate_regime():
    x=regime("2026-09-18","2026-09-24")
    assert x["calendar_gap_days"]==6
    assert x["is_multi_day_gap"] is True
    assert x["regime"]=="multi_day_gap"
