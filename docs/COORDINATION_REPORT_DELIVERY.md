# Issue #282 safe report delivery (opt-in; not deployed)

## Audit baseline, 2026-10-19

Reviewed protected main `302bd43e1862d995208f92686a2721a59bc5b72c`,
main CI https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39187269823
(success), Issue #282 (146 comments), and open related PRs before editing.
This work owns only `scripts/coordination_report_delivery.py`, its test, this
guide, and its dedicated synthetic CI. Target branch:
`fix/p0-safe-report-delivery-282`. No overlapping report-transport change was
found in the open PR inventory; #385 is a read-only ledger validator.

The referenced coordinator chat reports safety rejection, but does not expose
the original rejected tool arguments or policy reason. That platform-level root
cause is UNKNOWN. A repository patch cannot override platform policy or grant a
scheduled agent write authority. Do not claim that this change repairs those
external permissions. Existing schedules/prompts/notifications remain unchanged.

Current authenticated CLI can read the public repository and reports push/admin
repository permission. This does NOT prove the Issues write scope of a different
connector or scheduled task. GitHub's create-comment API requires Issues(write)
or Pull requests(write); read access alone is insufficient:
https://docs.github.com/en/rest/issues/comments#create-an-issue-comment
No credentials, scopes, app installations or permissions are changed here.

PR #386 at `d4df92c3e76ae51bad5c8a717caa52115071a08b` changes the authenticated
Claude routine trigger from #171 to #282. It is Draft/unmerged, and is not a
general report sender. Its signed/provenance/budget controls must not be relaxed.
This patch never emits its trigger prefix or invokes a paid service.

## Fixed public envelope

The new sender accepts only integer PR/run/sequence identifiers, a full commit
SHA and an enumerated state. It constructs repository-local evidence URLs.
No free text, credentials, local paths, raw logs, orders, account data, arbitrary
URLs or instructions can be supplied. Unknown/duplicate fields are rejected.
The hash approval binds the exact rendered body. Numeric fields and commit IDs
must be real public evidence, never a channel for encoding private data.
SYNTHETIC_TESTED requires a successful completed pull_request run on the exact
open Draft PR HEAD. Other states do not certify CI success. This is source/test
evidence only, not acceptance or deployment. Actor identity is checked through
GitHub; a specialized AI role or recipient ACK is never asserted.

## One authorized dispatcher, one durable local outbox

All callers on this dispatcher MUST share the same persistent SQLite outbox.
Multi-host independent databases are unsupported; no distributed exactly-once
guarantee is claimed. Do not roll back, delete, replace, copy stale backups of,
or reinitialize the outbox to retry a report. If lost, stop and recover/reconcile
manually; a new database cannot prove no prior attempt. A new sequence is a new
report, not a retry escape hatch. Existing agents are not silently wired to this
CLI. Automated rollout requires a separate integration decision.

The sender reads every comment page (bounded failure is blocking), checks the
message ID and exact body, and serializes local contenders with BEGIN IMMEDIATE.
It durably commits SEND_UNKNOWN BEFORE one POST. Denial, timeout, process death,
malformed response or readback failure leaves the attempt consumed. It never
retries a POST. No matching comment on a later read is NOT permission to resend.
Reconciliation requires one matching comment, actor, fixed URL and a separate
GET of its full body. Duplicate IDs or modified content block. READ_VERIFIED
means GitHub persisted the report; it is not the receiving agent's independent
ACK, processing, or hourly end-to-end completion.

If a policy/tool safety check rejects the action, preserve the outbox and report
HANDOFF_PENDING/BLOCKED. Do not switch connector/browser/CLI, alter the body or
create another ID to get around that rejection. A policy denial is not a network
error. Raw transport stderr/response errors are never published or logged.

## Explicit one-off use

Use an already authorized authenticated `gh` session. No token printing, setup
or new credential is required. In an ignored private directory prepare JSON:

```json
{"sequence":1,"head_sha":"<exact 40 lowercase hex PR HEAD>","pr":447,"ci_run":12345,"state":"SYNTHETIC_TESTED"}
```

Numbers above are illustrative, not evidence. Replace with verified IDs.

```text
python scripts/coordination_report_delivery.py prepare --report data/private/report282.json
python scripts/coordination_report_delivery.py init
python scripts/coordination_report_delivery.py send --report data/private/report282.json --approved-sha256 <reviewed body SHA256>
python scripts/coordination_report_delivery.py reconcile --report data/private/report282.json
```

Create `data/private` if absent; init is first-use-only and refuses an existing
file. `prepare` has no network or outbox side effect. Review the exact body under
the user's existing authorization before send. `reconcile` can only read remote
content and update local evidence; it cannot post. Retain the outbox after errors.

Dedicated CI uses fake transports on Windows and Ubuntu, read-only permissions,
no secrets, no schedules, no real GitHub writes, no trading/runtime deployment.
Real one-off delivery and independent connector reread are separate evidence.
Neither demonstrates that unchanged hourly tasks can invoke this local sender.
