from scripts.compare_kioxia_dex_models import walk
def test_walk_forward_never_trains_on_current_row():
    rows=[]
    for i in range(12):
        rows.append({"x":str(i),"y":str(2*i+1)})
    r=walk(rows,["x"],"y",5)
    assert r["n"]==7
    assert r["mae"]<1e-8
def test_missing_feature_is_excluded_not_imputed():
    rows=[{"x":str(i),"y":str(i)} for i in range(8)]
    rows[6]["x"]=""
    r=walk(rows,["x"],"y",4)
    assert r["n"]==3
