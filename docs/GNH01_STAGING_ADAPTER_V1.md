# GNH01 one-shot private staging adapter

PROJECT_ITEM_ID: P0-GLOBAL-INTELLIGENCE-TO-SHADOW-INTEGRATION-20261022

## What this change does

`scripts.gnh01_stage_review_once_v1.stage_json_once(db_path, raw, private_dir=..., now=...)`
composes the existing #490 strict event parser, private durable archive and signed
review exporter. The caller supplies bounded event JSON bytes, a trusted local
clock, the SAME private archive database across invocations, an external private
directory and the existing sender-key environment configuration. Never embed a
key or private news payload in a public comment, repository or command argument.

The function does not need the receiver key. It cannot fabricate PRE-NEXT's ACK.
It produces SOURCE_REVIEW_REQUIRED only. An authorized future ingress may call
this function, but no scheduler, GitHub listener, Grok Routine, ChatGPT task,
Windows service or live V10 integration is installed by this PR.

## Durable at-most-once boundary

1. Validate input, path, clock and configured sender key.
2. Reuse #490's archive and independently read the archived event.
3. In the SAME SQLite database, claim (event_id, revision) with BEGIN IMMEDIATE
   and synchronous=FULL; commit SEND_UNKNOWN before the exclusive file export.
4. Export exactly once, independently reopen and verify the signed envelope
   against the archive, then persist READ_VERIFIED plus the envelope SHA-256.
5. On completed duplicates, independently re-read both records. Never refresh
   timestamps or regenerate a missing/corrupt file. Any uncertain attempt stays
   SEND_UNKNOWN across process restarts and blocks export permanently.

The dispatch table is an attempt record, not a second queue or transport. No
reset/retry API exists. Database deletion, changing databases or renaming event
IDs is NOT a recovery procedure. Retention, OS ACLs, trusted clock and production
configuration custody require separate acceptance. SQLite and local HMAC do not
authenticate Grok or independently administered specialists. A hostile same-user
operator can replace local state; this implementation does not claim otherwise.

The existing independent local reader can subsequently consume the file using
`receive_review`, and #490's `audit_local_chain` can correlate its ACK. Those
remain LOCAL_READER_ONLY_NOT_CHATGPT_PRE_NEXT. Neither function is called by the
staging producer. Sender possession of both keys is not recipient independence.

## Issue #282 acceptance and #385 compatibility

Read on 2026-10-22: comment 6335466037 contains
`GNH01-ROUTINE-EGRESS-ONCE-20261022-01`, marker `GNH01-MARK-0de7fd7c`,
`DELIVERY_TEST`, source `global_news_hunter_01`, recipient `development_lead`.
The 214-comment connector snapshot contains one occurrence and no corresponding
in_reply_to ACK. This establishes observed GitHub persistence, not authenticated
Routine execution: routine_run_id is UNKNOWN and execution logs were not read.

At #385 HEAD 9a8d8cec2620f109c393e6418a4d04b669fac9eb, the parser does not
allow this source role or DELIVERY_TEST, and the message lacks sent_at_jst,
evidence_url and owner_approval_boundary. Its causal ACK validator also accepts
only ASSIGN/REPORT/REVIEW parents. Therefore a reply cannot be represented as a
#385-validated ACK without an explicit protocol extension. Do not silently map
DELIVERY_TEST into REPORT, fabricate timestamps or issue a substitute message ID.
No ACK is posted by this adapter. The synthetic delivery test is rejected as
market-event JSON and cannot enter the research archive or be promoted.

Evidence: https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6335466037

## Remaining gates

- Authenticated, unattended Grok exporter and run/action-log correlation.
- Authorized private ingress that calls this adapter and retains the database.
- Actual PRE-NEXT task import and independent receipt/ACK under an agreed protocol.
- Independent primary-source identity, issuer/ticker and publication/available_at
  verification; no self-asserted verification flags or local timestamp promotion.
- Existing research/SHADOW contract acceptance and separately controlled BRAIN
  receiver ACK. News claims do not satisfy MS2/virtual-ledger provenance contracts.
- Independent code review, Windows ACL/clock acceptance, OWNER approval of any
  cross-engine configuration and deployment. CI is synthetic, not these gates.

All outputs keep real_submit_allowed=false, end_to_end_verified=false,
pre_next_automated_receipt_verified=false, shadow_ingestion_verified=false and
brain_receipt_verified=false. No real order, merge, deployment, paid API call,
task setting change or production key provisioning is performed.
