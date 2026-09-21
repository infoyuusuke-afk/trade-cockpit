# Claude -> GPT TradingView 15s Handoff Contract v1

Status: research-only. No automatic order execution.

## Ownership
- Claude: acquire TradingView data.
- GPT / AI Cockpit: validate, route, backtest, analyze EV, OOS/WF and promotion evidence.
- Primary symbol: `TSE:285A`.
- Required timeframe: `15S`.
- Required timezone: `Asia/Tokyo`.

Machine-readable schema: `data/claude_tradingview_handoff.schema.json`.

The schema locks the required identity and payload shape. Runtime intake remains authoritative for semantic checks such as finite OHLCV, OHLC relationships, strictly increasing timestamps, routing and session quality.

## Required JSON
```json
{
  "meta": {
    "symbol": "TSE:285A",
    "timeframe": "15S",
    "retrieved_at": "2026-09-21T18:00:00+09:00",
    "timezone": "Asia/Tokyo"
  },
  "bars": [
    {"timestamp":"2026-09-18T09:00:00+09:00","open":0,"high":0,"low":0,"close":0,"volume":0}
  ]
}
```
Use actual TradingView values. Never synthesize missing 15-second bars or interpolate OHLCV.

## Claude acquisition rules
1. Return the TradingView symbol exactly as acquired.
2. Return the source timeframe exactly. Do not label resampled data as `15S`.
3. Preserve observed timestamps. Do not fill missing intervals.
4. Keep OHLCV numeric and finite. Volume must be non-negative.
5. Bars must be strictly increasing by timestamp.
6. `retrieved_at` is the acquisition timestamp, not the market-bar timestamp.
7. If TradingView cannot provide requested 15-second data, report acquisition failure instead of fabricating a payload.

## GPT intake
Run:
```text
python scripts/run_claude_tradingview_handoff.py <payload.json>
```
The intake fails closed for wrong symbol, wrong timezone, unavailable timeframe, invalid/non-finite OHLCV, or unusable routing.

The receipt records SHA-256 of raw input bytes, actual metadata, raw bar count, first/last timestamps, routing state, and session-quality counts.

## Evidence status
Claude MCP data without an independent Replay crosscheck is `READY_UNCROSSCHECKED` and is not promotion-grade evidence by itself.

Session quality remains separate:
- `ACCEPT`: eligible for downstream promotion evidence, subject to all other gates.
- `REVIEW`: research usable but not promotion eligible.
- `EXCLUDE`: excluded from research strategy results.

Even `ACCEPT` does not authorize LIVE trading. OOS, walk-forward, costs/slippage, risk gates and explicit production approval remain required.
