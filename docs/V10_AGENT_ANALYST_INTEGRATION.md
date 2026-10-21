# V10 specialist AI analysts (GPT API) — integration on the V10 candidate

Status: implemented and tested offline on branch `integ/v10-agent-analyst-20261021`
(base: V10 candidate `4c5720f`). Not deployed. No paid API call has been made by this
change. Research lane only; `real_submit_allowed=false` everywhere.

## Pipeline

```
public evidence JSON (dated, https, as_of <= available_at <= now)        scripts/agent_sdk_public_feed_ingest.py (BOJ RSS) or hand-made
  -> 4 specialists via GPT API: premarket / pre_next / supply_sq / revenue_hunter
  -> deterministic checks + coordinator (conflicts, next checks)          scripts/agent_sdk_coordination_pilot.py
  -> signed private envelope (HMAC, sidecar key)                          scripts/agent_sdk_brain_handoff.py
  -> Brain receiver in the V10 Brain observer: verify, durable receipt,
     Brain ACK (separate receiver key), display view                      scripts/v10_brain_agent_research_receiver.py (+ ai_brain_observer.py opt-in)
  -> Gateway /agent_research.json (read-only, safety flags re-checked)   downloads/AI_COCKPIT_GATEWAY_V10.ps1
  -> BRAIN tab "専門AIアナリスト"                                          index.html
```

The existing ChatGPT Tasks and chat-to-chat/copy-paste routes are not used.

## Every report (result schema `100b-agent-bridge-result-v2`)

| Field | Meaning |
|---|---|
| `report_id` | `<run_id>.<role>`; the same id appears in the envelope, the Brain ACK, the display view and the screen |
| `role` (担当) | premarket, pre_next, supply_sq, revenue_hunter |
| `lane` | `MARKET_RESEARCH_NOT_EXECUTION`, or `PROJECT_PROGRESS_NOT_TRADING` for Revenue Hunter (never compared with market roles, never a trade input) |
| `target_at` (対象日時) | from `--target-at` (offset-aware) |
| `generated_at`, `expires_at` (有効期限) | `expires_at = generated_at + ROLE_VALIDITY[role]` (checked again by the handoff verifier) |
| `evidence_ids`, `evidence` (出典) | only supplied source ids; `evidence` repeats each cited source's URL and `available_at` |
| `hypothesis`, `conditions` (成立条件), `invalidation` (撤回条件) | model text, length-checked |
| `status` | WATCH / NO_SIGNAL, or NO_DATA (no source for the role), or UNAVAILABLE (`API_OR_RUNTIME_FAILED` / `OUTPUT_VALIDATION_FAILED`) |

On the screen a report is usable as research only while it is unexpired, has at least one
cited source and is WATCH/NO_SIGNAL. Expired, unsourced, NO_DATA and UNAVAILABLE reports
are shown as 利用不可 with the reason; the browser re-checks the expiry itself.

## Failure isolation

- One role's API call or output failing makes only that role UNAVAILABLE; the others and
  the coordinator still run. If no role is usable the coordinator is UNAVAILABLE.
- The sidecar is a separate, manually started process. The Brain observer runs the
  receiver inside a try block every 30 s; a receiver error is printed and the observer
  keeps running. The Gateway route returns DISABLED/UNAVAILABLE JSON and never touches
  `/live_ms2.json`, `/health` or the Collector. MS2 collection does not depend on any of it.

## Cost and duplicate charging

Carried over from #481 (OWNER decision 2026-10-20/21): model pinned `gpt-5.4-mini`,
`max_turns=1`, 600 output tokens, 30 s timeout, `max_retries=0`, no tools, traces off,
custom endpoint/model refused; $1 reserved per paid run before any request, lifetime local
reservation $8 (8 runs) against the $10 prepaid credit with auto-reload off.

Added here: one paid run per (JST target date, `--slot`) (`BILLABLE_SLOT_ALREADY_RUN`)
and at most `PAID_MAX_RUNS_PER_JST_DAY = 2` paid runs per JST day
(`DAILY_PAID_RUN_CAP_REACHED`), both in the same crash-safe reservation transaction
as the existing run-id replay block. A run now makes at most 5 model calls
(4 specialists + coordinator). The local reservation is not an actual-dollar hard stop;
actual usage must be reconciled in the OpenAI Usage page.

## Not decided yet (provisional values in code)

- Run frequency / schedule: manual only. No scheduled task is created.
- `ROLE_VALIDITY`: premarket 3 h, pre_next 24 h, supply_sq 24 h, revenue_hunter 7 days.
- `PAID_MAX_RUNS_PER_JST_DAY = 2`.
- Sources for premarket and revenue_hunter: none approved yet, so those roles are NO_DATA
  until a dated public source with confirmed reuse rights is added.

## Keys (unchanged)

`OPENAI_API_KEY`, `AGENT_BRIDGE_HMAC_KEY` (sidecar) and a different
`AGENT_BRAIN_RECEIVER_HMAC_KEY` (receiver) live only in the OWNER PC environment.
`V10_AGENT_RESEARCH_INBOX` (absolute private folder outside the repository) turns the
receiver and the Gateway route on; unset means off.

## Manual run (after OWNER approval of the exact SHA and of a paid run)

```powershell
python -B scripts\agent_sdk_public_feed_ingest.py --fetch --run-id <new id> --output <PRIVATE_PARENT>\evidence.json
python -B scripts\agent_sdk_coordination_pilot.py --input <PRIVATE_PARENT>\evidence.json --enable-billable-api `
  --paid-budget-db <PRIVATE_PARENT>\paid_attempts.sqlite --receipt-db <PRIVATE_PARENT>\pilot_receipts.sqlite `
  --handoff-dir <INBOX> --target-at 2026-10-22T08:30:00+09:00 --slot premarket_0830
```

The Brain observer receives within 30 s when `V10_AGENT_RESEARCH_INBOX=<INBOX>`; the
envelope must be received within 15 minutes of emission or it is BLOCKED (stale).

## Evidence that is NOT produced by CI

Real API connectivity, actual cost, Brain receipt on the OWNER PC, screen display on the
OWNER PC and OWNER Windows acceptance all require separate runs on the PC.
