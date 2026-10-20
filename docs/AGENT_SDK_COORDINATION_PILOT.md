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
