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
from tests.test_gnh01_intelligence_contract_v1 import fixture  # synthetic fixture

db = Path("/tmp/gnh01_private_test.db")  # example only; private absolute folder required
event = fixture()
result = archive_event(db, event, clock=lambda: datetime(2026, 10, 22, tzinfo=timezone.utc))
assert result["receipt_independently_read_back"]
assert result["shadow_eligible"] is False
assert read_archive_receipt(db, result["event_id"], 1)["state"] == "ARCHIVED"
```

The path above is illustrative for non-Windows tests. For a Windows test use a dedicated private absolute path selected by the operator, not a project/repo directory.

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
