# Issue #364 offline IPC boundaries

Base #363 ca3ccf54bf50294827a1b8218e7f1d92afadd5ea; main at audit e6ca1a1f20d82a02da2755bb018b9e01b142df5a. Draft chain #347 → #349 → #351 → #353 → #355 → #358 → #360 → #361 → #363 preserved. #282 latest evidence still awaits independent review. No permission to integrate a Watcher or merge.

## Identity

Current SID DACL restricts authorization, not process identity. A fresh spawn process with only public map name and synthetic bytes can publish. Name secrecy, generation, SHA checksum, PID and an owner-controlled environment variable cannot establish hostile same-user identity. A secret in a same-user-readable file or command line is not a remedy. No secret is created or embedded.

`require_process_authentication=True` on both Python start APIs and `-RequireProcessAuthentication` on PS attach refuse BEFORE acquiring private resources with `SAME_USER_AUTH_UNRESOLVED`. Default disabled remains disabled. Explicitly enabled legacy offline fixtures retain their test access; they are NOT authenticated and all production contract gates remain blocked. A caller cannot turn this option into proof of authentication. Different-user anonymous denial from #363 is retained; actual other-user and elevated attacks remain unverified. Hostile same-user modification of code, private files or map bypasses this library policy. A distinct restricted service identity/security boundary is required before live admission.

## Commit/crash containment

Worker wraps existing writer hooks; payload, canonical serialization and writer code unchanged. Immediately before `os.replace`, parent sentinel and STOP/KILL are checked. A dead owner refuses publication after an in-flight write returns. This is a check-before-syscall fence, NOT an atomic parent-liveness/commit transaction. Owner death after the check or while replace is in progress may still publish. A published valid file is never rolled back merely because owner died.

Synthetic pauses inside partial temp write, before replace and after replace model unavailable syscall completion. Owner is hard-killed by its exact multiprocessing Process object. While the pause remains, worker lease denies a new owner (`ALREADY_RUNNING`, effective BLOCKED); there is no PID scan or automatic unknown-worker kill. Harness releases the pause, then parent death produces `OWNER_DEAD_QUARANTINED` with STOP|KILL and worker exits. New owner is allowed only after lease release, with new map/generation and empty queue. Separate worker hard kills use the parent's exact worker Process handle; leftover partial/complete unpublished temp goes to quarantine on restart, with previous published JSONL preserved. After-replace crashes preserve the committed prefix and record. This does not prove recovery if a real OS syscall never returns. Such a lease remains BLOCKED; no unsafe override. Existing STOP_PENDING retains ownership until exact process exit, as covered by inherited tests.

## Timing

PS5.1 complete steady path measures packing/validation plus submit (persistent attach). Attach+ACL and cold dot-source/first pack/first attach are measured separately. Instrumented runs: 3 × 200 submissions, 8 accepted + 192 full drops each, run 1 with a separate CPU load process, runs 0/2 without deliberate load. Fixed seed 364 (no random input); fixed one-level synthetic fixture, missing bid qty, zero ask qty. Each phase reports N/p50/p95/p99/max. Accepted N=8 is too small for robust tail inference. Instrumentation is opt-in `-TraceTiming`, never enabled on live code.

Stage wall timers split HEADER/PREFIX/CHECKSUM/ENVELOPE/PAYLOAD/COMMIT/UNLOCK; maximum complete sample logs its index/status, GC collection deltas and process CPU delta. These are diagnostic correlations, not allocation tracing or scheduler causal proof. Harness/Stopwatch overhead is included. Process cold launch externally measured includes all harness work; `cold.startup_ms` is in-process startup only. No hard real-time/WCET promise, no raised thresholds, no unproven optimization. The prior max 103.278ms is a failure of 5ms target. Safe fallback design is a separate low-priority observation process with drop on overload; not implemented or approved for Watcher integration here.

## Gates

real_submit_allowed=false; promotion_eligible=false; statistical_edge_confirmed=false; eligible real N=0; EV/PF/DD/economics UNKNOWN. Power loss, real indefinitely blocked syscall, sleep/resume, owner PC W1-W4: NOT VERIFIED. Watcher/COM/private market data/history unchanged. Only synthetic temporary directories are used. CI results must refer to exact final SHA; green synthetic tests do not resolve identity/latency/OS atomicity blockers.
