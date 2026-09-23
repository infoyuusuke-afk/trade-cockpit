"""Deterministic research triage for Strategy Lab. No execution side effects."""
from itertools import combinations

def generate_variants(registry, max_pairwise=20):
    base=[{"id":s["id"],"members":[s["id"]],"horizon":s["horizon"],"kind":"SINGLE"} for s in registry["strategies"]]
    pairs=[]
    for a,b in combinations(registry["strategies"],2):
        if a["horizon"]!=b["horizon"]: continue
        pairs.append({"id":a["id"]+"__"+b["id"],"members":[a["id"],b["id"]],"horizon":a["horizon"],"kind":"PAIR"})
        if len(pairs)>=max_pairwise: break
    return base+pairs

def rank_evidence(results):
    def eligible(x):
        return x.get("evidence_integrity") is True and x.get("lookahead_safe") is True and x.get("sample_size",0)>=30
    valid=[x for x in results if eligible(x)]
    # Ranking is research triage only, never trading permission.
    valid.sort(key=lambda x:(x.get("expectancy",float("-inf")),-x.get("max_drawdown_pct",100),x.get("sample_size",0)),reverse=True)
    return [{**x,"research_rank":i+1,"real_submit_allowed":False} for i,x in enumerate(valid)]

def next_experiments(registry, results):
    seen={x.get("strategy_id") for x in results}
    return [{"strategy_id":v["id"],"horizon":v["horizon"],"action":"BACKTEST",
             "real_submit_allowed":False} for v in generate_variants(registry) if v["id"] not in seen]
