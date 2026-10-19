# P0 authorized intake and ACK contract — BLOCKED for real hourly agents

## Current evidence, 2026-10-19 JST

Reviewed main: `ed90d8022dbdc854e2ccded42b80870147b67253`.
Reviewed Draft #447: `0ba22b50413e3117f7149cde208ebdc466cc1709`.
Its review requires real permitted input and independent scheduled ACK evidence:
https://github.com/infoyuusuke-afk/trade-cockpit/pull/447#pullrequestreview-5566330527
Issue #282 was read through all 163 returned comments. Relevant diagnosis:
https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6258530343
This is historical diagnostic evidence, not current platform authorization.

No verified authorized input adapter for the blocked hourly agents was found.
Original platform refusal category and operation details remain UNKNOWN.
This implementation does not resolve the platform refusal. No denied message is
forwarded through CLI, another connector, another agent, renamed ID or sanitized
rewrite. No live Issue comment is sent by this change. #447's interactive CLI
capability is not inherited by a scheduled ChatGPT agent.

## Implemented boundary

`production_status()` always returns WRITE_UNAVAILABLE, role authentication false,
E2E false, orders false. There is no production send/enable CLI or live adapter.
`SyntheticQueue` is explicitly an offline contract harness. Its fixture interface
is not an authentication implementation and must never be configured with a live
transport. All successful fixture results remain SYNTHETIC_ONLY, E2E false.

The harness extends #447's existing SQLite outbox, with one intake table and
unique event/message constraints; no second delivery queue. It never recreates a
lost database. An immediate transaction and durable pre-dispatch claim serialize
concurrent consumers. One attempted dispatch per sender route is the deliberately
bounded scope. The route remains held even after success, until a separately
reviewed release protocol exists; there is no automatic reset/retry/reconcile
operation in this layer. #447 itself still supports its existing read reconciliation.
No distributed exactly-once or sustained hourly throughput is claimed.

Input is a fixed report envelope plus source/recipient/event/run identifiers.
Extra fields such as `authorized=true` are rejected. Fixture grants are separate
from message data; they simulate, but do not prove, platform grants. Missing,
unknown or denied grants prevent fixture delivery. Recheck before dispatch catches
revocation. Denials and attempts latch the source/destination route across ID,
sequence and run changes. Persisted state cannot be cleared through this API.

| State | Meaning |
|---|---|
| WRITE_UNAVAILABLE | No verified permitted route; nothing dispatched |
| QUEUED | Fixture-authorized intake accepted in shared outbox |
| SEND_UNKNOWN | Durable claim exists; never automatically retry |
| READ_VERIFIED | #447 exact report readback succeeded in fixture |
| HANDOFF_PENDING | Required independent ACK or reread proof missing/invalid |
| ACK_VERIFIED | Fixture chain complete, still SYNTHETIC_ONLY, E2E false |

ACK verification creates no ACK. It repeats original report readback, requires a
complete duplicate search, exact in_reply_to and reversed role direction, fixed
Issue URL, independent receiver-run attestation, exact ACK body/hash GET, receiver
own reread, and sender later-run reread bound to the same URL/hash. A public role
string or shared GitHub account cannot authenticate a role. Reverification checks
edits/deletion and missing proof again; no cached ACK acceptance is returned.

The fixture abstracts platform-issued run identity, grants, receipt ordering and
complete pagination. Their positive synthetic tests do NOT establish that such
an adapter exists. A real implementation would need platform-verifiable identity,
run/time binding, revocation, bounded authorization, and read receipts from each
existing context. Do not turn boolean fixture attestations into production grants.

## Verification and next legitimate gate

Run `python -m unittest discover -s tests -p 'test_coordination_*.py' -v`.
The new CI uses only fake transports, read-only repository permission, no secrets,
no dispatch schedule, no deployment, and no issue-write permission. Existing
workflows and hourly task settings are unchanged.

Before any real integration, obtain the sanitized original refusal category and
the platform's supported authorization evidence in the affected agent context.
If no authorized input path exists, keep WRITE_UNAVAILABLE. A user instruction or
another agent's token cannot override platform refusal. Only a separately reviewed
authorized adapter can be considered; task-setting changes and production rollout
remain outside this request. Real sender report, recipient ACK and later sender
reread are NOT_RUN. No END_TO_END_VERIFIED or recovery claim is warranted.
