# AI Cockpit Autonomy North Star

## End state

AI Cockpit is not primarily an assistant that waits for the Owner to operate it.

The long-term target is an autonomous system that can carry the project forward while the Owner observes: acquire evidence, analyze markets, select only validated strategies, manage risk, execute only after the execution lane has earned permission, record outcomes, learn from measured results, prepare Japan-market JP/Global coverage, maintain the development loop, and turn sanitized history into Entertainment output.

The intended Owner experience is closer to **observer / governor** than operator.

## Autonomy ladder

1. **Observe** — collect and normalize evidence; fail closed on missing/stale data.
2. **Explain** — produce reproducible market/state interpretations with evidence.
3. **Simulate** — backtest and replay explicit strategies.
4. **Shadow** — generate decisions without sending orders; measure fills, MAE/MFE and failure modes.
5. **Controlled live** — only strategies and execution paths that pass predefined evidence/risk gates may become eligible for separately approved live operation.
6. **Autonomous operation** — target state: routine decisions, monitoring, journaling, evaluation and content preparation run without Owner micromanagement, while hard risk/kill-switch/governance boundaries remain.

Moving upward is earned by evidence, not ambition or narrative.

## What must become automatic

- local/market data acquisition and freshness checks
- market-regime and setup classification
- Strategy Lab evaluation and promotion/demotion
- position sizing and risk-budget calculation
- execution-quality measurement
- post-trade attribution, MAE/MFE and expectation-vs-result analysis
- regression detection and automatic fallback to safer states
- daily Japan-market JP/Global internal briefs even when the Owner does not trade
- sanitized diary/development/story-event generation
- Entertainment planning and editorial-quality checks
- overseas-community lead intake and verification queue
- compact mobile status and exception-only escalation

## Owner interaction target

Routine work should not require repeated “進めて” instructions.

The system should surface the Owner only for exceptions and boundaries that genuinely require human authority. The final UX goal is: AI Cockpit works; the Owner can watch, inspect evidence, and intervene when desired.

## Non-negotiable evidence boundary

The 10-billion-JPY dream is a long-term project goal, not evidence that a strategy works.

No autonomous lane may promote itself because of narrative importance, recent wins, confidence, or pressure to reach the goal. Trading autonomy must be gated by measured out-of-sample/shadow/live evidence, explicit loss/risk limits, deterministic audit records and a kill switch.

Current repository state remains research-first. This document does not activate broker submission, external publication, credentials, schedulers or private-data release.
