# Issue #370: offline poll reconciliation

Scope: synthetic only. New Draft stacked on #369. No Watcher, COM, main merge,
MS2/Excel, Owner PC, order, autostart, canonical/hash or record-size change.
Existing 263 historical rows stay unchanged. All safety flags false, eligible
real N=0, EV/PF/DD UNKNOWN. Production P0 BLOCKED.

## Evidence contract

The supervisor records immutable events keyed by session_id/generation/poll_seq.
Payload identity is SHA256 of the existing Writer's complete canonical JSON
record, obtained by unchanged `build_captured_record(unpack_capture(blob))`.
This is a NEW audit identity, not a change to existing execution/hash semantics.
source_digest binds the synthetic receipt/readback bytes; hashes do not establish
hostile same-user authentication. Callers must supply measured timezone-aware
clock values. queued_at is measured receipt evidence; persisted_at is the
observed readback upper bound, NOT an invented original commit timestamp.
No available_at, price, quantity, exchange clock or fill is inferred.

| Evidence | Reconciliation | Closing state |
|---|---|---|
| QUEUED receipt only | UNKNOWN_PENDING | NOT_CLOSED |
| Same validated published Writer row + QUEUED identity | PERSISTED_VERIFIED | NOT_CLOSED |
| Explicit prequeue refusal | DROPPED_PRE_QUEUE | NOT_CLOSED |
| Explicit Writer refusal + receipt | REJECTED_POST_QUEUE | NOT_CLOSED |
| Time window ended / crash without row or refusal | UNKNOWN_TERMINAL | NOT_CLOSED |
| Conflicting identity, drop/save or reject/save | fail-closed UNKNOWN_TERMINAL | NOT_CLOSED |

QUEUED remains an immutable evidence stage. UNKNOWN_TERMINAL means the audit
window ended; permanent_loss_proven stays false. Subsequent readback in the same
session may resolve it. A new generation never consumes old receipts. PIT
queries filter evidence by measured observed_at; conflicts conservatively block
the affected poll even when reviewing an earlier point. Original market rows
are neither enriched nor modified by reconciliation.

## Durability and recovery

SQLite DELETE journal + synchronous FULL; transactionally serialize receipt and
conflict checks. INSERT OR IGNORE uses deterministic event digests. Update/delete
of events and conflicts is rejected by SQLite triggers. Event hashes are rechecked
on reads. A killed process with an uncommitted transaction rolls back on recovery.
JSON checkpoints are deterministic disposable views, fsynced then replaced.
Leftover partial temp checkpoints are quarantined. A stale checkpoint never
proves persistence or overrides the committed database. Disk refusal preserves
existing evidence and keeps unknowns. No synchronous audit write occurs in the
Watcher or measured PS capture/packing/submit boundary.

Not a power-loss certificate. Hostile same-user file replacement, owner→replace
TOCTOU, real uninterruptible OS I/O, simultaneous IPC/disk disappearance, genuine
sleep/resume and Owner-PC W1-W4 are BLOCKED/NOT VERIFIED. Windows directory-fsync
is not certified. Caller provenance must remain trusted in these offline tests.

## Exact-shape replay

Evidence fixtures and a real spawned unchanged Writer induce 83→80,79→77,8→0.
The writer pauses after the specified count; published JSONL is validated and
reread by poll identity. 8→0 additionally verifies a real bounded queue refuses
another enqueue while full. Hard-kill leaves 3,2,8 UNKNOWN_TERMINAL; no permanent
loss claim. Release/resume yields 83,79,8 PERSISTED_VERIFIED in the same generation,
while a query at the pause timestamp still sees 80,77,0. A fresh generation is
empty and does not replay the old queue.

These are controlled fault replays, NOT forensic recovery of the actual earlier
#369 missing polls. That historical report contained counts rather than complete
poll receipts and worker outcomes. Their exact root causes remain NOT VERIFIED.
Inherited tests exercise actual PS producer hard-kill, worker hard-kill, STOP,
KILL, partial publication, stale generation, duplicates and disk faults. New tests
cover partial/tampered readback, conflicting evidence, SQLite process death,
checkpoint interruption, disk-write refusal, PIT, and immutable/idempotent events.

## Native PS5.1 measurement

A standalone unchanged Bridge IPC fixture separates producer latency from disk.
A preinitialized supervisor drains immutable copied records; no Writer watchdog
runs in this fixture, so the deliberately held gate measures PRODUCER_BUSY only.
It is NOT the #367 anonymous ingress, live Watcher or production pipeline.
First warmup includes first pack and IPC/JIT. Native cold start is process launch
to readiness (includes compilation, attach and warmup), not an independent cost
that can be added to warmup. Remaining samples are steady cohorts, separated by
ACCEPTED, DROP_NEWEST and PRODUCER_BUSY. Each contains price/audio/signal mocks,
capture, packing, IPC submit and full boundary wall times. Serialization of the
synthetic-only diagnostic record is after the measured boundary, in memory.
The supervisor consumes raw synthetic diagnostics privately and prints aggregates
only. No actual private market data is read or published.

The unchanged Writer subsequently persists drained records outside the producer
loop. Writer save completion, validated readback/ledger import and checkpoint are
separate wall-time distributions. This does NOT measure concurrent PS→production
Writer enqueue-to-fsync latency; that path remains NOT VERIFIED. Two CPU background
processes create contention; CPU saturation is NOT VERIFIED. Stopwatch percentiles
use nearest rank. N/p50/p95/p99/max are reported for each nonempty cohort; N=0
means NOT MEASURED, never zero latency. Cold/warmup N=1 per fixture is explicitly
small. A finite synthetic run cannot guarantee a maximum 5ms: always NOT_MET.

Run: `python -m unittest tests.test_ms2_poll_reconciliation tests.test_ms2_poll_latency`
Replay: `python -m tests.ms2_poll_fault_replay`
Native aggregates: `python -m tests.ms2_poll_latency --output poll-latency.json`
Exact-HEAD Windows/Linux CI also runs inherited E2E, Writer and canonical tests.
