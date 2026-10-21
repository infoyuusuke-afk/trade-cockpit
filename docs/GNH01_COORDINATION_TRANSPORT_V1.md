# GNH01 coordination transport contract v1 (DRAFT)

**Project item**: P0-GNH01-COMMUNICATION-PATH-20261022  
**Date**: 2026-10-22 JST  
**State**: PUBLIC CONTROL PLANE READBACK PASS; INDEPENDENT RECIPIENT ACK / GROK EGRESS / PRIVATE BRAIN DELIVERY NOT VERIFIED.  
**Authority**: OWNER approval required before changing cloud Bot connections, recurring tasks, private adapters or live V10.  
**Non-goals**: live orders, brokerage connection, profit forecast, replacing ChatGPT Tasks, exposing private research.

## 1. Existing transport — public control plane

- Repository: https://github.com/infoyuusuke-afk/trade-cockpit (PUBLIC).
- Shared control ledger: Issue #282: https://github.com/infoyuusuke-afk/trade-cockpit/issues/282.
- Introduction: https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6328242129.
- Readback-tested public **manual relay**: https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6328372106.
- That test was sent by an authorized ChatGPT/GitHub relay **from OWNER-supplied Grok Bot text**, not Grok's autonomous sender.
- A GitHub READBACK proves persistence/retrievability, **not** that a scheduled ChatGPT Task read the data, and **not** that a live BRAIN received anything.

## 2. Roles

| Sender/recipient | Duty |
|---|---|
| Grok Bot GNH01 | Discover public news, IR, public X posts; preserve origin, first publication, own detection timestamp, novelty and contradictory follow-ups. |
| PRE-NEXT | Independently verify candidate evidence; select pre-move Japanese-stock hypotheses and monitor initial/continuation/pullback/invalidation. |
| supply_sq | Independently validate supply/credit/derivatives context and market-demand signals; never treat hearsay as confirmed. |
| revenue_hunter | Assess business/commercial relevance separately; no sale/revenue assumed. |
| progress_coordinator | Assess timeliness, routing, receipt proof and conflict resolution; no invented ACK. |
| development_lead / Claude | Design/verify isolated opt-in ingress and tests, not live V10 changes. |
| Brain | May consume separately verified, privately delivered research only after approval and independent BRAIN ACK. |

## 3. Public routing envelope for Issue #282

Use existing `[100B_COORD_V1]` header and these minimum fields:

```text
[100B_COORD_V1]
message_id: GNH01-<UTC-date>-<unique-event-id>
event_type: PUBLIC_MATERIAL_SIGNAL | PUBLIC_MATERIAL_UPDATE | ACK_RECEIVED | REQUEST_VERIFICATION
source_role: gnh01 | owner_instruction_relay | pre_next | supply_sq | revenue_hunter | progress_coordinator | development_lead | implementer_claude
recipient_role: pre_next,supply_sq,progress_coordinator
project_item_id: P0-GNH01-COMMUNICATION-PATH-20261022
in_reply_to: <original-message-id or NONE>
event_id: <stable-public-event-id>
bot_run_id: <opaque nonsecret ID or UNKNOWN>
original_published_at_jst: <ISO8601 offset or UNKNOWN>
bot_detected_at_jst: <ISO8601 offset or UNKNOWN>
sent_at_jst: <ISO8601 offset or UNKNOWN>
source_url: <public HTTPS no secrets/query/fragment>
verification_status: UNVERIFIED | PRIMARY_CONFIRMED | SECONDARY_ONLY
novelty_status: FIRST_DISCLOSURE | NEW_UPDATE | RECONFIRMATION | REPEATED | UNKNOWN
ticker_company: <verified ticker + official company name, or UNKNOWN>
state: PUBLISHED_NOT_ACKED
real_submit_allowed: false
owner_approval_boundary: PUBLIC_RESEARCH_ONLY_NO_LIVE_V10_NO_ORDERS_NO_BILLING
```

Every material fact must be grounded to the original public URL. Do not silently replace UNKNOWN with guessed times. A Bot-run timestamp is **not** the publication timestamp. Relay and Bot-origin content must be distinguished: a human/ChatGPT repost MUST declare `source_role: owner_instruction_relay`, `original_source_role: grok_bot_gnh01`, and `autonomous_delivery_verified: false`.

Keep message IDs immutable. A correction is a NEW message with `in_reply_to` and the prior event ID. Deduplicate by `(event_id, source_url, novelty_status, original_published_at_jst)`. Do not suppress substantive corrections.

## 4. Receiver ACK

Each intended recipient that can actually read Issue #282 replies using the existing `[100B_COORD_V1]` form:

```text
message_id: ACK-<role>-<source-message-id>
event_type: ACK_RECEIVED
source_role: <the actual receiver>
recipient_role: progress_coordinator,gnh01
project_item_id: P0-GNH01-COMMUNICATION-PATH-20261022
in_reply_to: <exact source message_id>
received_at_jst: <observation timestamp or UNKNOWN>
ack_scope: PUBLIC_GITHUB_READ_ONLY
verified_event_ids: <IDs actually read>
source_verification: VERIFIED | UNVERIFIED | PARTIAL
brain_received: false
real_submit_allowed: false
```

Distinguish three separate evidence gates:
1. **PUBLISHED_AND_READBACK**: one sender put a message on GitHub, and an independent GitHub read found it.
2. **RECIPIENT_ACK_RECEIVED**: the *actual recipient* fetched it and replied in the same Issue.
3. **PRIVATE_BRAIN_ACK**: the Windows V10 Brain receiver independently recorded and signed receipt. No GitHub comment can substitute for this third gate.

Silence is not an ACK. Bot routine success is not the same as signal receipt. Recipient ChatGPT Tasks may need their existing prompts updated with OWNER approval to search for this schema; a pasted one-off instruction does not change their saved schedules.

## 5. Restricted Bot outgoing access — NOT CONNECTED

GNH01 is a cloud Bot external to this GitHub connector. It is **not** proven to have a writable GitHub session or API credentials. No person should paste a GitHub access token into chat, public Issue, or logs.

Before any automatic post, use an OWNER-approved constrained integration:
- Prefer a dedicated relay endpoint with authentication and *only* append-public-signal permission, or a fine-grained token scoped to Issue comments on a designated repository, stored in a dedicated secret manager and never echoed.
- Avoid a general-purpose write token that can change code, PRs, workflows or other repos.
- Publish a **synthetic PUBLIC test only**, read it back independently, then collect actual recipient ACKs.
- Compare sender-reported send time with GitHub record; test duplicate, malformed, delayed and revoked-credential cases.
- Do not enable the Bot's scheduled external posting merely because the hourly research Routine is enabled.

No part of this Draft establishes Grok-side authentication or autonomous external delivery. That requires access to the Bot integration settings.

## 6. Private research/BRAIN path — already staged, not live

Existing Draft PRs:
- #481: independent Agents SDK research pilot + signed private handoff.
- #482: local V10 research receiver with signed durable Brain ACK.
- #483: opt-in Brain observer wiring, **default OFF**, not deployed.

All are separate from public Issue traffic. The 15-minute HMAC envelope age and no-trade gate remain unchanged. A new GNH01-to-private-envelope adapter may be implemented only on an isolated branch with synthetic tests, explicit source/evidence binding, input deduplication, re-play rejection, secrets outside git and OWNER acceptance. No scheduled API spending is authorized.

## 7. Acceptance checklist and current evidence

| Gate | Current result |
|---|---|
| Issue #282 supports public coordination notices | PASS: introduction comment #6328242129 |
| Public source-relay message can be written/read back | PASS: comment #6328372106 |
| All intended specialist recipients independently ACK the *same* pilot message | PENDING |
| GNH01 can autonomously post one test event with restricted permissions | NOT VERIFIED |
| Hourly :30 Grok routine continuously executed | OWNER-REPORTED INTENT; RUN HISTORY NOT VERIFIED |
| Private adapter receives real GNH01 event | NOT VERIFIED |
| V10 Brain independently ACKs real GNH01 event | NOT VERIFIED |

Nothing here grants live deploy, merges, paid API use, order submission, changes to Excel, UI, existing task schedule or stored prompt. `real_submit_allowed=false` applies end-to-end.

## 8. Immediate next actions

1. Progress coordinator, PRE-NEXT, supply/SQ, Revenue Hunter, development lead and Claude: read pilot comment #6328372106 and reply with exact `ACK_RECEIVED`, preserving `in_reply_to` and role.
2. Verify GNH01's cloud integration capabilities and configure least-privileged outbound delivery with OWNER approval; send one **Bot-originated** synthetic message.
3. Independently read back that Bot-originated message and inspect all role-specific ACKs.
4. Only then design the bridge to #481–#483's private research lane and run synthetic fail-closed tests before any live V10 attachment.
