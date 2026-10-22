# 100億PROJECT | Role Coordination Ledger v1.0 (DRAFT)

Status: IMPLEMENTED_ON_ISOLATED_BRANCH; activation / task-prompt changes / merge NOT authorized by this document.
Owner's goal: **JPY 10,000,000,000 cumulative realized NET profit after costs**. Code volume, PR counts, AI reports and synthetic CI are not profit.

## Boundaries

- Single PUBLIC-SAFE transport: [Issue #282](https://github.com/infoyuusuke-afk/trade-cockpit/issues/282). This is **not** a private channel, authentication server, trading endpoint or substitute for Acceptance evidence.
- Existing ChatGPT hourly tasks retain their current schedules, enablement, prompts and notifications. No new workflow, automation, scheduled task, deploy, main write, merge, publication, broker submit or paid API is enabled by this change.
- OWNER is final authority; `progress_coordinator` prioritizes and independently reviews; `development_lead` owns engineering; `spec_audit` checks requirements; `revenue_hunter` measures verifiable net profit; `pre_next` researches next-session signals; `supply_demand_analyst` researches supply/demand; `claude_auditor` is read-only and best-effort when available.
- **real_submit_allowed=false**. Preserve Permission/Risk/Kill Switch. No real orders/hedges, auto-merge, contracts, charges, sensitive disclosures, silent task changes or override of cross-engine instructions.
- Never post account/position/order/fill/holdings, private MS2/RSS data, trade secrets, tokens, local PC paths, unpublished information or personal data to public Issue #282.

## Transport: append-only, one message per comment

All new machine-readable comments MUST start with literal `[100B_COORD_V1]` and have one `key: value` per line (no multiline fields). Required:

`message_id`, `event_type`, `source_role`, `recipient_role`, `project_item_id`, `sent_at_jst` (offset ISO8601), `evidence_url` (public GitHub evidence), `owner_approval_boundary` (`REVIEW_ONLY`, `OWNER_APPROVED_PILOT`, `CHANGE_REQUEST_PENDING_OWNER`), `real_submit_allowed: false`.

For `ACK`, `RESULT`, `REVIEW` and `CHANGE_REQUEST`, include `in_reply_to` matching an existing comment's `message_id`. For `REPORT` or `ASSIGN` the reply is optional; self-declared roles NEVER constitute authenticated identities. Comments must be unique by `message_id`; duplicates, invalid timestamps, unsafe values and wrong-direction replies fail closed. Optional non-secret `state`, `next_action`, `acceptance`, `main_sha`, `pr_number`, `head_sha`, `data_as_of`, `data_available_at`, `ev`, `pf`, `n`, `cost_impact` can be included, never synthetic performance asserted as realized profit.

Examples (public-safe; non-executable):

    [100B_COORD_V1]
    message_id: COORD-20261015-DEV-001
    event_type: ASSIGN
    source_role: progress_coordinator
    recipient_role: development_lead
    project_item_id: P0-WINDOWS-WRITER
    sent_at_jst: 2026-10-15T15:32:00+09:00
    evidence_url: https://github.com/infoyuusuke-afk/trade-cockpit/issues/382
    owner_approval_boundary: REVIEW_ONLY
    real_submit_allowed: false
    state: PENDING_ACK
    next_action: Report existing Windows native Writer DROP root cause and evidence, no source code change authorized by this message.

    [100B_COORD_V1]
    message_id: DEV-20261015-ACK-001
    event_type: ACK
    source_role: development_lead
    recipient_role: progress_coordinator
    project_item_id: P0-WINDOWS-WRITER
    in_reply_to: COORD-20261015-DEV-001
    sent_at_jst: 2026-10-15T16:02:00+09:00
    evidence_url: https://github.com/infoyuusuke-afk/trade-cockpit/issues/282
    owner_approval_boundary: REVIEW_ONLY
    real_submit_allowed: false
    state: RECEIVED

## Honest state machine

`NOT_CONFIGURED -> CONFIGURED -> READ_VERIFIED -> WRITE_VERIFIED -> END_TO_END_VERIFIED`.
A posted comment that was independently re-read proves `WRITE_VERIFIED` for THAT writer; not recipient receipt.
`END_TO_END_VERIFIED` requires the intended recipient's **independent subsequent scheduled-run** readback, a unique correlated ACK/reply URL and further source-run evidence. GitHub's shared authenticated account does NOT cryptographically prove the declared source_role. Until that provenance is independently attested, report `SENDER_ROLE_UNVERIFIED` and DO NOT claim authenticated E2E.

Business flow: `REPORT/ASSIGN -> ACK -> RESULT -> REVIEW -> (next change or BLOCKED)`. An ACK is not task completion. A Draft PR is IMPLEMENTED, not necessarily TESTED; CI PASS does not imply DEPLOYED/PRODUCTION_VERIFIED. Change requests across AI engines need OWNER approval and must not mutate the recipient automatically.

## Idempotency / replay

- Every scheduled run independently reads current Issue #282, latest main and relevant PR/CI before acting.
- A coordinator posts at most ONE supply-demand reply per hour/run, never retries a delivery with UNKNOWN outcome; before posting check exact `in_reply_to` and sender-role ACK already exists.
- Repeated reports with no new evidence use `NO_MATERIAL_CHANGE`, not a new synthetic achievement or ID.
- Missing/late/stale/future evidence must be `UNKNOWN` / `DATA_UNAVAILABLE` and fail closed. No market metric may bypass point-in-time `available_at`.

## Initial actual verified pilot (legacy format)

- Analyst original: https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6180186007
- Coordinator ACK, POSTED and INDEPENDENTLY RE-READ 2026-10-15 JST: https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6186087525
- These two pre-v1 comments are **not machine-schema v1**, and do not prove the analyst's independent scheduled-run receipt. E2E=PENDING until separate analyst evidence.
- Development, PRE-NEXT, Revenue Hunter and spec-audit routes are **not** E2E-proven. PRE-NEXT's existing schedule text is not a guaranteed Issue #282 inbox, and no task prompt shall be silently modified.

## GNH01 legacy DELIVERY_TEST observation extension (Draft only)

The 2026-10-22 one-shot Routine GitHub comment
[6335466037](https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6335466037)
does **not** have required standard v1 sent_at_jst, evidence_url or
owner_approval_boundary. Never synthesize those fields or treat this comment
as a regular REPORT or authenticated transport. The separate read-only
`gnh01_coordination_observation_v1` validator permits only the observed
legacy DELIVERY_TEST shape (fixed external global_news_hunter_01 source,
development_lead recipient, strict marker, clock and real_submit_allowed=false).
Its asserted routine run ID UNKNOWN remains UNKNOWN.

Under this **proposed, unmerged** extension, a development_lead ACK may
reference that one DELIVERY_TEST only when it includes
`ack_scope: GITHUB_COMMENT_READBACK_ONLY`, standard valid ACK metadata and
reversed roles. Correlation proves only a declared GitHub readback. It does NOT
prove a Grok-authenticated sender, unattended PRE-NEXT task delivery, specialist
receipt, SHADOW/BRAIN input, or end-to-end verification. Any duplicate ACK or
unsupported ACK scope fails closed. The external Grok source is not an active
coordination role; the five-role OWNER roster in Issue #282 prevails over
legacy role descriptions in this Draft.

This change is a review proposal. Do not post an ACK relying on its
not-yet-approved contract, install schedulers, modify Grok/PRE-NEXT/V10,
promote delivery tests to market events, merge, deploy or authorize real orders.
Independent review and OWNER acceptance are required before activation.

## Local read-only verifier

`python -m scripts.coordination_ledger_v1 path/to/public_issue_comments.json`

Input is an array of GitHub comment objects with `body`, `url` and `created_at` (optional); the tool NEVER accesses the network and NEVER writes or posts to GitHub. It validates messages, causal replies and duplicate IDs; all role claims are explicitly marked UNVERIFIED until separately attested.

Unit tests: `python -m unittest tests.test_coordination_ledger_v1`.
No automatic execution integration is claimed by this DRAFT. If task integration needs prompt, workflow, schedule or permissions changes, prepare a separate OWNER-approved acceptance proposal.

## Final Acceptance

A) role contract reviewed and isolated Draft PR; B) deterministic negative tests PASS; C) public-safe pilot ACK independently re-read; D) each target owner independently receives and correlates a message on its own scheduled run; E) controller independently verifies receipt, actual PR/test or analytic evidence and closes feedback; F) no changes to schedules, safety gates, real execution or secret exposure. Until D/E, label `PILOT_PARTIAL` not `ORGANIZATION_COMPLETE`.
