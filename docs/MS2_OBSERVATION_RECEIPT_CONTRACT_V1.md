# MS2 Observation & Receipt Contract v0.1 — Issue #376

Status: **OFFLINE SYNTHETIC / DESIGN ONLY**. Does not integrate with MS2 RSS, Windows Excel, the real Collector, existing CSVs, any broker, or live execution. Not a canonical-contract or historical-data migration. Reviewed starting main: `d7e884fe9f641282701cd9d01381b38825672de5`.

## Why this is needed

Existing `MS2_RSS_100_Collector.ps1` writes `market_snapshots.csv`, `condition_log.csv`, `under_over.csv` sequentially without a shared durable poll identifier or demonstrable `available_at`. An existing day of `records` passed the Q1 read-only structural check, but Q2 genuine source identity and Q3 point-in-time eligibility have not been established. A later CSV match on ticker+local-second is ambiguous. Old data must retain UNKNOWN rather than receive invented provenance.

## Future independent sidecar schema, NOT a change to existing 2048-byte/canonical record

**Capture** (exact fields): `schema_version="ms2-observation-receipt-0.1"`, `producer_sha` (40 lowercase hex source-code identifier; NOT an identity proof), `session_id` (32 lowercase hex, generated once per process session), `poll_seq` (strict positive int, increasing within a session), private local `symbol`, `stream` (MARKET_SNAPSHOT, CONDITION, UNDER_OVER, or SIGNAL), `record_sha256` (64 lowercase hex of producer-defined payload; integrity identifier, NOT authenticity), `read_started_at`, `read_finished_at`, `available_at`, `created_at`.

All timestamps must be offset-aware RFC3339, with explicit precision and semantics. Semantics require `read_started_at <= read_finished_at <= available_at <= created_at` as a structural candidate, **not proof** the producer observed these times correctly. An exchange event time is separate, never inferred from read completion or local captured_at. UTC offsets must compare as instants. Source health reuses the existing main `local-source-health-1.0` contract, including HEALTHY, consecutive_failures=0, last_data_at present and not later than health observed_at. A self-reported HEALTHY does not constitute independent source attestation.

**Receipt** (exact fields): `schema_version, session_id, poll_seq, symbol, stream, record_sha256, phase, at`. Allowed phases are `PRE_QUEUE_DROP`, `QUEUED`, `POST_QUEUE_REJECT`, `PERSISTENCE_CLAIM`. Receipt identity must match the capture. QUEUED→PERSISTENCE_CLAIM or QUEUED→POST_QUEUE_REJECT is structurally allowed. PRE_QUEUE_DROP is terminal; crossing it with QUEUED/rejection/claim is a conflict. Claim/rejection without queue, duplicate phase with different times, gaps, wrong record SHA, missing stream or receipt remain **BLOCKED**. Exact repeat is idempotent.

**Critically: PERSISTENCE_CLAIM is an untrusted claim, not a confirmed write.** True `PERSISTED_VERIFIED` requires an independent, crash-consistent disk artifact, writer fsync, and identity-bound readback verification; this contract does NONE of those. UNKNOWN/queued with no completion must remain unknown, never promoted by elapsed time, restarts, or inference.

**Optional decision manifest**: `schema_version="ms2-observation-decision-0.1"`, `session_id, poll_seq, symbol, decision_at, input_streams`. Strict as-of check refuses features created/available after decision time and missing/unclaimed referenced records. Passing that ordering check cannot prove no lookahead: actual feature dependencies, clock synchronization, market data source time and readback are still unverified.

## Output and safety boundaries

The pure function `scripts/ms2_observation_receipt_contract.evaluate(captures,receipts,health_snapshot,decisions)` reports fixed status/reason/receipt-state counts. It NEVER outputs symbols, prices, quantities, raw rows, producer SHA, source digest, session IDs, PC paths or original timestamps. No filesystem, network, Excel or subprocess actions. Data inputs in CI are **synthetic only**. `STRUCTURALLY_CONSISTENT_UNATTESTED` means only well-formed, nonconflicting self-reported evidence and NEVER Q2 authenticated, Q3 PIT eligible, verified persistence, fill, real expectancy or live readiness. Failure → BLOCKED. No source means UNKNOWN.

Always outputs `source_authenticated=false`, `shared_poll_durability_proven=false`, `persisted_verified=false`, `decision_asof_proven=false`, `pit_research_eligible=false`, `shadow_forward_eligible=false`, `performance_eligible=false`, `eligible_observed_n=0`, `real_submit_allowed=false`, `promotion_eligible=false`, `statistical_edge_confirmed=false`.

## Real-system acceptance — requires a separate explicit OWNER approval

A future Collector-integrated version MUST first pass separately reviewed owner-GitHub/Windows acceptance, including:

1. Collector actually running SHA/launch params/identity attested, generated session nonce and per-poll symbol ID bound to the **same sampled data** across outputs. Self-declared hash by itself is insufficient. Do not update old `records` to fake these fields.
2. Source-side start/end/available timing proven against calibrated timezone/clock uncertainty; feature generation/decision time and dependent source observations fixed, no lookahead. Poll sequence handling under restarts/session changes, missing/stale/duplicate must fail closed.
3. Real queue producer/worker ack and independently verified writer readback with fsync, stable file, generation/owner/crash fencing and conflict handling. UNKNOWN cannot be replayed/resubmitted automatically.
4. Nonblocking critical price/voice/signal loop, measured worst-case latency; preservation of existing canonical/hash/2048-byte semantics. Legacy Watcher write error isolation is a separate issue; no unsafe modification here.
5. Private raw records stay on OWNER PC/private store. Public GitHub contains only code, synthetic fixture and anonymous aggregate metadata. No live MS2/Excel integration, Collector/Watcher edit, main merge or actual order permitted by this Draft.
6. Research sources for earnings run-up/earnings hold, 2X/10X growth, market regimes and futures/SQ hedge remain independent time-versioned data contracts. MS2 alone cannot support real EV for these.

## Test plan and gate

Windows and Linux, Python 3.11/3.12 synthetic-only unittest validates healthy complete claim as UNATTESTED, missing required streams/receipt, queued unknown, drop/rejection, premature or conflicting claims, generation/session SHA conflict, time zone/future timestamps, health status, missing decision input, cross-offset order, duplicate exact idempotency and no private data in the output. Exact-head CI plus independent GPT review needed for offline acceptance.

No real market files accessed, no runtime startup, no main modifications, **DO NOT MERGE** until explicit OWNER authorization. Real eligible N=0, EV/PF/DD/realized profit/¥10bn remaining UNKNOWN.
