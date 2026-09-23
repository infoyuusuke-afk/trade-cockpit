from scripts.evaluate_kioxia_dex_signal import pearson, summarize

def test_perfect_positive_relation():
    rows=[{"x":str(x),"y":str(x*2)} for x in (-2,-1,1,2)]
    s=summarize(rows,"x","y")
    assert s["n"]==4
    assert abs(s["corr"]-1)<1e-12
    assert s["direction_hit_rate"]==1

def test_missing_values_are_not_imputed():
    rows=[{"x":"1","y":"1"},{"x":"","y":"2"},{"x":"3","y":""}]
    assert summarize(rows,"x","y")["n"]==1
