# V10 specialist AI analysts (GPT API) — market-data input, Brain integration, cost controls

PROJECT_ITEM_ID: P0-V10-GPT-API-BRAIN-MARKET-INTELLIGENCE-20261021
Branch: `integ/v10-agent-analyst-20261021` (PR #486). Not deployed. No paid API call has been made.
Research lane only; `real_submit_allowed=false` everywhere; nothing here can place or approve an order.

## Pipeline

```
public sources (manual --fetch)                          scripts/agent_sdk_evidence_bundle.py
  BOJ RSS headlines -> pre_next / supply_sq              scripts/agent_sdk_public_feed_ingest.py
  JPX 日々公表銘柄等信用取引残高 -> supply_sq            scripts/agent_sdk_jpx_margin_ingest.py
  -> one evidence file, schema 100b-public-agent-evidence-v2
-> 4 specialists via GPT API (premarket / pre_next / supply_sq / revenue_hunter),
   each only with its own eligible sources, then deterministic checks + coordinator
                                                         scripts/agent_sdk_coordination_pilot.py
-> signed private envelope (sidecar key)                 scripts/agent_sdk_brain_handoff.py
-> Brain receiver inside the V10 Brain observer: verify, SQLite receipt, Brain ACK
   (separate receiver key), signed display view          scripts/v10_brain_agent_research_receiver.py
-> Gateway /agent_research.json re-verifies the view's signature and age
                                                         downloads/AI_COCKPIT_GATEWAY_V10.ps1
-> BRAIN tab "専門AIアナリスト" (AI inference, research only)   index.html
```

## Evidence v2 (time contract)

Every source has `source_id, role, source_url, source_name, source_type, as_of, available_at,
fetched_at, data_status, summary`.

- The timestamps must be ordered `as_of <= available_at <= fetched_at <= now`.
- `data_status` is either `PUBLICATION_TIME_VERIFIED` (the publisher states the release time)
  or `DATE_ONLY_OBSERVED_AT_FETCH`. For a date-only source, `available_at` must equal
  `fetched_at`: no earlier release clock is invented.
- URLs must be public https, with no credentials, query or fragment.
- v1 evidence is refused.

A role only receives sources that meet both conditions:
- published at or before `target_at` (no lookahead);
- within its window: premarket 18 h, others 7 days (provisional).

The excluded ids are recorded in the report and re-checked by the handoff verifier. A role with
no eligible source is `NO_DATA` (`NO_SOURCE` or `NO_ELIGIBLE_SOURCE`); nothing is guessed.

## Data sources

| Source | Role | State |
|---|---|---|
| BOJ RSS (whatsnew, statistics) | pre_next, supply_sq | connected; headline metadata only |
| JPX 日々公表銘柄等信用取引残高 (daily, "16:00を目安") | supply_sq | connected: index page → newest `*_mtdaily.xlsx`, allowlisted path, no redirects, stdlib xlsx reader; requested codes only. It covers daily-publication issues only and is NOT the daily margin balance of all issues. Checked once against the live 2026-10-21 file: 347/347 rows parsed. The file is not committed |
| JPX 投資部門別 先物・OP (weekly CSV, 4th business day 15:30) | supply_sq | not connected: the CSV uses numeric product/investor codes whose table is not published with it; reading them by guess is refused |
| JPX 投資部門別 株式 (weekly xlsx), 裁定取引 (weekly) | supply_sq | not connected yet (multi-level headers; next candidate) |
| TDnet 適時開示 | pre_next | not connected: `release.tdnet.info/robots.txt` disallows all automated access; the paid TDnet API is an OWNER decision |
| J-Quants daily margin of all issues | supply_sq | not used: contract and cost are OWNER decisions |
| Overseas indices before the open | premarket | not connected: no approved free source with a verified time contract yet |

Reuse rights: fetched figures stay in private files (never GitHub). Sending them to a paid model
is an OWNER decision.

## Reports (result v3)

Every report has:
- `report_id` (`<run_id>.<role>`), `role`, `lane`, `target_at`, `generated_at`, `expires_at`;
- `evidence` (id, URL, source name, data status, available_at) and `excluded_source_ids`;
- `hypothesis`, `conditions`, `invalidation`;
- `status` WATCH / NO_SIGNAL / NO_DATA / UNAVAILABLE.

Revenue Hunter is in `PROJECT_PROGRESS_NOT_TRADING` and is never compared with the market roles.
One role's API or output failure makes only that role UNAVAILABLE.

## Brain receipt, ACK and display authenticity

- Envelope: HMAC with the sidecar key; schema, safety flags and source binding are checked;
  it must be received within 15 minutes of emission.
- Receipt: SQLite (BEGIN IMMEDIATE, synchronous=FULL); a run_id is received once; receipts and
  ACKs survive a restart.
- Brain ACK: signed with a separate receiver key and read back independently.
- Display: `agent_research_display_v1.json` is a signed wrapper (`body_json` plus an HMAC with
  the receiver key).
- Gateway `/agent_research.json` re-verifies, with the same private key:
  - the signature;
  - the schema and the flags (`real_submit_allowed`, `brain_trade_decision_eligible` and
    `live_market_data` must all be false);
  - that `generated_at` is within 300 s.

  Otherwise it answers 503 UNAVAILABLE with a reason, and the screen shows that reason.
- A report is shown as usable only while it is unexpired and sourced. Expired, unsourced,
  NO_DATA and UNAVAILABLE reports are shown as not usable.

## Paid-run controls (nothing runs without the OWNER)

Before any request:
- the run is blocked unless `--enable-billable-api` and `OPENAI_API_KEY` are both given;
- the pinned model, with no custom endpoint;
- input ≤ 8 KB;
- **the one fixed ledger**: `--paid-budget-db` must be `AGENT_PAID_LEDGER_PATH`, and the ledger's
  stored id must equal `AGENT_PAID_LEDGER_ID`. A new or swapped file is refused, so counts cannot
  be reset. Create the ledger once with `--init-paid-ledger <absolute path>`;
- **explicit approval**: `AGENT_PAID_RUN_APPROVED_RUN_ID` must equal this run_id;
- the crash-safe reservation, which blocks:
  - a replay of the same run_id;
  - a second run for the same JST date + slot;
  - more than 2 runs per JST day;
  - more than the $8 lifetime reservation;
- each reservation records the model, max output tokens, timeout and maximum model calls;
- `max_retries=0`, so nothing is re-sent after a failure or timeout.

Evidence a paid model may receive (audit D1/D5):
- `OFFICIAL_STATISTICS_FILE` rows (e.g. JPX margin figures) are refused unless
  `AGENT_PAID_ALLOW_OFFICIAL_STATISTICS=OWNER_DECISION_RECORDED` is set after an OWNER decision
  on reuse.
- `SYNTHETIC_TEST` evidence runs only with `--synthetic-paid-trial`. It is never mixed with real
  evidence and is never handed to the Brain.

Ledger registry (audit D3):
- `%LOCALAPPDATA%@B_AGENT\paid_ledger_registry.json`, or `AGENT_PAID_LEDGER_REGISTRY`, records
  the active ledger.
- A new ledger can only be created when none is active.
- `--retire-paid-ledger <id> <reason>` closes the active ledger and carries its reserved total
  forward, so the $8 lifetime allowance continues across ledgers.
- The paid run is refused unless the configured ledger is the registered active one.

Known limitations (audit D2/D3; need an OWNER decision number):
- The per-run approval variable and the registry are set by the same Windows user. A process
  running as that user, including an AI executor, could set or delete them. They are deliberate
  per-run steps, not proof that the OWNER approved.
- Deleting the registry file still lets the counts restart. The reconciliation report then shows
  `USAGE_WITHOUT_RESERVATION`, but only after the fact.

Usage reconciliation (audit D4/D5): the report compares each reservation on the Usage export's
calendar. The default is UTC; use `--usage-dates JST` otherwise. It prints the ledger's
`ledger_id` and flags `LEDGER_IDENTITY_MISSING`.

The local reservation is not a provider-side stop. To reconcile it with OpenAI Usage, run
`scripts/agent_paid_ledger_report.py --ledger <ledger> --usage-csv <Usage export>`. It flags:
- usage on a day with no reservation;
- usage above that day's reservations;
- a total above the $10 credit.

`python scripts/agent_sdk_coordination_pilot.py --print-settings` prints every limit with its
status:
- APPROVED (OWNER, #481): model, retries, tokens, timeout, $1 per run, $8 lifetime.
- PROVISIONAL: calls per run, runs per day, the slot rule, validity, source windows.
- UNDECIDED: run frequency.

## Not done / not claimed

- Real API connectivity: not run.
- Brain receipt in the running V10 on the OWNER PC: not run.
- Screen check on the OWNER PC: not run.
- OWNER Windows acceptance: not run (see `docs/V10_AGENT_ANALYST_WINDOWS_ACCEPTANCE.md`).
- Actual revenue, realized P&L, costs, net profit and the remainder to 10 billion yen: UNKNOWN.
