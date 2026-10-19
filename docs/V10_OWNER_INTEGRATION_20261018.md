# V10 OWNER integration candidate — 2026-10-18

Status: IMPLEMENTED; synthetic CI and independent integration review required. No production acceptance or merge authorization.
Safety: REAL_SUBMIT_ALLOWED=false; STOP_ALLOWED=false; CUTOVER_ELIGIBLE=false.

## Fixed source evidence and integration decisions

| PR | Reviewed HEAD | Decision |
|---|---|---|
| #434 | 51f9278cc4e062dfb580d1ecf98ac54b05cd0875 | Include exactly its 6 CI/diagnostic files; Acceptance 10 uses the unchanged 115-ID exclusion list, all-or-none discovery and fail-closed current suite. Excluded does not mean passed. |
| #435 | c391f1092d8dc91b2bc1c7b0fc327b4745de418b | Include functionality: STOP source already identical in #441. Bring the original exact-argv test and hosted process regressions via #438; do not import divergent older history. |
| #438 | 0ed9e070efc9333865fcd0760359aa8d89814451 | STOP/preflight sources already inherited; add the original 3 test files to the required runtime bundle Windows job. |
| #439 | 420ecd4ef052d5187d0cc1ac9a254734682a074d | Inherit source pin and guarded entry through #441 ancestry. |
| #440 | 6449cf7ace3bf234b9e745f773fd651925189bdd | Inherit 29-component runtime/UI candidate through #441. |
| #441 | 44f417a8b13c8b6b207756cc41c7d16d317975dd | Inherit scoped localhost browser security repair; add bounded freshness/privacy changes below. |

Proposed replacement list after independent integrated acceptance: #438, #439, #440, #441. #434/#435 functionality is included, but their closure remains a separate OWNER decision. No old PR is closed by this candidate. No new consolidated PR existed in the fetched open-PR inventory before this work; this draft is proposed as that candidate, based against main, not a bulk merge of the old V10 stack. #442 (Shadow) and #443 (canonical documents) stay outside this change.

## #441 independent audit evidence

OWNER supplied the Claude re-audit PASS at exact 44f417a in the 2026-10-18 instruction. Independently checked the code, PR discussion and Actions run 39081576738 (pull_request, exact head, success): Windows 14 tests PASS, actual AST-extracted Collector/Watcher HTTP loops, real symlink refusal and health path suppression. Formal GitHub reviews were empty at retrieval; the PR comment requests re-audit and does not itself contain the subsequent Claude response.

Development-lead recommendation: accept P0-1 within that bounded #441 browser-security scope on the OWNER-attested re-audit plus matched source/CI. Coordinator's formal acceptance and integration approval remain separate. Do not describe an unperformed audit as completed. A PowerShell User-Agent is NOT local-process authentication; no privileged/order capability may rely on it. This candidate is not independently audited.

Evidence:
- https://github.com/infoyuusuke-afk/trade-cockpit/pull/441#issuecomment-6243558199
- https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39081576738
- https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6243564254

## OWNER additions

- Acceptance 6 (bounded implementation): Watcher HTTP rejects missing/malformed/wrong-schema/wrong-source data, missing/non-JST/future/older-than-60s publication timestamps, timestamp disagreement, stale/conflict flags and reparse files. File age is also bounded. Rejection returns 503 with no price/signal payload. This validates declared lineage and publication freshness, not cryptographic MS2 authentication or exchange quote freshness.
- Privacy: Collector publication and rejection responses expose only the workbook filename. A SHA-256 normalized canonical path identifier preserves comparison in both Collector and Gateway; no absolute path is serialized in workbook_full_name. This identifier is pseudonymous and potentially guessable, NOT authentication or a claim of irreversible anonymity. Full-path/COM identity checks remain private to the producer. Stale Collector/Gateway responses clear current_price.
- Collector positive synthetic test: original AST listener with deterministic fake process inventory, synthetic fresh diagnostics and workbook identifier must return 200; wrong ID/identity/symbol/full path and stale payload must fail closed. No real Excel/MS2 process is queried by this fixture.
- Acceptance 8: original hosted test `test_unrecorded_excel_collector_watcher_survive_valid_stop` checks unrelated synthetic processes survive. Fake EXCEL.EXE is a renamed PING fixture, NOT real Excel. Business-Excel coexistence remains OUT OF SCOPE per OWNER 2026-10-17.
- Acceptance 10: exact #434 list/runner is included. Record collected, executed, skipped and excluded counts separately. This main-based source may match zero legacy IDs; do not import old scripts just to create 115 exclusions. Original legacy tests remain in their historical PR and manual diagnostic workflow is preserved.
- Work limit: push current coherent commit, report unfinished work and stop if the limit is reached. Never interpret a quota stop as completion.

## Remaining acceptance

Integrated independent review, full Acceptance 1–10 beyond the explicitly evidenced subsets, actual Windows MS2/data source authentication, BRAIN/UI truthfulness, owned-process safety outside the existing synthetic cases, release pin and approved cutover remain PENDING/BLOCKED. No OWNER runtime, production port, Excel, STOP or order action is performed. No release pin is generated. CI process execution is confined to disposable hosted Windows runners. Historical source/CI PASS does not prove deployment, live trading performance or profit.
