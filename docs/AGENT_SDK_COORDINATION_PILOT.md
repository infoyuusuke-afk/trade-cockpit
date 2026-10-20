# 100億PROJECT — OpenAI Agents SDK coordination pilot

Status: DRAFT / OFFLINE RESEARCH ONLY / NOT DEPLOYED. A Draft PR does not authorize an API cost or a runtime change. The new agents are NOT the existing ChatGPT Tasks. The old tasks remain scheduled and unchanged.

## Purpose

An independent, explicitly initiated programmatic coordinator running PRE-NEXT, supply/SQ, Revenue Hunter and an overarching coordinator. The official OpenAI Agents SDK (https://openai.github.io/openai-agents-python/) is imported only when there is an explicit OWNER-approved billable API trial.

Pipeline: public-only, dated evidence JSON -> three separated specialist research agents -> coordinating research agent -> validated research-only result -> optional locally stored receipt.

The system has NO broker, Excel, MS2, V10 runtime, GitHub writing, scheduled Tasks, private market data, payment, or auto-deployment tool. Existing safety gates and Task settings are untouched.

## Offline synthetic validation (no key and no network)

    python -m unittest discover -s tests -p test_agent_sdk_coordination_pilot.py -v

Provide an explicitly public-safe JSON file with schema_version, run_id and up to 30 sources. Every source must contain exactly the following fields:

- source_id: unique public-safe identifier
- role: pre_next, supply_sq or revenue_hunter
- source_url: public HTTPS URL with no credentials, query or fragment
- as_of: observation timestamp in offset-aware ISO 8601
- available_at: earliest public availability timestamp
- summary: at most 400 characters of NONPRIVATE public evidence

Synthetic example, NOT market evidence:

    {
      "schema_version": "100b-public-agent-evidence-v1",
      "run_id": "synthetic_20261020_01",
      "sources": [{
        "source_id": "example_jpx_001",
        "role": "supply_sq",
        "source_url": "https://www.jpx.co.jp/markets/",
        "as_of": "2026-10-19T09:00:00+09:00",
        "available_at": "2026-10-19T15:00:00+09:00",
        "summary": "Synthetic example only; no real market claim"
      }]
    }

Save to a local example.json and run:

    python scripts/agent_sdk_coordination_pilot.py --input example.json --offline-test

Expected state OFFLINE_SYNTHETIC_NO_API_CALL. The offline provider is a stub and performs ZERO model inference or external communication. Roles lacking input return NO_DATA.

## Phase 4 (isolated): Agents SDK -> signed private Brain RESEARCH sidecar

This branch now contains \`scripts/agent_sdk_brain_handoff.py\` plus
\`tests/test_agent_sdk_brain_handoff.py\`. This is a PRIVATE FILE handoff
prototype only. It is NOT connected to the running Brain process,
not a replacement for \`v10_brain_research_consumer.py\`,
and cannot change V10, the Excel instance, the market-data gate,
safety/permission/kill switches or orders. It never sends public GitHub
comments. Scheduled tasks and API billing settings remain unchanged.

Handoff is strictly OPT IN through --handoff-dir. A future successful
\`agent_sdk_coordination_pilot.py\` run may export the validated full
research result and its PUBLIC-only source metadata after its receipt is
recorded. Earlier runs only stored hash-based SQLite receipts, not
recoverable model outputs: **do not replay earlier billable run IDs** and
do not reconstruct missing payloads as if they had been observed.

Safety contract:
- Local private directory OUTSIDE git and V10, explicitly owner-selected,
  no symlink/reparse component. One \`agent_research_<run_id>.json\` file,
  opened once exclusively with no overwrite or hidden retry.
- Source identity and strict evidence IDs bound to model output. Result
  always RESEARCH_ONLY or OFFLINE_SYNTHETIC, no trade/profit/provenance
  promotion. Reject future, stale >15-minute handoffs, unknown timestamp
  offsets and changed/tampered JSON; no last-good fallback.
- Full JSON payload covered by HMAC-SHA256 with a separately generated
  32-byte signing key provided as exactly 64 hex characters through the
  private environment variable \`AGENT_BRIDGE_HMAC_KEY\`.
  Never paste this secret in chat, GitHub or Logs, and do not conflate
  HMAC possession with official market/source authenticity.
- Research-only receiver validates content, timestamps, file identity,
  HMAC, source fingerprint, role outputs and disabled order flags,
  and may create exactly one **local sidecar** ACK
  \`agent_research_<run_id>.ack.json\`. Replays fail CLOSED.
  This confirms sidecar receipt only; it is not ACK from a live Brain.
- Use the preexisting paid-attempt reservation and OpenAI Usage audits for
  any future OWNER-approved paid run. New handoff capability does not
  authorize billable calls, a scheduler, a daemon or a production cutover.

**Offline-only Windows test plan (no OpenAI API):** take an explicitly
new unique synthetic run ID in a separate copy of the public synthetic
fixture, and use a new private temporary directory. The signer HMAC
must first be generated privately on the PC. Do not disclose it in chat.
Call the existing pilot with --offline-test --receipt-db <private-db>
--handoff-dir <private-dir>, then call:

    .\.venv\Scripts\python.exe scripts/agent_sdk_brain_handoff.py --consume "<private-dir>\agent_research_<run_id>.json" --private-dir "<private-dir>" --write-ack

Expected receiver state is
\`RESEARCH_ONLY_ACK_RECEIVED_NOT_BRAIN_LIVE\`, not \`LIVE\`,
\`END_TO_END_VERIFIED\` or market-trading eligibility. The previous
12 BOJ RSS pieces can only be reused for read-only provenance display;
they cannot be replayed into another paid run without fresh evidence,
a new ID, Usage reconciliation and OWNER approval.

**Next gated milestone:** technical contract review by Claude V10
development lead, explicit owner-approved configuration of a Brain-side
inbox reader, and real Windows acceptance. No edits to V10 in this PR.
Only once the actual Brain consumer independently reads a signed
handoff and emits its own verified ACK can \`END_TO_END_VERIFIED\`
be considered, and even then research-only until separately authorized.

## Phase 3: official BOJ RSS -> evidence JSON (manual, no billable AI)

Draft-only intake is implemented in scripts/agent_sdk_public_feed_ingest.py.
BOJ officially publishes RSS (website updates and statistics). Only TWO
pinned, official RSS endpoints may be fetched and only on explicit --fetch:

- https://www.boj.or.jp/rss/whatsnew.xml => pre_next (macro/regime news CONTEXT ONLY)
- https://www.boj.or.jp/rss/statistics.xml => supply_sq (macro statistics releases CONTEXT ONLY)

Revenue Hunter is NO_DATA until an independently authorized, dated business
evidence source is added. No stock-specific JPX daily credit amounts, no MS2
quotes, no J-Quants tokens, no paid TDnet API, no scraping, and no trading calls
are in this adapter. JPX publishes RSS guidance, but an exact approved source
URL and reuse rights must be separately checked before adding that source.

The parser accepts only www.boj.or.jp official item links with NO
credentials, nondefault ports, query strings or fragments. BOJ's RSS includes
legacy http://www.boj.or.jp item links. Such links are normalized IN MEMORY
to the identical https://www.boj.or.jp path and only the canonical HTTPS URL
is saved as public provenance. No HTTP article request or redirect is made.
A Windows HEAD probe for a sample canonical article URL returned HTTP 200
(OWNER observation, 2026-10-21; not a bulk proof of all article links).
Full publication timestamps require an explicit timezone; offsetless times, malformed/future entries and content older than
seven days are REJECTED. Some official feeds publish only a YYYY-MM-DD
calendar date, with NO PUBLICATION CLOCK. Such items are accepted only as
CURRENTLY OBSERVED HEADLINE EVIDENCE: as_of = available_at = FETCH TIME,
with DATE_ONLY_OBSERVED_AT_FETCH and the source's calendar date explicitly
recorded in summary. This NEVER invents an earlier exact release time,
creates positive lead-time evidence, or allows intraday signals. With a
verified full timestamp, as_of = feed-declared publication timestamp and
available_at = fetch time (CONSERVATIVE first actually verified access,
NOT proof of the earliest release). It records only short headline text and
link, never downloads the article or statistic contents.
Therefore it CANNOT verify statistical figures or prove market opportunity.
Explicit DOCTYPE/ENTITY XML is prohibited and redirects are not followed.

For one-time Windows local diagnostic (NO OpenAI API charges, NOT scheduled),
first ensure an output folder outside the repository, for example a
user-private folder. Choose a NEW run_id and unused filename on each explicit
manual attempt. Never put fetched sources into public GitHub:

    .\.venv\Scripts\python.exe scripts/agent_sdk_public_feed_ingest.py --fetch --run-id boj_pilot_20261021_01 --output "<private-path>\official_boj_feed.json"
    .\.venv\Scripts\python.exe scripts/agent_sdk_coordination_pilot.py --input "<private-path>\official_boj_feed.json" --offline-test

"OFFLINE_SYNTHETIC_NO_API_CALL" tests routing only; an actual AI analysis
would need a separately approved new PAID run ID, reconciliation of
prior Usage, and independently verified content rights/provenance.

Phase 3 is NOT yet production complete: first real BOJ HTTP download and
parse must pass on OWNER Windows with local time and source provenance;
revenue_hunter, JPX margin balances, exact publication-time proof,
true agent source-verification and content-based extraction remain pending.
No V10/Brain live inbox or recurring task connection is implemented.

## Paid API: manual, locally reserved, OWNER-approved $10 pilot (NOT deployed)

OWNER reported a one-time initial API credit purchase of $10 (tax extra) and disabled
auto-reload on 2026-10-20/21. This authorizes only a tightly scoped, manually
initiated pilot within the purchased credit: it does NOT authorize auto-deployment,
additional credit, scheduled operation, broker access or an assurance of a dollar
hard cap. Confirm actual org balance and auto-reload OFF in Platform before use.

**Preflight**: use the existing isolated Windows checkout and venv (NOT the live V10
or Excel folder). Require a private session OPENAI_API_KEY. Never paste the secret
into chat or write it to .env/GitHub. First pull this exact PR branch and run offline
tests. Use `examples/agent_sdk_public_synthetic_20261021.json`, which explicitly
contains ONLY fictional test inputs; any resulting hypotheses are NOT trade advice.

    .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_agent_sdk_coordination_pilot.py -v
    .\.venv\Scripts\python.exe scripts/agent_sdk_coordination_pilot.py --input examples/agent_sdk_public_synthetic_20261021.json --offline-test

**Controlled single-run CLI (only after offline PASS and OWNER consent to spend)**:

    .\.venv\Scripts\python.exe scripts/agent_sdk_coordination_pilot.py --input examples/agent_sdk_public_synthetic_20261021.json --enable-billable-api --paid-budget-db "<private-local-path>\paid_attempts.sqlite" --receipt-db "<private-local-path>\receipts.sqlite"

Fail-closed paid gates at exact revision:
- The complete four-role run ID is transactionally reserved BEFORE the first
  external request, using private SQLite WAL-independent synchronous FULL and
  BEGIN IMMEDIATE. A crash or error consumes the reservation and can never be
  silently retried with the same ID. Different run IDs require explicit manual
  authorization; no automatic scheduler is installed.
- A paid attempt reserves **$1 of a lifetime local $8 reservation allowance**
  (eight attempted runs maximum). This is intentionally conservative against
  the purchased $10 balance, but IS NOT an actual-dollar hard spending ceiling;
  actual provider usage can differ and must be checked in Billing.
- Paid input JSON <=8 KB; model pinned `gpt-5.4-mini`; per agent
  `max_turns=1`, maximum 600 output tokens, 30-second request timeout,
  no network/tools, and OpenAI client `max_retries=0`.
  Maximum planned model calls for a three-specialist plus coordinator run: 4.
- Model overrides, custom OpenAI endpoint and missing private ledger refuse to
  start without external API calls. Traces disabled. Generated role outputs are
  research-only, cannot place orders or send GitHub comments.
- An SDK/API/validation error may consume a reserved attempt and any provider
  charges; NO automatic retry, double submit, charge replacement, or resetting
  of the ledger. Review billing and ask OWNER before authorizing another ID.
- The local attempt ledger and optional receipt contain no API key, market rows,
  positions or order history. Keep files OUT of git and public Issue #282.

Actual charges, market-data provenance, source contents, scheduled specialist task
delivery, local Brain inbox and production readiness remain unverified. A synthetic
fixture with real API inference proves API orchestration only, not market edge.

## Invariants

- as_of <= available_at <= evaluation time, explicit time zone required; future/missing/invalid means BLOCKED.
- Specialist WATCH requires IDs drawn from its provided role-specific sources. Hallucinated IDs or unsupported roles mean BLOCKED.
- Coordinator receives verified specialist summaries only; it cannot call an order route or independently approve a release.
- Output is research only: real_submit_allowed=false, actual_profit_yen=null, costs_verified=false, broker_fills_verified=false, promotion_eligible=false.
- No write to existing Shadow ledgers and no changes to Brain/Risk Gate/Permission Gate/Kill Switch.
- No modification of D-023 single-Excel restriction; no live V10 launch or source-pin changes; no GitHub Issue #282 write from runtime.
- GitHub Actions executes only Python standard-library offline tests on Windows and Ubuntu, no API key or cost.

## Acceptance gates

1. Pass offline cross-platform CI and independent review on exact Draft HEAD.
2. OWNER decides source availability contracts, API budget, model/key custody and spending cap; no charge before approval.
3. In an approved private runtime, test a manual bounded four-model-call trial on SYNTHETIC inputs and independently reconcile actual Usage; no auto retry after a reserved attempt.
4. Add a read-only local Brain inbox adapter with independent source authentication, point-in-time semantics, restart persistence and receiver ACK.
5. Confirm live compatibility, Windows stop/recovery, safe source evidence and Shadow backtesting on a separate approved candidate SHA.
6. DEPLOYED and PRODUCTION_VERIFIED require independent evidence; the Draft is neither.
7. Real orders or hedges require a wholly separate explicit OWNER authorization, which is NOT granted.

Trading P/L, revenue, expenses, net profit, verified EV/PF/N and remainder to 100億 are UNKNOWN.
