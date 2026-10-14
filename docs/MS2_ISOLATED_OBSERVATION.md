# Issue 366: offline isolation prototype — production P0 BLOCKED

Audit main e3a1d877cdb1d5fa54c1b99dd45f25a9c0f402ab; Pages
38515840614 SUCCESS (not IPC acceptance). Base Draft #365
ff1fa0fa63684217a87c3b0ae7eefce3a2a4f7b9, tree
606062dea160914b9e87deef910c834c386dadae, stacked on #363.
Read #282 through 6161360779 and independent #365 review 6161461988.
Inspected all heads/bases #347→349→351→353→355→358→360→361→363→365.
#365 E2E/Bridge/Mobile/Queue all SUCCESS; no production PASS inferred.

## Exact topology

Offline launcher, outside critical loop, allocates inherited anonymous raw
buffers and one semaphore, creates a generation, starts B Consumer.
A synthetic single-PID/single-thread producer owns fixed-copy Ingress and
local counters. B starts/owns existing Bridge and Writer child, performs
canonical validation, SHA-envelope publication, private I/O, control and stop.
Both B processes request below-normal Windows priority / Linux nice 10;
actual achieved priority is reported, never assumed.

offer() accepts immutable 2048-byte canonical fixtures prepared OUTSIDE A,
checks primitive types/freshness/PID/thread/generation, acquire(False) once,
copies 2048 bytes, calculates CRC32 and commits sequence. No spawn, attach,
JSON, canonical packing, SHA, disk, sleep, join, pipe send/recv, liveness
syscall or retry in A. CRC32 and semaphore are synchronous fixed-size work;
OS scheduling/page faults remain unbounded. No WCET/5ms guarantee.

NOT a native PowerShell producer or live Watcher adapter. Real acquisition
outside A with zero extra COM reads is unresolved. PS5.1 harness launches
Python measurement; cannot be reported as native PS Watcher latency.
Read-only Watcher trace: board lines 601–602, display 658–683, signals
703–819, JSON 864, voice 869–872, final sleep 2 seconds. Existing synchronous
COM/log/JSON work is unchanged. Tests use price/voice/signal mock counters.

## Identity and fail-closed behavior

Synthetic launcher/A/B/Writer use same CI account SID/session. Inherited
handles reduce named attach surface but are NOT security against hostile
same-user handle duplication or code/file modification. PID/thread/session,
generation and CRC are integrity checks, NOT process authentication. Existing
named Bridge retains the demonstrated same-user vulnerability from #365.
Default disabled; enabled with required auth refuses before allocation:
SAME_USER_AUTH_UNRESOLVED / P0_BLOCKED. Tests explicitly opt out offline.
Restricted service identity, private ACL storage, authenticated admission and
trusted capture ownership are design requirements, NOT implemented. No secrets.

Full/busy/stop/kill/stale/bad input/old generation produce DROP without waiting.
Consumed polls cannot be retried. B rejects torn/CRC-corrupt/ABA/stale/poll
mismatch slots, consumes without replay, refuses unhealthy Writer. ACCEPTED
means ingress copy ONLY, not durability/completeness. B can separately refuse
or drop downstream. Stop discards pending ingress. Abandoned semaphore can
leave B in STOP_PENDING; A keeps GATE_BUSY dropping, never releases foreign
ownership. No unknown PID kill or foreign IPC deletion.

Producer audit is fixed-space per reason: exact count and first/last
MONOTONIC_SESSION timestamp/poll range. B refusals have counts and first/last
decision times. Audit/control/report JSON happens outside A. Abrupt A exit
loses local counters: **no durable per-event loss ledger**. First/last ranges
cannot enumerate each missing poll. Monotonic timestamps are not fabricated
market available_at. Evidence completeness therefore remains BLOCKED.
Missing qty remains missing, poll_seq=POLL, snapshot_atomic=false,
available_at unknown, NOT_CLOSED, real eligible N=0. Writable same-user forging
valid CRC is outside integrity's guarantee.

## Tests and limitations

New 15 transition tests: normal durability/missing qty/explicit zero;
default/auth refusal; exact full/drop counts and no retry; abandoned gate;
STOP/KILL/stale/invalid/generation; duplicate spawned producer; torn/ABA/CRC/
stale slot consumption; Consumer hard-kill/orphan fence and mock continuation;
Writer kill; simulated partial write kill with original JSONL preserved;
STOP_PENDING held gate; AST inspection of A's excluded operations.
Inherited suite covers owner kill before/after replace, partial write,
Worker orphan, lease restart refusal, old generations, duplicate sessions,
gap/stale/missing, private JSONL integrity, same-user attack/refusal and byte
pins. Existing 263/history, Writer, payload/canonical/hash source UNCHANGED.
Synthetic kill of a paused writer does NOT prove real uninterruptible OS I/O
cancellation, atomic parent-check/replace, power loss, sleep/resume, other-user
attack or OWNER PC W1–W4. Those remain NOT VERIFIED / P0 BLOCKED.

Local Linux 170 tests OK (6 Windows-only skip), including 15 new. Initial
local failures came from incomplete downloaded dependency files and extra
newline from text materialization; exact base64 bytes restored and complete
pins fetched; tests unchanged. No protected dependency changes are published.
Remote exact-head Windows/Linux CI is authoritative; failures cannot be
hidden by local green. No threshold increase or assertion weakening.

## Measurement

N300 attempts each: steady, CPU contention, full queue, stopped Writer,
recovery, stale Consumer. Cold launch N3. Immutable fixtures prepacked outside
A. Drain/Writer completion waits are outside offer timings. Steady waits for
completion to avoid full queues. Two CPU-busy children = contention, not
all-core saturation proof. Nearest-rank p50/p95/p99/max reported separately
for ACCEPTED/DROP with N and reason. N3 cold/N8 full accepted are weak tail
samples. Timers include call overhead. Local steady accepted N300 and durable
N300; downstream failures/drop recorded separately. Artifacts contain only
synthetic aggregates; actual private records stay in temporary directories.
Final Windows PS5.1 orchestration/Python results belong in Issue evidence.
No PS-native benchmark or Watcher integration is claimed.

real_submit_allowed=false; promotion_eligible=false;
statistical_edge_confirmed=false; real N=0; EV/PF/DD/economics UNKNOWN.
DO NOT MERGE. No live connection/COM/autostart/OWNER PC/orders/promotion.
Watcher edits, live connection, main merge need separate authorization.
