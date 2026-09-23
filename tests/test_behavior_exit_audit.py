from scripts.behavior_exit_audit import exit_context
def test_relief_and_structure_exit_are_separated():
    assert exit_context(had_adverse=True,near_breakeven=True,sweep_label="liquidity_sweep_reclaim",facts=["above_vwap","above_or5_low"])=="relief_exit_candidate"
    assert exit_context(had_adverse=True,near_breakeven=False,sweep_label="breakdown_unreclaimed",facts=["below_vwap","below_or5_low"])=="structure_exit_candidate"
