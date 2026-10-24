# D-041 paid GPT runs: spend record and the 08:30 / 12:15 schedule (draft)

Status: implemented and synthetically tested on `integ/v10-audit-fix-20261022`; not deployed.
No paid run, no task registration and no admin key were used.

## Spend record (items 1, 2 and audit 6339629207 item 5)
- Two copies of the paid spend record: a file under the per-user LocalAppData folder
  (path from the Windows known-folder API, not from an environment variable) and the
  HKCU value `Software\100B_AGENT\PaidSpend\Record`. Each holds the ledger ids, the highest
  lifetime reservation (cents) and a revision counter.
- Before a paid reservation both copies must exist and be identical, every active ledger
  must be listed, and the registry/ledger total must not be below the recorded high-water
  mark. Otherwise the run stops before any request (`..._NO_CALL`).
- Nothing is created automatically. A PC with neither copy adopts the record once with
  `python scripts/agent_sdk_coordination_pilot.py --adopt-spend-anchor`, and only while its
  ledger already holds reservations.
- Per-run reservation 25 cents (OWNER 2026-10-22); 8 USD lifetime, 2 runs per JST day,
  one run per day and slot, no retry: unchanged.

### Residual risk (not solved)
Both copies and the ledger belong to the same Windows user. A process running as that
user can delete all of them. The OpenAI prepaid balance with auto-reload off stays the last
stop. Provider cost reconciliation (D-041 item 4) and independent OWNER authorization
(item 3) are not part of this change.

## Schedule (audit item 6)
- `downloads/AGENT_PAID_SCHEDULED_RUN.ps1 -Slot 0830|1215` runs one specialist GPT run on a
  weekday inside a 30-minute window after the slot, only when the OWNER's standing approval
  file names this checkout's exact HEAD and the slot. It issues the run id
  `sched_YYYYMMDD_HHMM` itself; every money limit above is still enforced by the pilot.
- `downloads/REGISTER_AGENT_PAID_SCHEDULE.ps1 -ApprovedSha <40 hex> -OwnerMessage "<words>"`
  writes that approval file and registers the two weekday tasks. Run it only after the OWNER
  approved that SHA. `-Unregister` removes both tasks and the file.
