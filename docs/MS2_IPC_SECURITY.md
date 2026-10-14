# Issue #362 — offline IPC threat model and evidence boundary

Base: #361 / 48404f1d753cf6b5006f22e0e0cd6e81669f4806. DO NOT MERGE.

## Creation and admission

Windows CreateFileMappingW and CreateMutexW receive a protected, non-inheritable
security descriptor at creation. Owner is the current token user SID; only that
SID receives access. A successful syscall returning ERROR_ALREADY_EXISTS is a
collision, never a reason to adopt or repair that object. Python attaches its
view while the newly created native map handle is still held. No public-create
then-ACL-narrow interval is used by startup or the offline hold harness.
Worker and PS5.1 use open-existing Mutex, never create-on-attach. Both map and
Mutex ACL/owner are checked; PS uses .NET Framework GetAccessControl and
OpenExisting with ReadPermissions. Startup/API availability is validated in CI,
not assumed from PowerShell 7. Legacy ACL hardening helper remains solely for
existing explicit synthetic ACL tampering tests.

OS SID is principal authorization, NOT process authentication. Random map name
and generation are collision avoidance, NOT secrets. A hostile same-user process
can attach and tamper with a valid object/header/checksum. Privileged/elevated
attackers may take ownership/debug processes. These boundaries remain P0_BLOCKED.
Other-user real token attack is NOT VERIFIED until explicitly tested; an ACL
inspection alone must not be reported as an actual denied cross-user connection.
An existing object with a malicious same-user creator is not distinguishable by
owner SID alone. Producer admission against that attacker remains BLOCKED.

## Owner death and recovery

Spawned Worker uses multiprocessing's parent process sentinel (OS process handle
on Windows), not a guessed PID or kill(0). Parent death at a cooperative checkpoint
sets STOP|KILL and OWNER_DEAD_QUARANTINED and exits without draining pending slots.
Worker lease prevents restart while old worker remains. Normal stop only kills
the exact owned multiprocessing.Process; no scanning/killing unknown PIDs.
New owner uses a new map and generation, zero queue; no old map discovery/replay.
Actual synthetic owner hard-kill holds a pending slot, verifies flags/reason,
no JSONL, release of worker lease and clean new generation. Foreign pre-created
mapping bytes remain unchanged. Worker never unlinks the owner map.

An already executing disk syscall can finish after parent death. Uninterruptible
I/O cannot be cancelled safely here, and automatic recovery in that case is NOT
VERIFIED. A new owner must wait for verified worker lease release; no PID-based
forced orphan cleanup. Sleep/resume, power loss and clock discontinuity remain
NOT VERIFIED. This is not full production crash consistency acceptance.

## Performance

PS harness reports nearest-rank p50/p95/p99/max for packing, attach (including
ACL and Mutex open), lock acquisition and publish (including unlock); accepted
and queue-full submissions are separate. Startup and first packing/attach are
cold single samples. Three fresh sessions include a bounded synthetic background
CPU process in one run. No live board or private data is printed.

The old 101.3259ms maximum mixes 8 accepted and 192 queue-full calls. It cannot
identify a root cause without a trace. Cold JIT, reflection, SHA instantiation,
scheduling and allocation are hypotheses, not a proven explanation. Timings
are observations, not WCET or a hard 5ms bound. No tuning may weaken the envelope
or canonical record hash. Keep any future producer in a non-critical loop;
pricing/audio/signals and production promotion remain blocked.

## Safety

Watcher, 2048-byte record, canonical/hash semantics and 263 existing records are
unchanged. All fixtures are synthetic. real_submit_allowed=false;
promotion_eligible=false; statistical_edge_confirmed=false. Eligible N=0;
EV/PF/DD/profit UNKNOWN. CI evidence is reported per exact commit separately.
