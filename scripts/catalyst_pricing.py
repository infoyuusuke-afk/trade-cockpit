#!/usr/bin/env python3
"""Research-only catalyst pricing / sell-the-news features.

No causal claim is made. Features describe price/volume behavior after the
first point-in-time-known catalyst observation and before a decision cutoff.
"""

def pricing_features(event, price_at_first_known, price_at_decision,
                     volume_ratio_at_decision=None):
    if price_at_first_known is None or price_at_decision is None:
        raise ValueError("prices required")
    if price_at_first_known <= 0 or price_at_decision <= 0:
        raise ValueError("prices must be positive")
    move=(price_at_decision/price_at_first_known-1)*100
    return {
      "event_id":event["event_id"],
      "event_state":event["state"],
      "price_move_since_first_known_pct":move,
      "volume_ratio_at_decision":volume_ratio_at_decision,
      "priced_in_direction":"UP" if move>0 else ("DOWN" if move<0 else "FLAT"),
      "research_only":True
    }

def sell_the_news_context(pricing, confirmation_now=False):
    """Descriptive context only; never emits a trade signal."""
    move=pricing["price_move_since_first_known_pct"]
    return {
      **pricing,
      "confirmation_now":bool(confirmation_now),
      "prior_runup":move>0,
      "prior_selloff":move<0,
      "sell_the_news_research_case":bool(confirmation_now and move>0),
      "buy_the_news_research_case":bool(confirmation_now and move<0)
    }
