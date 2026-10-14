# Issue #356: offline IPC v2 integrity and crash fencing

Reviewed main `dd06571d80d0d228d54aae5cb5f7d6751ba68160`.
Base Draft #360 `7ecb2d74790e032d787121b5d39773a47c1061bc`.
Stack #347 → #349 → #351 → #353 → #355 → #358 → #360 unchanged.
No live Watcher/Owner PC/MS2/Excel, autostart, orders, promotion or merge.

## Cause and contract

The inherited producer copied bytes and advanced write index without publisher
exclusion or a per-slot envelope. Two publishers could select the same index,
interleave valid-looking data and lose increments. A payload decoder alone
cannot reject every plausible mixture. Bare ctypes stores are not a portable
publication barrier. Slot reuse lacked absolute sequence/generation/checksum.

The **map header** version at offset 180 is now 2. Old map headers are refused.
The 2048-byte NBH1 record stays version 1 with unchanged bytes/canonical hashes.
Map size 20480, queue capacity 8, slot base 4096, stride 2048 remain unchanged.
This is an isolated IPC revision; sidecar/execution/hash contracts and the
263-row history are byte unchanged.

| Offset | Meaning |
| --- | --- |
| 0, 8 | absolute write/read indices |
| 112 | positive signed-64-compatible session generation |
| 176–187 | magic/map version/capacity/record bytes/map bytes |
| 192–195 | persistent gate: free=0, held/abandoned=1 |
| 256–287 | inherited worker reason |
| 512 + (absolute sequence mod 8) × 64 | slot metadata |
| metadata + 0 | commit=sequence+1; unpublished=0 |
| metadata + 8, +16, +24 | generation, absolute sequence, payload length |
| metadata + 32–63 | SHA256(little-endian generation/sequence/length + payload) |

## Exclusion and ordering

Windows uses `Local\ms2ipc-v2-<generation>` OS mutex, **zero timeout**, no retry,
plus the persistent shared gate. Handles are prepared at startup/attach and
cached. OS mutex ownership supplies the publication/consumption memory barrier.
Linux uses libatomic CAS and sequentially consistent acquire/release on the
shared gate. No disk write, file lock, pipe or process creation occurs in submit.

Producer: one gate acquisition → header/generation/index/flags checks → reject
full queue → invalidate commit → copy envelope/checksum/payload → publish commit
and write index → release. Collision returns PRODUCER_BUSY without overwriting
someone else's slot. Consumer: one acquisition → header/envelope/checksum and
process-local read/highwater fences → copy and claim index → release → decode
unchanged record → existing private writer. Disk IO occurs outside the gate.
One immutable local in-flight copy can coexist with eight queued slots.

A crashed holder leaves a persistent held gate or abandoned mutex. No foreign
holder is forcibly unlocked. After 150ms continuously refused gate acquisitions,
the worker latches Kill Switch and stops. Scheduling delays can cause safe false
rejections; this is not proof of failure detection or a strict time bound.
Sequence exhaustion, old-generation/ABA slot, index rollback, checksum/length/
header mismatch cannot persist. Checksum is corruption detection, **not**
authentication against someone already holding write access to the mapping.

## Lifecycle and security

Inherited owner/worker leases reject duplicate starts and retained orphan workers.
Lock-file existence alone is not a healthy-owner test; OS lock ownership decides.
Only a known child process handle is stopped. No foreign PID is killed. No foreign
mapping is cleared/unlinked. Restart creates a new map/generation and quarantines
unpublished spill through the existing private writer lock, never replaying old
mapping slots. General automatic orphan remediation is not claimed.

PowerShell attaches only to the exact generated session map name; Global/Local
fallback was removed. Immediately after successful create=True (never attach or
collision), startup verifies owner, **narrows its own map DACL** to current token
user/SYSTEM/Administrators, and rereads actual resulting grants. Null/unreadable/
unsupported/untrusted ACLs fail closed. Temporary synthetic ACL test widens only
its own test map to World and expects refusal. The pre-hardening bootstrap interval,
mutex identity/DACL authentication, hostile same-user attach, and actual other-user
or elevated-token attacks are not proven safe: production remains P0 BLOCKED.

## Tests, timing and evidence boundary

Tests inject envelope marker/generation/sequence/size/checksum/plausible-payload
corruption, actual producer exit mid-slot, actual consumer kill while holding read
gate, separate-process publisher collision, sequence limit, ABA/rollback, old map
header, actual Windows DACL broadening, PS5.1 normal/full-queue/crash. Inherited
Windows/Linux E2E rereads private JSONL and covers duplicate restart, corrupt JSONL
preservation, injected ENOSPC, writer lock/replace/temp faults, stop/restart and
byte-pinned Watcher/history/contracts.

Windows timing: 200 actual PS5.1 submit calls with harness call overhead, initial
accepted slots then full-queue DROP_NEWEST. Report nearest-rank p50/p95/p99/max;
attach/startup/packing are outside the measurement. This is synthetic runner data,
not Owner PC, formal WCET, real market observation, or revenue. A 5ms target may
be missed on a general-purpose OS; it is never presented as guaranteed.

W1–W4, sleep/resume/clock shift, power loss, actual owner-death automatic recovery,
other-user/elevated access, hostile same-user authentication and authenticated
mutex identity remain NOT VERIFIED/P0 BLOCKED. Existing owner-lease-loss test is
a model, not actual owner power failure. No safety-critical issue is closed.
POLL remains POLL; snapshot_atomic=false; available_at is not inferred; missing
quantities remain null. Real eligible N=0; EV/PF/DD/profit/100B residual UNKNOWN.
real_submit_allowed=false; promotion_eligible=false;
statistical_edge_confirmed=false.
