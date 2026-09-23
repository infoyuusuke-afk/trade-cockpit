from scripts.behavior_state_machine import State,update
def test_adverse_recovery_exit_flip_sequence():
    s=State()
    assert update(s,side="LONG",price=100,adverse_trigger_pct=3,recovery_band_pct=.5)==[]
    assert update(s,side="LONG",price=96,adverse_trigger_pct=3,recovery_band_pct=.5)==["rapid_adverse_move"]
    assert "breakeven_recovery" in update(s,side="LONG",price=99.8,adverse_trigger_pct=3,recovery_band_pct=.5)
    assert "relief_exit" in update(s,side="FLAT",price=100,adverse_trigger_pct=3,recovery_band_pct=.5)
    assert "post_exit_flip" in update(s,side="SHORT",price=99.9,adverse_trigger_pct=3,recovery_band_pct=.5)
def test_no_hardcoded_threshold_means_no_behavior_label():
    s=State();update(s,side="LONG",price=100)
    assert update(s,side="LONG",price=90)==[]
