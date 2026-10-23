# P0 MS2 Collector failure-isolation and data-quality boundary — offline acceptance v0.1

Issue: #376. This package contains **only an offline static-source risk inventory and pure synthetic policy model**, not a runtime fix. Main verified source SHA `d7e884fe9f641282701cd9d01381b38825672de5`. No changes to `MS2_RSS_100_Collector.ps1`, `Kioxia_RSS_Live_Watcher.ps1`, private CSVs, existing canonical/hash semantics, IPC Draft stack or owner PC.

## A. Confirmed source-level risks, not demonstrated runtime outages

- `ms2_live/MS2_RSS_100_Collector.ps1` has a single main `try { while ($true) { ... } } finally { ... }` loop. Its `New-Item` and multiple `Ensure-Csv` checks run in that loop.
- While iterating over up to 100 monitored symbols, it calls synchronous `Add-Content` for `ticks.csv` (before `$results +=...`), and the ordered `condition_log.csv` → `under_over.csv` → `market_snapshots.csv`. The latter is not an atomic 3-file transaction; partial files, stale/mismatched snapshots and partial writes are possible without a verifiable shared poll ID.
- In the same path, missing values for `volume,vwap,bid,ask,bidQty,askQty,marketSell,marketBuy,over,under` are replaced with numeric zero. The current CSV therefore does not preserve all missing-versus-observed-zero distinctions; old values MUST NOT be retroactively certified as observed zero.
- PowerShell `Add-Content` can report non-terminating errors depending on error action and exception type, and can block. **The current static audit does not prove that any specific write failure will throw or actually stop voice/price processing.** Such claims require PS5.1 fault injection. Synchronous `try/catch` alone cannot guarantee worst-case latency or handle uninterruptible disk I/O.
- The market record counts and signal counts already discovered are structure-level evidence only. Source/PIT and actual fill remain unverified.

## B. Required runtime architecture for a later *separately approved* Collector patch

**Critical loop**: market input → normalized observation with explicit `observed` / `missing_reason` and source time → signal hypothesis / monitoring state / risk and kill switch. No sync disk wait or file creation in this critical loop.

**Sidecar publisher**: bounded nonblocking transfer to a low-priority isolated persistence process. The entire producer boundary (serialization, IPC enqueue and exception handling) must have a measurable worst-case target; historical sub-5ms experiments have NOT established a real OS bound. Queue-full or unavailable writer ⇒ DROP/UNKNOWN evidence and suppression of *actionable* signals requiring verified sources, **not** silence of risk/kill/market-status monitoring. A nonresponsive producer must not be waited on indefinitely.

**Writer**: durable observed record / verified readback / explicit receipt vs queued-only / duplicate and stale generation reject; avoid replays after UNKNOWN, record lost or unverifiable ranges as NOT_CLOSED. Do not auto-promote `PERSISTENCE_CLAIM` to `PERSISTED_VERIFIED`. Leverage unmerged PR #379 pure receipt specification, but retain versioned boundaries without changing old canonical/hash or 2048-byte contract.

**Monitoring**: quote/price source missing must be separate from actual zero. Monitoring UI should show DEGRADED, data gate NO_TRADE. Critical price/voice/risk/kill *continue where permitted*, but the policy cannot require acting on unverified quotes or stale signals. On conflicts enforce fail-closed.

**Source identity**: immutable session+symbol+poll ID, producer hash proven by independent launch/supervisor record rather than self-asserted identity, offset-aware read-start/end/available/decision stamps. Per-poll same ID across condition/supply/snapshot if and only if they truly derive from that poll; no retrospective invention for old CSV.

## C. Synthetic acceptance & negative matrix

The offline `inspect_collector_source(text)` returns only fixed risk codes/counts, never original market data, source text or local path. It detects known direct writes, false-zero conversions, direct-write-before-render and sequential triplet; absence of detected signature results UNKNOWN, *not* a PASS of a modified Collector.

The pure `model_failure_boundary` demonstrates a **policy**, not actual PS5.1 or file durability. Scenarios include missing/zero/nonfinite price and volume, stale ages, source provenance missing, queue accepted but never persisted, claim without verified readback, prequeue DROP, writer REJECT, UNKNOWN, stopped feed. For all scenarios actionable trading stays prohibited and real-submit flags remain false; monitoring/risk/kill continuity remains an **unverified goal**.

Before a live patch is even considered:
1. Windows PowerShell 5.1 executable synthetic harness with **real fault-injected filesystem and process**, permission-denied, partial writes, disk-full simulation, queue-full, process kill and restart, stale/invalid quote; prove independently measured monitoring/signalling/risk continuity as appropriate, error/no-error behavior, loss/UNKNOWN accounting and last committed state.
2. Compare source count, saved count, durable receipts and corresponding poll IDs. A result with unknown or unrecoverable data is NOT_CLOSED and never counts as full observation coverage.
3. Tests under CPU/Excel background load for p50/p95/p99/max of critical loop and async submit, end-to-end write/readback separately. Real worst-case bound cannot be inferred from OS CI.
4. Stable Windows startup/stop including Excel workbooks, older instance/mutex collision, work Excel coexistence and recovery—W1–W4 must be observed on OWNER PC **only after separate authorization**.
5. Independent GPT source review, CI evidence and precise OWNER approval of any actual Collector/Watcher changes and main promotion. Do not silently add real_order APIs.

## D. Decision gate

Offline policy and source risk scanner may receive CONDITIONAL PASS if CI succeeds; **production and original data Q2/Q3 remain BLOCKED**. This PR is an evidence-driven implementation plan, not the fix. A bounded producer-to-Writer sidecar and fail-closed input differentiation are indispensable *before* real integration. Reuse existing pure contracts to avoid producing a second universe of receipts.

No OWNER PC operations, no Excel/MS2 startup, no Collector/Watcher code edits, no main merge, no real orders. `real_submit_allowed=false`, `promotion_eligible=false`, `statistical_edge_confirmed=false`; eligible trading N=0 and real EV/PF/DD/yen profit UNKNOWN.
