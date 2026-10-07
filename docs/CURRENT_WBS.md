# 100億PROJECT — CURRENT WBS
Updated: 2026-10-08 JST

## P0-1 V10 lifecycle closeout
Status: NEAR COMPLETE
Done: V10 START PASS / V10 STOP PASS / Excel no-save close / hidden orphan PID-limited cleanup / V8-V9 cleanup / local runtime cleanup.
Remaining acceptance: post-restart Brain full-state confirmation.
Definition of Done: START -> RUNNING -> STOP -> CLEAN -> RESTART; Brain confirms Gateway/Collector/Watcher/RSS Excel/Shadow/BRAIN LIVE; no unmanaged orphan; real_submit_allowed=false.

## P0-2 NEXT / HOT real-time lane
Status: NOT COMPLETE
Current defect: EVENT 5 is not true market-wide real-time detection.
Required lane: market-wide discovery -> short-interval candidate scoring -> HOT promotion -> dynamic live-watch promotion where possible -> live price/volume/VWAP/OR/EMA enrichment -> EVENT 5 ranking refresh -> stale/fail-closed -> theme/PR/earnings enrichment -> latency/coverage metrics -> Shadow performance log.
Definition of Done: new intraday momentum symbols can enter without manual fixed-list editing; freshness timestamp; exact data-source label; stale block; measurable detection latency; replay validation.

## P0-3 Data quality / Shadow evidence
Status: ACTIVE
Maintain Collector 28580 / Gateway 28581 / Watcher 28582 / Voice 28583 / Brain 28584. No real order submission. Persist data-quality state. Accumulate Shadow evidence. Block on conflicts/staleness.

## P1 Revenue lane
Status: UNDERWEIGHT / must not be starved
AIトレード日記 / Auto Publish / overseas distribution / monetization experiments. Record actual cash revenue, not projected value.

## Owner operation target
Nearly 0. Repeated manual PowerShell/debug loops are prohibited as normal operation.
