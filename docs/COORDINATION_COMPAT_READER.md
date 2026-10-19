# Issue #282 compatibility reader (read-only, Draft)

PROJECT_ITEM_ID: P0-AI-COORDINATION-DELIVERY-RECOVERY
State: IMPLEMENTED_ON_DRAFT_BRANCH. Synthetic tests only. Not wired to any task.
`real_submit_allowed=false`, `stop_allowed=false`, `cutover_eligible=false`.

## Why

Three message formats are in use on Issue #282, and no single tool reads them all:

| Format | Where it comes from | Read by #385 parser |
|---|---|---|
| `[100B_COORD_V1]`, strict | PR #385 contract | yes |
| `[100B_COORD_V1]`, as actually written | all agents since 2026-10-15 | no (rejected) |
| `[100B_REPORT_DELIVERY_V1]` | PR #447 sender | no (ignored) |

On the 166 comments of Issue #282 (read 2026-10-19, last comment 08:45:45Z):

- 88 comments carry the `[100B_COORD_V1]` tag. Only 5 pass the #385 parser.
- The rest fail mainly because of extra fields (70) or a missing `sent_at_jst` (71).
- Agents also use about 30 free event names instead of the 6 defined ones, and comma-separated recipient lists.
- One comment uses the #447 envelope.
- 77 are untagged legacy comments.

## What this adds

`scripts/coordination_compat_reader.py` is an offline reader. It reuses the #385 parser unchanged for the strict check, then reads the same comment leniently. It returns one normalised record per comment:

- protocol
- message id and raw event plus an event class
- declared roles, with comma lists split and aliases resolved (`supply_sq` to `supply_demand_analyst`)
- project item and `in_reply_to`
- declared time and server time
- posting channel
- warnings and blocking findings

It has no network access and never posts, retries, edits, deletes or authenticates.

Usage, with comments saved by `gh api` beforehand:

```text
python -m scripts.coordination_compat_reader comments.json --summary
python -m scripts.coordination_compat_reader comments.json --baseline earlier.json --expected <message_id>
```

### Rules

- **Only an ACK claims receipt, so only an ACK must match exactly.** The ACK sender must be one of the parent's recipients. The ACK must be addressed to the parent's sender, with the same project item and a parent of type ASSIGN, REPORT, RESULT or REVIEW. One ACK per parent per role. Any mismatch blocks.
- **Other replies are references.** Agents use `in_reply_to` to thread their own follow-ups. Those replies are kept as `SELF_CONTINUATION` or `LOOSE_REFERENCE` and never count as receipt.
- **Duplicates.** A repeated `message_id` blocks: `DUPLICATE_MESSAGE_ID` for the same body, `ID_CONTENT_CONFLICT` for a different one.
- **Time.** A declared time later than GitHub's post time blocks. So do a server time in the future and a missing server time. A missing or invalid declared time falls back to server time with a warning.
- **Safety.** `real_submit_allowed: true` blocks. So do tokens and local paths, using the #385 pattern.
- **Integrity.** An edit after posting is flagged. With `--baseline`, deleted or changed comments are listed.
- **Send unknown.** With `--expected`, a message the sender believes it sent but that is absent stays `SEND_UNKNOWN_NOT_OBSERVED`. It is never "failed" and never permission to resend. `retry_allowed` is always false.
- **Provenance.** GitHub's `performed_via_github_app` is the only server-side fact. It names the tool family (`chatgpt-codex-connector`, `claude`, or none), not the role or the scheduled task.
  - A role claimed from the other family is `ROLE_CHANNEL_MISMATCH` and blocks.
  - A plain token is `CHANNEL_UNATTESTED`.
  - A match is still `UNVERIFIED`.
  - `end_to_end_verified` is always false.
- **#447 envelopes.** They are read, but they have no roles or project. An ACK to one correlates by id only (`ID_ONLY_NO_ROLES`) and does not count as a role ACK.

## Findings on the real Issue #282 (public metadata only)

| Role | Messages claimed | Last | Correlated ACKs sent | Addressed to it, unanswered | Write | Role auth | Scheduled E2E |
|---|---|---|---|---|---|---|---|
| progress_coordinator | 13 | 2026-10-18 22:52Z | 0 | 54 of 63 | CLAIMED_UNVERIFIED | UNVERIFIED | UNKNOWN |
| development_lead | 53 | 2026-10-19 08:18Z | 1 | 6 of 18 | CLAIMED_UNVERIFIED | UNVERIFIED | UNKNOWN |
| implementer_claude | 7 | 2026-10-19 08:45Z | 0 | 3 of 6 | CLAIMED_UNVERIFIED | UNVERIFIED | not scheduled |
| revenue_hunter | 1 | 2026-10-15 07:15Z | 1 | 2 of 7 | CLAIMED_UNVERIFIED | UNVERIFIED | UNKNOWN |
| pre_next | 0 | none | 0 | 3 of 7 | NOT_OBSERVED | UNVERIFIED | UNKNOWN |
| supply_demand_analyst | 0 tagged; 1 untagged pilot on 2026-10-14 | 2026-10-14 22:46Z | 0 | 2 of 6 | NOT_OBSERVED in v1 | UNVERIFIED | UNKNOWN |

Notes on the table:
- Since 2026-10-16, none of the three specialist roles has a message on the Issue.
- All 166 comments are posted under one GitHub account.
- No ACK on the Issue has been cited back by its original sender, so `ack_reread_observed` is 0 everywhere.

Other findings:
- Five replies cite a parent id that does not exist on the Issue (`ORPHAN_REPLY_PARENT_NOT_FOUND`):
  - 6258448529 cites a Revenue Hunter handoff that was only in chat.
  - 6259741202 and 6260692666 are Claude's, citing a mistyped development-lead id.
  - 6204182561 and 6204316558.
- Four development-lead comments (6209004396, 6209350119, 6209916413, 6210193824) contain local PC paths. That breaks the Issue #282 rule against posting local paths. They are left untouched; editing another engine's record needs OWNER approval.
- Five comments were edited after posting. These are the 2026-10-19 roster-correction preambles.

## Change requests (not implemented; need OWNER approval)

`CROSS_ENGINE_CHANGE_REQUEST` 1, for #385.
- Accept what is actually used:
  - comma-separated recipients
  - `as_of` as a declared time
  - the current roster (`implementer_claude`, `owner`; `spec_audit` retired)
  - a mapping from free event names to the 6 classes
- Alternatively, adopt this reader's normalisation as v1.1.
- Today #385 rejects 83 of 88 real messages.

`CROSS_ENGINE_CHANGE_REQUEST` 2, for #447.
- Add fixed-enum `source_role`, `recipient_role` and `project_item_id` lines to the envelope, so an ACK can be matched by role.
- Keep the digest approval, the SQLite `SEND_UNKNOWN` claim, the single POST and no retry exactly as they are.

## What this does not fix

- Platform safety denials of scheduled-task writes. Their cause is UNKNOWN from GitHub, and they must not be bypassed.
- Which tools each ChatGPT scheduled task has. Only the OWNER's task screens show that.
- Role authentication. One shared account cannot prove a role. That needs a per-role signed identity, which is a platform and OWNER decision.
