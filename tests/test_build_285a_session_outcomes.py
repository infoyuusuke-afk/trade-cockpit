from scripts.build_285a_session_outcomes import build
def row(t,o,h,l,c,v=10): return {"time":t,"open":str(o),"high":str(h),"low":str(l),"close":str(c),"volume":str(v)}
def test_session_targets_use_only_defined_windows():
    rs=[row("2026-09-24T09:00:00+09:00",100,102,99,101),row("2026-09-24T09:04:45+09:00",101,103,100,102),
        row("2026-09-24T09:14:45+09:00",102,104,101,103),row("2026-09-24T09:30:00+09:00",103,105,102,104),
        row("2026-09-24T10:00:00+09:00",104,106,103,105),row("2026-09-24T15:30:00+09:00",105,107,104,106)]
    x=build(rs,95)
    assert x["or5_high"]==103
    assert x["or15_high"]==104
    assert round(x["open_gap_pct"],6)==round((100/95-1)*100,6)
    assert x["open_to_0930_pct"]==4
