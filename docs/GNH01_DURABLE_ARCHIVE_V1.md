# GNH01 durable research archive v1 — isolated / default OFF

**PROJECT_ITEM_ID**: P0-GLOBAL-INTELLIGENCE-TO-SHADOW-INTEGRATION-20261022

## 1. Verified scope and boundaries

This isolated Draft #490 implements **offline validation and crash-recoverable storage of untrusted public research claims**. It is *not* an operational Grok connector, a replacement PRE-NEXT, an automated ChatGPT Task, or a Brain/Shadow input. Never describe archive receipt as Grok authentication, market-data provenance, a verified forward-test observation, independent Brain acceptance, or an executable trade signal.

- Sources: `scripts/gnh01_intelligence_contract_v1.py`, `schemas/intelligence_event_v1.schema.json`, `scripts/gnh01_durable_archive_v1.py`.
- Tests: `tests/test_gnh01_intelligence_contract_v1.py`, `tests/test_gnh01_durable_archive_v1.py`.
- CI: `.github/workflows/gnh01-intelligence-contract-offline.yml` (offline only).
- No broker, RssOrder, network, API key, cost-bearing call, running V10, Excel/RSS, UI, start/stop, Gateway, or task prompt changes. `real_submit_allowed=false`.
- This module does NOT run automatically. Calling it with real data requires a separate approved private input adapter and controlled absolute database path.

## 2. Data and point-in-time trust

1. `validate_event` checks structure, source-URL syntax, UTC chronology, canonical content SHA-256 and a no-orders flag. It does **not** verify that the linked external source exists, that the issuer/ticker association is correct, or that Grok actually discovered the event.
2. The upstream `bridge_received_at` remains an untrusted CLAIM. Excluding transport-only fields from canonical content identity permits repeat transport without creating false new information; distinct semantic corrections MUST increment revision.
3. `archive_event` captures **receiver-local** UTC time, inserts a `PENDING` row, commits through SQLite WAL with synchronous FULL, rereads it using a new connection, commits `ARCHIVED` state with local `available_at`, and independently rereads again. A crash between stages leaves recoverable `PENDING`, not a false completed ACK.
4. `read_archive_receipt` returns metadata only. Both content SHA and a separate **unkeyed** metadata checksum detect accidental changes, including timestamp edits. These hashes DO NOT authenticate a malicious database writer.
5. `available_at_verified=false`, `receiver_clock_attested=false`, `source_authenticity_verified=false`, `brain_receiver_ack_verified=false`, `shadow_eligible=false` are invariant. The observed local time is NOT automatically eligible for point-in-time backtest or Brain; an independent source and clock attestation step is still missing.
6. Same event ID + revision + canonical content hash is idempotent. Conflicting hashes are BLOCKED. Revision changes append only in sequence, preserving the prior record. SQLite transactions obtain the write lock BEFORE deduplication reads.
7. Do not put databases or live event bodies on public GitHub. The private storage path must be chosen and access-controlled by the deployment owner; this module only checks that it is absolute and its parent exists (it does NOT establish directory ACLs).

## 3. Isolated offline example (synthetic only)

```python
from datetime import datetime, timezone
from pathlib import Path
from scripts.gnh01_durable_archive_v1 import archive_event, read_archive_receipt
from test_gnh01_intelligence_contract_v1 import fixture  # synthetic fixture, set PYTHONPATH=tests

db = Path("/tmp/gnh01_private_test.db")  # example only; private absolute folder required
event = fixture()
result = archive_event(db, event, clock=lambda: datetime(2026, 10, 22, tzinfo=timezone.utc))
assert result["receipt_independently_read_back"]
assert result["shadow_eligible"] is False
assert read_archive_receipt(db, result["event_id"], 1)["state"] == "ARCHIVED"
```

Run this snippet with the repository root as current directory and PYTHONPATH=tests so the synthetic test fixture is importable. The path above is illustrative for non-Windows tests. For a Windows test use a dedicated private absolute path selected by the operator, not a project/repo directory.

## 4. Test gates and known limitations

- CI evidence: https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/39714853493 — Ubuntu and Windows, Python 3.11 and 3.12, each runs 19 contract tests + 20 archive tests successfully; Windows Japanese-directory tests repeat the suites.
- `jsonschema==4.23.0` is pinned and installed in this **test workflow** so its full structural validation test is not SKIPPED.
- Negative coverage includes malformed timestamps, URL guards, optimistic PRIMARY_VERIFIED claim, duplicate deliveries, changed payload conflicts, nonsequential revision, local clock regression, tampered contents/receipt timestamps/checksum, WAL concurrent duplicate writers, restart after PENDING, and no-real-submit invariant.
- GitHub Windows CI is not OWNER's Windows V10 machine acceptance. The database receipt is local synthetic, not Grok scheduled automation or live Brain receipt.
- The current contract requires a sender-declared `bridge_received_at`; a future adapter MUST produce this field as a clearly marked sender claim and MUST NOT treat it as an authenticated receipt.
- No tenant/authn ACL enforcement, receiver secret, authenticated source verification, independently attested clock, scheduled outbound Grok endpoint, private delivery, PRE-NEXT receiver, signed Brain ACK or SHADOW run is provided here.

## 5. Next isolated step: reuse rather than duplicate

- Inspect the exact current input/output contracts in Draft #481 (signed research envelope), #482 (durable Brain ACK), and #483 (Brain observer opt-in, default OFF), plus #488 bidirectional research lane.
- Identify whether the Grok cloud routine has an **actual unattended export mechanism**. The one-shot GitHub Issue #282 comment https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6331373208 proves only single delivery/readback, not an hourly autonomous exporter.
- After an authorized private export path exists: build a small **isolated** receiver adapter with synthetic data, source authentication/verification, timestamp and replay checks, append-only archive, and a non-trading PRE-NEXT event representation. Only separately independently verified research can be adapted to the existing signed Brain lane.
- Do not modify existing hourly tasks, V10 runtime, or PR #481-#483 in this isolated PR. No merge, deployment, billable API calls, or real order submission.

## 6. Acceptance statuses (not inferred)

| Gate | Status |
|---|---|
| Synthetic schema and archive/clock/restart/concurrency tests | CI PASS |
| Original issuer/news authenticity and ticker identity | NOT VERIFIED |
| Unattended Grok export (hourly :30) | NOT VERIFIED |
| PRE-NEXT receiver and its independent ACK | NOT VERIFIED |
| V10 Brain receiver and private signed ACK for GNH01 | NOT VERIFIED |
| SHADOW virtual execution and EV tracking | NOT VERIFIED |
| Owner Windows V10 production acceptance | NOT RUN |
| Main merge or deployment | NOT PERFORMED |
| Real trading | DISABLED |

## 7. Phase 1C — PRE-NEXT review request (NOT AUTOMATED DELIVERY)

- `scripts/gnh01_pre_next_review_v1.py` builds an in-memory `100b-gnh01-pre-next-review-request-v1` from an event whose immutable content hash/revision matches an independently reread private archive receipt.
- Strict gate: private archive must be ARCHIVED and fresh (maximum 2 hours since local archive completion); missing/tampered/older/future/corrupt data are rejected.
- Every external assertion remains a **claim**. Even sender-marked PRIMARY_VERIFIED is not independent source verification. The exported request explicitly keeps `publication_available_at_verified=false`, `pre_next_delivery_verified=false`, `pre_next_ack_verified=false`, `brain_trade_decision_eligible=false`, `shadow_eligible=false` and `real_submit_allowed=false`.
- Crucially, this object is NOT the `100b-public-agent-evidence-v1` schema from Draft PR #481: #481 requires a verified evidence availability timestamp and specialist research output. Do not forge `available_at` from a Grok claim or local archive time. A separate actual PRE-NEXT receiving process and independent official-source verification must precede any adaptation to #481 and #482/#483.
- This pure converter **does not** read/modify ChatGPT scheduled Tasks, call Grok, post Issue #282, write a delivery queue or claim any PRE-NEXT ACK. The received original JSON must remain in private storage only.
- Safety improvement: archive path guard refuses databases in the GitHub checkout, linked/reparse directories, hardlinks and POSIX directories with broad permissions. This is still not a substitute for Windows ACL validation, which remains a deployment gate.

### Acceptance status

`test_gnh01_pre_next_review_v1.py` exercises matching private receipt, sender-source claims, missing/stale/future data, corrupted payload, mismatched revision and no-execution invariants. These tests are synthetic-only and are included in the isolated Windows/Ubuntu CI matrix. GitHub run evidence must be updated to the exact latest HEAD before any PASS claim.

## 8. Phase 1D — strict JSON ingestion and origin preservation

This extension keeps the existing one-shot, isolated archive—no new IPC,
network listener, webhook, scheduling or broker interface.

- `parse_event_json_bytes` consumes at most 64,000 bytes of strict UTF-8. It
  rejects duplicate JSON keys (including nested keys), floating-point or
  nonfinite literals, invalid UTF-8, BOM, trailing JSON, unexpected root types,
  and malformed inputs. `archive_json_once` parses bytes through this
  guard and reuses `archive_event` durable local receipts. It is not a live
  Grok origin authentication mechanism.
- Duplicate Japanese security codes are normalized for a `.T` suffix during
  structural review: `285A` and `285A.T` cannot both appear as independent
  securities in one event. This is NOT external issuer-identity verification.
- Reject escaped lone Unicode surrogate code points in source URL and news
  text before attempting the canonical UTF-8 content hash.
- PRE-NEXT candidate construction now preserves the **original claimed
  `source_role`**, including `owner_instruction_relay`; no OWNER relay may
  be mislabeled a direct `grok_bot_gnh01` emission.
  `sender_role_authenticated=false`, `grok_direct_emission_verified=false`,
  and `origin_transport_verified=false` remain invariant even when the
  sender claims to be Grok. A GitHub comment by the OWNER or its connector
  cannot prove Grok's unattended automation.
- This is compatible with future inspection of Draft #481's public research
  snapshot, but **DOES NOT** automatically set its `available_at`, which
  requires independent evidence-source availability and authorization.
- Negative tests cover relay-origin laundering, changed role despite a
  matching local archive, ambiguous JSON, ticker suffix duplicates, and
  surrogate Unicode. The exact latest HEAD-specific CI is documented
  in Draft PR #490; all former CI claims apply to the former HEAD only.

### Deferred operational acceptance

To connect the hourly Grok Routine, supply an authenticated **private**
outbound message transport and a receiver whose access rights, source
identity, clock and secrets are separately verified. A public Issue #282
single-shot comment and a local archive receipt are insufficient. PRE-NEXT
and Brain must each independently acknowledge consumption; no automatic
trading or brokerage orders may be enabled.


## 9. Phase 1E — signed private local review / reader-only ACK

Draft-only module: `scripts/gnh01_private_review_handoff_v1.py`, synthetic tests:
`tests/test_gnh01_private_review_handoff_v1.py`.

- `export_review` invokes the earlier archive-backed `build_pre_next_review_request`,
  not an untrusted arbitrary sender dictionary. It exclusively writes one
  canonical JSON, HMAC-SHA256 signed, immutable review-envelope file in a
  private **absolute folder outside the checkout**. No overwrite, raw
  news publication, caller-visible secrets, API calls, timers, or new IPC.
- `receive_review` is an explicit **local test reader**. It independently
  reads a stable regular file, validates HMAC with
  `GNH01_PRENEXT_REVIEW_HMAC_KEY`, checks exact review schema, preserved
  OWNER relay provenance, no-trade/no-elevation flags, 15-minute freshness,
  and receipt filename/content identity. It creates one no-overwrite
  reader-only ACK signed using a *different* key,
  `GNH01_PRENEXT_READER_ACK_HMAC_KEY`, then independently rereads and
  validates that ACK.
- Both environment keys must be distinct 64-character hexadecimal strings
  stored privately by the permitted deployment service. The **synthetic**
  test fixture uses dummy keys only. No live credentials added to GitHub.
  These local HMAC signatures prove possession of local keys, **not** that
  cloud Grok emitted the message, that a scheduled PRE-NEXT task read it,
  or that the official news source/ticker was verified.
- ACK `ack_kind=LOCAL_READER_ONLY_NOT_CHATGPT_PRE_NEXT` and
  `pre_next_scheduled_task_ack=false`; `brain_received=false`,
  `shadow_eligible=false`, `real_submit_allowed=false`.
  A receipt returned from this module MUST NOT be counted as a
  cross-chat ChatGPT Task ACK or `PRIVATE_BRAIN_ACK`.
- Fail-closed cases tested include malformed/duplicate JSON, source-role
  laundering, payload or signature tampering (including a recomputed HMAC
  on a forbidden Boolean), source and ACK key mismatch/missing, duplicate
  send/receive, stale/future timestamp, renamed files, public repo path,
  symlinked private directory, and ACK corruption.
- The module is **manual, on-demand, default OFF**, and has no connector
  to Grok, ChatGPT Tasks, PRE-NEXT running task, existing #481/482/483
  Brain bridge, V10, MS2 RSS, order APIs, UI, or SHADOW. A cloud-to-private
  outbound adapter, real recipient process integration, independent source
  verification and signed Brain ACK remain separate owner-approved gates.
- Windows ACL, clock trust, authentication to an unattended Grok Routine,
  and end-to-end actual receiver authorization remain NOT VERIFIED.
  OWNER must approve deployment location and any costs; no main merge,
  real orders, or schedule changes are implied.

Latest exact-head GitHub CI should be recorded against the actual tested
commit in PR #490; never reuse CI PASS from an older HEAD.
