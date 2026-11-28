# OWNER Windows acceptance — specialist AI analysts (T18 procedure)

This is the procedure. It has not been run. Each step needs the OWNER's approval of the exact SHA.
Paid steps also need the OWNER's spend approval.

Assumptions:
- The checkout is a clean copy of the approved SHA, not the folder of the V10 that is running.
- `<PRIVATE>` is an absolute folder outside the repository, for example
  `D:\100億PROJECT\AGENT_RESEARCH_INBOX`.
- Keys are 64-hex secrets kept only in the OWNER's user environment. Never put them in chat,
  GitHub or logs.

## A. No cost (offline)

1. Run `python -m unittest discover -s tests -p "test_agent_*.py"` and
   `python -m unittest discover -s tests -p "test_v10_*agent*.py"`. All must PASS.
2. Run `python scripts\agent_sdk_coordination_pilot.py --print-settings`. Check that the
   APPROVED and PROVISIONAL marks match the OWNER's decisions.
3. Set the keys in the environment: `AGENT_BRIDGE_HMAC_KEY` (sidecar) and a **different**
   `AGENT_BRAIN_RECEIVER_HMAC_KEY` (receiver).
4. Build public evidence:

   ```
   python scripts\agent_sdk_evidence_bundle.py --fetch --run-id accept_<date>_01 --output <PRIVATE_PARENT>\evidence.json --boj --jpx-margin-codes 3656,285A
   ```

   It prints the state of each adapter. Write down which codes were found in the JPX file.
5. Offline analysis and handoff (no API):

   ```
   python scripts\agent_sdk_coordination_pilot.py --input <PRIVATE_PARENT>\evidence.json --offline-test --receipt-db <PRIVATE_PARENT>\pilot_receipts.sqlite --handoff-dir <PRIVATE> --target-at <ISO> --slot supply_1730
   ```

6. Brain receipt: run `python -m scripts.v10_brain_agent_research_receiver --private-dir <PRIVATE> --once`.
   The result must be `RECEIVED`, and `<PRIVATE>` must now contain `*.brain_ack.json` and
   `agent_research_display_v1.json`.

## B. In the running V10 (needs the SHA approved and installed; no cost)

7. Set `V10_AGENT_RESEARCH_INBOX=<PRIVATE>` in the user environment, then start V10 with the
   usual 「AIコクピット_起動」.
8. Within 30 s of a new handoff, the Brain observer log shows
   `{"agent_receiver": "PASS", ...}`.
9. Open the BRAIN tab. Check:
   - the 「専門AIアナリスト」 section says 「AI推論・研究用（MS2の実測データではありません）」;
   - each report shows report_id, target, expiry, sources, conditions and invalidation;
   - NO_DATA / UNAVAILABLE / expired reports show 「利用不可」.
10. Negative checks:
    - stop the Brain observer for more than 5 minutes: the section must show
      「利用不可（DISPLAY_STALE_OR_FUTURE）」;
    - edit one character of the display file: 「利用不可（DISPLAY_SIGNATURE_INVALID）」;
    - restart V10: the receipts remain and the same run_id is not received again.
11. Confirm that REALTIME 5, SCALP, FOCUS and MS2 freshness behave as before. Prices still come
    only from MS2, and `real_submit_allowed=false` stays as is.

## C. One paid run (only after the OWNER says so)

12. Run `python scripts\agent_sdk_coordination_pilot.py --init-paid-ledger <PRIVATE_PARENT>\paid_attempts.sqlite`
    once. Then store `AGENT_PAID_LEDGER_PATH` and the printed `AGENT_PAID_LEDGER_ID` privately.
13. If paid runs were made before this ledger existed, record their dates and the Usage amount
    first, so the reconciliation explains them.
14. Set `OPENAI_API_KEY` (private), and set `AGENT_PAID_RUN_APPROVED_RUN_ID=<the new run_id>`
    for this run only.
15. The first paid trial uses only the synthetic fixture with `--synthetic-paid-trial` and no
    `--handoff-dir`. A real-evidence paid run with JPX figures also needs
    `AGENT_PAID_ALLOW_OFFICIAL_STATISTICS=OWNER_DECISION_RECORDED` after the OWNER decides reuse.
    Run the pilot with `--enable-billable-api --paid-budget-db <ledger>` and the same
    `--handoff-dir`, `--target-at` and `--slot`. Do not retry after a failure; the run stays
    reserved.
16. The next day, export Usage from the OpenAI platform and run
    `python scripts\agent_paid_ledger_report.py --ledger <ledger> --usage-csv <export>`. No flags
    must be raised.

## Recording

For each step, record PASS / FAIL / NOT_RUN with time, SHA and screenshot or output. CI PASS is
not PRODUCTION_VERIFIED; only steps B and C on the OWNER PC can support that, and C only for the
research lane.
