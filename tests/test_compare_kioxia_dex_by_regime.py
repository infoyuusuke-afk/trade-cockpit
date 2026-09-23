from scripts.compare_kioxia_dex_by_regime import compare
def test_regimes_are_not_pooled():
    rows=[]
    for i in range(10):
        rows.append({"session_day":f"2026-01-{i+1:02d}","regime":"weekday_overnight" if i<7 else "multi_day_gap","b":str(i),"d":str(i),"open_gap_pct":str(i),
        "open_to_or5_pct":str(i),"or5_to_or15_pct":str(i),"open_to_0930_pct":str(i),"open_to_1000_pct":str(i),"open_to_close_pct":str(i)})
    r=compare(rows,["b"],["d"],3)
    assert r["all"]["sessions"]==10
    assert r["weekday_overnight"]["sessions"]==7
    assert r["multi_day_gap"]["sessions"]==3
