# Issue #382｜Native MS2 Writer Release Cut Evidence Gate v0.1

**OFFLINE SYNTHETIC / DO NOT MERGE / NOT PRODUCTION READY.**

## Existing implementation reused

Base: Draft PR #373 `work/issue372-native-concurrent`, HEAD at review `9861b9ed0acb375bbe137c5b485a670c3d1feffe`, a 14-PR unmerged IPC stack, not current main `faf4540260e0d91dc28484480304e99e36f2d7d7`. The producer is `tests/ms2_concurrent_producer.ps1` (real Windows PowerShell 5.1 process); the existing Bridge/isolated Worker/Writer comes from `scripts/ms2_ps_python_bridge.py`, `scripts/ms2_nonblocking_handoff.py` and `scripts/ms2_offline_observation_writer.py`. This is not the main MS2 Collector and must not become a second IPC implementation.

The previously implemented `tests/ms2_concurrent_pipeline.py` can observe an actual separate Writer doing JSONL append/fsync and the supervisor independently reading the published entire file, then imports only matching poll/session/generation identities into the immutable SQLite evidence ledger. Enqueue is merely QUEUED. Readback observation time is an upper bound, **not** the originally known disk commit instant. Evidence stages (QUEUED, DROPPED_PRE_QUEUE, REJECTED_POST_QUEUE, UNKNOWN_PENDING/TERMINAL, PERSISTED_VERIFIED) still have close_state NOT_CLOSED. Fsync is measured, but power-fail durability and hostile same-user tampering are NOT proven.

## New finite gate; no interface rewrite

`scripts/ms2_native_release_evidence_gate.py` consumes **only anonymous synthetic run aggregate results** and reports counts, reason codes, latency p99/max and fixed safety states. `tests/ms2_native_release_probe.py` calls the **existing** `run(normal,n=24,native=True)` under Windows; Linux calls same existing code in nonnative protocol fixture mode and explicitly refuses Windows PS5.1 evidence. It does not read OWNER data or activate Excel/MS2.

The gate checks (1) exact Native Windows PowerShell 5.1 origin of test process, (2) accepted + drops = attempted, (3) accepted count = Writer published independently validated readback count, (4) real Writer overlap and restart-new-generation-no-replay evidence, (5) nonempty fsync/readback/upper-bound timing cohorts, (6) normal-condition DROP=0, (7) steady full boundary measured max <=5ms with explicit cohort N, (8) no PID/session/market identity or source timestamps inferred from this synthetic run. **Even a hypothetical perfect run is still NOT source authenticated, NOT PIT eligible, NOT Shadow Forward eligible and NOT real submit allowed.**

A green test here means the gate correctly interprets synthetic evidence, **NOT** that the release gate passed. In the source `report` returned by #373, production='P0_BLOCKED', five_ms='NOT_MET' and receipt_tail='NOT_CLOSED' are expected. The gate outputs release_eligible=false, real_submit_allowed=false, promotion_eligible=false, statistical_edge_confirmed=false and eligible_observed_n=0 unconditionally.

## Explicit blocker / STOP boundaries

Do not relax the 5ms max target to p99 or claim no dropped polls if the count is >0. In #383's different disposable ring, normal condition had 9/120 drops and 8.9343ms max (first run 8/120, 58.57ms): **not** sufficient for production; not directly comparable with this different existing IPC/Writer pipeline. Native process creation and first warmup are separate. Logs and CI must report if measured N=0 rather than impute a favorable value.

Actual Collector source has synchronous CSV and JSON writes, daily folders/headers, Excel COM waits and voice/network calls. #381 only catches finite CSV append failures. This PR does not remove those waits; the broader Collector nonblocking P0 stays blocked. The session/code SHA, available_at, missing/stale data, source truth/market hours, native OS authentication, power failure, Windows Owner W1-W4 and actual production volume are NOT verified.

All test inputs are synthesized. All changes are new files, no canonical 2048-byte record/hash, existing IPC, Collector, Watcher, broker, private CSV, OWNER PC, main branch or production changes. No merges or real orders.

**Next decision after CI**: select a minimal existing-IPC Release Cut to cover an actual isolated private market-data Writer, then seek separate explicit OWNER approval before actual Collector wiring and Windows private live use. If normal-phase DROP persists, fix throughput/queue backpressure through an independently reviewed small patch without replaying UNKNOWN or coupling monitor to Writer. Evidence N for real eligible trading remains zero and EV/PF/DD/net profit/¥10 billion remaining UNKNOWN.



## Bounded correlated latency repeat, 2026-10-15 (synthetic ONLY)

The Native Windows fixture reports timings correlated for the same slowest steady ACCEPTED poll. Its capture_ms is synthetic stamp preparation, packing_ms is PowerShell payload conversion, submit_ms is native IPC submission; unattributed_ms is the residual of full_ms minus the measured stages. The largest measured component is NOT proof of its OS root cause. No original ticker, market time, payload, digest or private path is emitted.

Windows runs 3 fresh isolated synthetic sessions x 48 attempted observations; Linux one protocol-only session x 24. Each returns anonymous N, normal DROP, fsync/readback evidence and independent cold/first/steady metrics. Separate-stage aggregate maxima from different polls MUST NOT be added or declared the cause of the full maximum. The signal and critical real Collector are not part of this test.

A green workflow means a valid classification, not a production release. Any normal DROP, max>5ms, missing timing evidence or readback discrepancy is explicitly recorded. Even repeated max<=5ms is NOT an OS worst-case execution-time proof. Preserve the prior 24-attempt Windows max 51.9509ms/zero DROP as an independent failed performance result.

Finite stop rule: after three Windows cohorts, document actual stage-correlated results and unresolved tail. Do not endlessly repeat synthetic benchmarks. Proceed next to a separately approved plan for a minimal private, point-in-time Collector-to-existing-Writer data capture route rather than proliferating IPC.

All real submission, promotion, live source authentication, production acceptance and finance statistics remain blocked/UNKNOWN. This is not permission to start MS2/Excel, operate OWNER PC, merge main or edit the live Collector.

## 2026-10-15｜Single-function PowerShell pack micro-optimization; STRICT compatibility gate

At review, main `b0680d2c27ce83c2f0b7c0d63dc32fbb70be5fea` is newer than this unmerged stacked Draft's base. The single function `ConvertTo-Ms2PsBridgeRecord` has been changed **only in the Draft** to allocate its four immutable level-field descriptors once per capture (rather than once per book depth) and to append rows to a typed `List[hashtable]` instead of recreating an array. This is a candidate optimization, **not a verified performance improvement or an approval to rebase/merge/deploy**.

The exact unmodified baseline is PR #373 HEAD `9861b9ed0acb375bbe137c5b485a670c3d1feffe`, original blob SHA `9f053c73235635bf87bad86652d12109662455f9`. `tests/ms2_native_pack_byte_parity.ps1` retrieves this pinned historical source through local Git checkout history, executes baseline and candidate `ConvertTo-Ms2PsBridgeRecord` definitions with synthetic captures, and **compares all 2048 output bytes (via base64) and the full refusal reason**; no in-market source, private records, MS2, Excel or Windows Owner PC are used. The suite covers 1/5/10/0-depth, true quantity zero versus missing, fractional/Unicode, timestamp formatting, watcher-source refusal, duplicate/sparse levels and negative/NaN/string values. All tests are fail-closed: one mismatched byte or changed refusal aborts CI.

A 35×10-depth coarse timing sample is **diagnostic only**; it does not replace 3×48-run real isolated Writer tests, it cannot certify 5ms WCET or power-loss durability and it must never infer PowerShell pack as OS-level root cause. The Native real-source path is still NOT connected; Q2 source authentication, Q3 PIT, lossless session accounting, Excel COM, stop/restart W1-W4 and long-tail reliability are blocked. New files only for parity harness / CI; canonical/hash semantics intentionally unchanged.

**STOP RULE**: If pinned baseline parity fails, revert the optimization; never modify canonical record bytes to obtain a speed gain, never relax 5ms target. Even with full CI green, owner permission is separately required to touch real Collector, OWNER PC or main. No real orders; `real_submit_allowed=false`, `promotion_eligible=false`, `statistical_edge_confirmed=false`.
