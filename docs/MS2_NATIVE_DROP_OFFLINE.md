# Issue 368 — synthetic only / DO NOT MERGE

Native PowerShell 5.1 generates a synthetic sequential capture, calls the
unchanged canonical 2048-byte packer, and attaches once to the preinitialized
existing Bridge. The separate existing Writer performs private JSONL saving.
The supervisor lowers the Writer's priority before starting PowerShell.
This exercises the native Bridge path; it does **not** replace #367's Python
fixed-copy ingress or prove a native connection to that anonymous mapping.
No Watcher modification, Excel/MS2/COM call, account data, or real order.

Read-only Watcher trace: `ms2_live/Kioxia_RSS_Live_Watcher.ps1` sets `$now`
before sequential price/tick/board reads around lines 586–602. Board formulas
are assigned at 443–448; this is not an atomic exchange snapshot. Synthetic
read-start/read-finish/per-level timestamps explicitly represent sequential
reads. Poll ordering is POLL, snapshot_atomic=false, event_time and
available_at are absent. Missing bid quantity remains null; explicit ask zero
is preserved. Synthetic records remain NOT_CLOSED and eligible N=0.

## DROP evidence contract

Separate 1024-byte evidence mapping, owned and retained by the supervisor.
It does not change the market payload, queue envelope or hash semantics.
One PowerShell producer per session, seqlock odd before capture, even after
reason counters, poll span and first/last UTC Unix-millisecond event clocks.
Clocks may regress: an invalid snapshot is refused, not normalized.
Counter/sequence regression, inconsistent totals, torn generation/update
are rejected. Ranges are bounds, **not** assertions that every poll in the
range dropped. Individual poll identities are not retained.

Supervisor commits OPEN before launching the producer. Every approximately
10ms it snapshots without locking the producer and writes same-directory
temporary JSON, flush/fsync, atomic replace (POSIX directory fsync).
On producer death it commits the last consistent counters with UNKNOWN tail.
If killed in an odd update, the last complete checkpoint remains a lower
bound. A DROP between checkpoints survives producer death when the supervisor
can still read the retained map; supervisor/disk/IPC failure can lose detail.
OPEN/RUNNING checkpoints and missing/corrupt checkpoints never mean no gaps.
Power-loss durability, Windows directory metadata durability, fsync honesty
of storage hardware and simultaneous supervisor/producer death are unproven.

Recovery is read-only and idempotent. Hash-verified checkpoint is read once;
unpublished partial `.tmp` is not promoted; a truncated/tampered published
checkpoint becomes BLOCKED/UNKNOWN. No old observation or counter replay.
New generation gets a new session/file/map. Hash protects accidental corruption,
not hostile same-user rewriting. Single-producer exclusivity is an offline
launcher invariant, not process authentication; same-user IPC remains P0_BLOCKED.
Windows evidence-map ACL isolation from real other users is NOT VERIFIED.

READY is preinitialized Bridge availability. ACCEPTED means queued only.
DROP has a reason counter; verified snapshot is GAP_EVIDENCE. Durable JSONL
reread and Writer durable counter provide PERSISTED evidence separately.
Neither elevates a synthetic or incomplete capture to CLOSED. STOP/kill are
explicit drops; shutdown that cannot prove Writer exit remains STOP_PENDING
or BLOCKED per inherited lifecycle. Ledger persistence is not on the
PowerShell critical loop. CPU/memory/OS scheduling still interfere.

## Measurements / limits

`python -m tests.ms2_native_drop_benchmark` on Windows launches real PS5.1.
N=100 per condition, nearest-rank p50/p95/p99/max, ACCEPTED/DROP separated.
Full boundary includes capture, packing, bridge submit and shared-evidence
updates. Capture/packing/submit separately reported. Attach is outside loop;
cold start includes Bridge/Writer spawn only, excludes PS startup/Add-Type.
Disk checkpoints and final downstream persistence wait are separate measures,
not per-record end-to-end latency. Full process cold start is NOT VERIFIED.
Mock price/audio/signal loop spacing includes benchmark pacing and scheduling;
no real audio/price service accuracy or hard real-time claim. 5ms hard maximum
is NOT MET unless proven; this work always keeps production P0_BLOCKED.

Actual queue-full, busy shared gate, kill switch, Writer kill, old generation,
corrupt header and PS hard-kill before capture/after acceptance are tested.
NOT_READY/STALE/INVALID/STOP are synthetic refusal branches, not real sensor
or IPC readiness detection. In particular a stalled Writer could accept into
the existing queue before the inherited watchdog refuses; NOT_CLOSED applies.
Real uncancellable OS I/O and entire-machine CPU saturation remain unverified.
Inherited partial-JSONL/owner/worker kill tests must also pass; new evidence
checkpoint partial-write/before-replace faults include actual supervisor-process
hard kill; they do not prove OS kill or cancellation inside fsync.

real_submit_allowed=false; promotion_eligible=false;
statistical_edge_confirmed=false. OWNER PC W1–W4 NOT VERIFIED.
