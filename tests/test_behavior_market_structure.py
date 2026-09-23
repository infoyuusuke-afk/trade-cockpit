from scripts.behavior_market_structure import structure,classify_sweep
def test_sweep_and_reclaim_is_distinct_from_unreclaimed_breakdown():
    assert classify_sweep(prior_low=100,current_low=98,current_close=101,reclaim_level=100)=="liquidity_sweep_reclaim"
    assert classify_sweep(prior_low=100,current_low=98,current_close=99,reclaim_level=100)=="breakdown_unreclaimed"
def test_context_is_factual_not_directional_signal():
    x=structure(price=101,vwap=100,or5_low=99,or5_high=103,volume_ratio=1.5)
    assert x==["above_vwap","above_or5_low","below_or5_high","volume_expanded"]
