# 100億PROJECT — CURRENT WBS
Updated: 2026-10-08 JST

## P0-1 Brain continuous edge engine
Status: SPECIFICATION CREATED / IMPLEMENTATION NOT STARTED
Canonical spec: docs/BRAIN_CONTINUOUS_EDGE_DISCOVERY_REALTIME_SIGNAL_SPEC_V1.md
Objective: 365-day continuous strategy discovery -> normalization -> point-in-time validation -> context-specific Champion/Challenger -> realtime best-symbol LONG/SHORT/NO-TRADE signal -> attributed Shadow feedback.
Critical rule: no fixed 8-strategy roster; strategies are evidence-driven and dynamically added/demoted/retired/inverted.
Definition of Done: Brain can answer current best symbol/side/strategy/EV/PF/N/context/expiry/latency and preserve full lineage to Shadow evidence with no Owner manual analysis.
Safety: real_submit_allowed=false.

## P0-2 Strategy PF attribution / inverse Shadow
Status: SPECIFICATION CREATED / IMPLEMENTATION NOT STARTED
Canonical spec: docs/STRATEGY_PF_ATTRIBUTION_INVERSE_SHADOW_SPEC_V1.md
Required: every Shadow trade links to Brain decision -> strategy_id -> signal -> NORMAL/INVERSE; daily and rolling PF/EV/N/DD/MFE/MAE rankings; strongest inverse candidate.

## P0-3 NEXT / HOT real-time lane
Status: NOT COMPLETE
Current defect: EVENT 5 is not true market-wide real-time detection.
Required lane: market-wide discovery -> short-interval candidate scoring -> HOT promotion -> dynamic live-watch promotion where possible -> live price/volume/VWAP/OR/EMA enrichment -> EVENT 5 ranking refresh -> stale/fail-closed -> theme/PR/earnings enrichment -> latency/coverage metrics -> Shadow performance log.
Role in Brain: candidate-universe discovery input to the realtime selector, not an independent final decision authority.
Definition of Done: new intraday momentum symbols can enter without manual fixed-list editing; freshness timestamp; exact data-source label; stale block; measurable detection latency; replay validation.

## P0-4 V10 lifecycle closeout / data quality
Status: NEAR COMPLETE / ACTIVE
Done: V10 START PASS / V10 STOP PASS / Excel no-save close / hidden orphan PID-limited cleanup / V8-V9 cleanup / local runtime cleanup.
Remaining acceptance: post-restart Brain full-state confirmation.
Maintain Collector 28580 / Gateway 28581 / Watcher 28582 / Voice 28583 / Brain 28584.
No real order submission. Persist data-quality state. Block on conflicts/staleness.

## P1 Revenue lane
Status: UNDERWEIGHT / must not be starved
AIトレード日記 / Auto Publish / overseas distribution / monetization experiments. Record actual cash revenue, not projected value.

## Owner operation target
Nearly 0. Repeated manual PowerShell/debug loops are prohibited as normal operation.
