#!/usr/bin/env python3
"""Point-in-time signal features. Never infer unavailable market context."""
def signal_features(rows, i, prev_close=None, market=None):
    if i < 0 or i >= len(rows): raise IndexError(i)
    seen=rows[:i+1]
    bar=rows[i]
    vols=[x["volume"] for x in seen]
    base=vols[max(0,len(vols)-21):-1]
    avg_vol=sum(base)/len(base) if base else None
    volume_ratio=(bar["volume"]/avg_vol) if avg_vol else None
    turnover=bar["close"]*bar["volume"]
    pv=sum(((x["high"]+x["low"]+x["close"])/3)*x["volume"] for x in seen)
    vol=sum(x["volume"] for x in seen)
    vw=pv/vol if vol else None
    vwap_dev=((bar["close"]/vw)-1)*100 if vw else None
    hi=max(x["high"] for x in seen); lo=min(x["low"] for x in seen)
    intraday_range=((hi-lo)/seen[0]["open"])*100 if seen[0]["open"] else None
    or5=seen[:20] if len(seen)>=20 else None
    or5_width=((max(x["high"] for x in or5)-min(x["low"] for x in or5))/seen[0]["open"]*100) if or5 else None
    gap=((seen[0]["open"]/prev_close)-1)*100 if prev_close else None
    market=market or {}
    return {
      "volume_ratio_20": volume_ratio,
      "bar_turnover": turnover,
      "vwap_deviation_pct": vwap_dev,
      "or5_width_pct": or5_width,
      "intraday_range_pct": intraday_range,
      "gap_pct": gap,
      "nikkei_return_pct": market.get("nikkei_return_pct"),
      "topix_return_pct": market.get("topix_return_pct"),
      "futures_return_pct": market.get("futures_return_pct"),
    }
