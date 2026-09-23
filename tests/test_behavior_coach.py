from scripts.behavior_coach import excursion,market_structure,coach_message
def test_long_excursion():
    x=excursion("LONG",100,103,95);assert x["mae_pct"]==-5;assert x["mfe_pct"]==3
def test_reclaim_evidence_is_factual():
    e=market_structure(101,100,98,105);assert "above_vwap" in e;assert "or5_low_reclaimed" in e;assert "or5_high_reclaimed" not in e
def test_message_does_not_command_trade():
    m=coach_message("breakeven_recovery",["above_vwap"]);assert "市場構造" in m;assert "買え" not in m;assert "売れ" not in m
