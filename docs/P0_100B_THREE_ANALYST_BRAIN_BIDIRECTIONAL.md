# P0-100B-THREE-ANALYST-BRAIN-BIDIRECTIONAL-20261022

OWNER instruction 2026-10-22 (GPT direction check). OWNER note: writes to the
ChatGPT scheduled tasks are expected to stay BLOCKED; the GPT API lane was
introduced as the connectable path. The loop is therefore closed inside the
API lane, and the scheduled-task side is read-only (Issue #282 metadata).

Research only. `real_submit_allowed=false`, no paid call, no deploy, no merge,
no scheduled-task change, no GitHub write.

## Phase 0: what exists (checked 2026-10-22 05:40 JST)

Evidence base: PR #486 (Draft, HEAD 9c4c6e8), V10 launcher on 2a72a23 (branch
integ/v10-gpt-coord-20261022), Issue #282 (200 comments, last 2026-10-20),
first paid run `live_20261022_01` (2026-10-22 04:55 JST).

| # | Item | State | Evidence / gap |
|---|------|-------|----------------|
| 1 | 3 specialists -> Issue #282 REPORT | READ_VERIFIED (write probes only) | 2026-10-19 PRENEXT/SUPPLY/REV-WRITE-PROBE-20261019-01. No analytic REPORT since. |
| 2 | Coordinator -> specialist ACK | READ_VERIFIED | COORD-ACK-*-WRITE-PROBE-20261019. Next-run readback by the specialists: not seen. |
| 3 | GPT API specialist run | PRODUCTION_VERIFIED once | live_20261022_01: pre_next/supply_sq NO_SIGNAL, premarket/revenue NO_DATA, coordinator UNAVAILABLE (fixed in 2a72a23). |
| 4 | GPT API -> Brain signed delivery | DEPLOYED | agent_research_live_20261022_01.json in the OWNER inbox. |
| 5 | Brain receive, store, ACK | DEPLOYED, TESTED | receiver v3, SQLite receipts, ACK restore; real receipt pending the next V10 start. |
| 6 | Brain -> specialist feedback | **NEW (this branch), TESTED** | `scripts/v10_brain_agent_feedback.py` |
| 7 | Specialist re-reads feedback next run | **NEW (API lane), TESTED**; scheduled tasks HANDOFF_PENDING | read receipt `agent_feedback_read_<run_id>.json` |

## Loop in the API lane (new)

1. Brain observer, after each receiver pass: one feedback per report
   (`fb.<report_id>`): verdict (PENDING_OUTCOME / PENDING_VERIFICATION /
   INSUFFICIENT_EVIDENCE / RUN_FAILED), evidence used, missing evidence, outcome
   and measured EV/PF/N = UNKNOWN (never backtest numbers), one improvement
   request. SQLite `brain_agent_feedback.sqlite`; newest per role signed in
   `<inbox>/feedback/brain_feedback_<role>.json`.
2. Next research run (pilot, `--handoff-dir`): verified, unexpired feedback of a
   role goes into that role's model input as untrusted data (`brain_feedback`).
3. After the envelope: signed `agent_feedback_read_<run_id>.json` lists exactly
   which feedback_id/sha256 went into which role's input.
4. Brain verifies it and marks the feedback DELIVERED_TO_NEXT_RUN with the run_id.
   This proves delivery to the next run, not that the model followed it; that is
   judged from the next reports and outcomes.

Keys: no new environment variable. HMAC keys are derived from the bridge key
with distinct labels (feedback, read receipt), separate from the envelope key;
the Brain-only receiver key and its ACKs are unchanged.

## Scheduled tasks (Issue #282)

`scripts/coord_issue282_reader.py` reads operator-fetched comments (no network,
no write): REPORTs from and ACKs to pre_next / supply_sq / revenue_hunter, once
per message_id, metadata only. Return direction: **HANDOFF_PENDING**. No
authorized interface writes into a ChatGPT scheduled task; nothing here posts on
anyone's behalf. Needed for END_TO_END: an OWNER-approved posting identity for
public-safe feedback metadata on Issue #282, and each scheduled run reading it
back independently.

## Stage per specialist (API lane)

| Specialist | Forward (report -> Brain) | Return (feedback -> next run) | END_TO_END |
|---|---|---|---|
| PRE-NEXT | WRITE_VERIFIED (live_20261022_01) | TESTED (synthetic) | Not yet: needs a second approved paid run |
| Supply/SQ | WRITE_VERIFIED (live_20261022_01) | TESTED (synthetic) | Not yet: same |
| Revenue Hunter | CONFIGURED (NO_DATA, not called) | TESTED (synthetic) | Not yet: needs verified revenue records |

## Not done / OWNER decisions

- Paid input limit for all-issue JPX margin (A: 24,000 bytes / B: 8,000).
- Outcome scoring (MISSED_SIGNAL / FALSE_ALERT, EV/PF/N) needs WATCH reports to
  carry a structured code and direction; requested in the feedback, UNKNOWN now.
- Real revenue, cost, net profit and the remaining amount to 100 billion JPY: UNKNOWN.
