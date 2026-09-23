#!/usr/bin/env python3
"""C-191 post-exit opportunity-cost labels from confirmed future bars."""
def post_exit_mfe(side,exit_price,future_prices):
    if not future_prices or not exit_price:return None
    if side=="LONG": return (max(future_prices)/exit_price-1)*100
    if side=="SHORT": return (exit_price/min(future_prices)-1)*100
    return None

def horizons(side,exit_price,prices_by_seconds):
    return {f"post_exit_mfe_{sec}s_pct":post_exit_mfe(side,exit_price,prices_by_seconds.get(sec,[]))
            for sec in (30,60,300,900,1800)}
