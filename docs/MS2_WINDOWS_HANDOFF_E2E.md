# Issue #359: offline Windows bridge to durable JSONL

Basis: main `dd06571d80d0d228d54aae5cb5f7d6751ba68160`, Draft #358
`4910f11dd8bdc03782463b68dce447684dd505c3`. Draft stack
#347 → #349 → #351 → #353 → #355 → #358 is preserved; this PR targets #358.
Main has not changed the Watcher since the stack fork. Contract/writer files
are additions on the draft stack, not deployed main functionality.

## Root cause and connection

Both the handoff module and bridge lifecycle used POSIX-only `fcntl`.
Bridge now transfers the handles of the existing handoff session instead of
implementing another startup/lock path. Both entrypoints acquire the same
private `runtime/handoff.lock`. Worker holds `runtime/worker.lock` until exit.
They reuse #358 `_lock_native` / `_unlock_native`: nonblocking LockFileEx on
Windows, nonblocking flock on POSIX. No unbounded lock wait or retry.

An already copied 2048-byte PowerShell record uses the unchanged NBH1 packing,
4096-byte slot base, capacity 8, and little-endian 64-bit header offsets.
The same spawned `_worker_entry` consumes it through existing
`record_captured_observation`. No additional writer, COM read, file IO,
process creation or pipe is added to PowerShell submission or the Watcher.

Startup validates private destination/reparse paths, acquires the owner lock,
probes the worker lease, quarantines unpublished files while holding #358's
writer lock, creates a fresh uniquely named map, stamps its protocol/generation,
then spawns once. Readiness deadline is two seconds. Failures close owned
handles; an existing map is refused, never attached, cleared or unlinked.
Only a creating owner unlinks its POSIX map. An attached Worker closes only.
On Windows there is no unlink call: the map survives until the last handle
closes. An old attached map is never replayed by a fresh session.

If an owner crashes while its Worker remains alive/hung, that Worker retains
its lease and a new owner is refused. We do not kill an unknown PID, remove
someone else's map, or claim automatic orphan recovery. After the known
Worker exits, restart uses a fresh map/generation and discards unpublished
spill. Safe automatic orphan recovery is NOT VERIFIED. The lease-loss test
models OS owner-lock release; it is not a power failure test.

Header/protocol, generation and queue-index contradictions stop the Worker
fail-closed and latch the kill flag. Invalid packed records cannot persist.
This does NOT prove absence of plausible torn slots, concurrent producer
races, ABA, same-user hostile attachments or map ACL restrictions: Issue #356
remains a blocking gate. Existing packing/hash/canonical semantics are unchanged.

## Evidence boundaries

`MS2 Windows Handoff E2E` runs the same 131-test suite on Windows and Linux.
Windows additionally executes Windows PowerShell 5.1 in the E2E test and the
existing packing/mapping fault script. The E2E rereads the resulting private
JSONL and checks null/zero quantities, absent event/availability clocks,
POLL, snapshot_atomic=false, NOT_CLOSED, N=0, and byte-identical duplicate
restart. Only aggregates are printed. All fixtures are synthetic.

Inherited #358 tests cover injected ENOSPC, actual competing writer lock,
Windows open-handle replace failure, crash before replace, leftover temp,
corrupt JSONL and deterministic replay. Handoff tests cover worker crash,
hang, queue full, kill switch, missing/contradictory clocks, stale/gap and
invalid quantities. Added tests cover spawn failure, map collision without
foreign deletion, common owner lease, retained orphan worker lease,
header/generation/index corruption, stale publication generation and invalid
private destination. Startup and stop are bounded algorithms; OS scheduling
and disk startup IO have no formal WCET guarantee. Timing is measured,
not a hard 5ms Windows guarantee.

W1–W4, live price/voice/sign stability, sleep/resume, local ACL security and
power-loss durability: NOT VERIFIED. Watcher is untouched and not started.
Real submit, promotion and statistical edge remain false. Actual eligible N=0;
EV/PF/DD/realized net profit/100-billion-yen remaining are UNKNOWN.

Offline integration can be accepted conditionally after exact-head CI;
live connection remains P0_BLOCKED until #356 and separate OWNER approvals.
No main merge, deployment, autostart, real order, private data publication,
existing 263-row edits or canonical/hash changes are authorized.
