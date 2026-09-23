from scripts.behavior_outcome_labels import horizons
def test_long_post_exit_mfe():
    x=horizons("LONG",100,{30:[100,101],60:[100,102],300:[99,104]})
    assert x["post_exit_mfe_30s_pct"]==1
    assert x["post_exit_mfe_60s_pct"]==2
    assert x["post_exit_mfe_300s_pct"]==4
    assert x["post_exit_mfe_900s_pct"] is None
